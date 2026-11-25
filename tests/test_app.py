import importlib


def test_approval_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "test-secret")
    monkeypatch.setenv("NORA_CODEX_ENABLED", "0")
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    created = m.create_task(m.TaskInput(title="Dimension node", description="Add event data model", acceptance="EditMode tests pass"))
    assert created["status"] == "draft"
    try:
        m.transition(created["id"], "approved", "running")
        assert False, "Unapproved task was runnable"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    approved = m.approve(created["id"])
    assert approved["status"] == "approved"
    assert approved["progress"] == 10
    try:
        m.approve(created["id"])
        assert False, "Double approval succeeded"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409


def test_execution_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_CODEX_ENABLED", "0")
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    created = m.create_task(m.TaskInput(title="Dimension node", description="Add event data model", acceptance="EditMode tests pass"))
    status, message = m.do_work(created["id"])
    assert status == "disabled"
    assert "disabled" in message


def test_project_agent_and_review_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "test-secret")
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    project = m.create_project(m.ProjectInput(name="Arcadia", description="Deckbuilder"))
    agent = m.agents()[2]
    task = m.create_task(m.TaskInput(
        title="Treasure event", description="Create treasure event data",
        acceptance="All event choices validated", project_id=project["id"],
        agent_id=agent["id"], priority="high"))
    assert task["project_id"] == project["id"]
    assert m.dashboard()["pending_approvals"] == 1
    assert m.approve(task["id"], m.DecisionInput(note="Go"))["status"] == "approved"
    assert m.approvals()["history"][0]["decision"] == "approved"
    # Simulate successful execution (no external Codex invocation).
    running = m.transition(task["id"], "approved", "running")
    assert running["progress"] == 15
    m.progress_update(task["id"], 35, "Codex 실행 중", "real CLI output")
    assert m.get_task(task["id"])["log"] == "real CLI output"
    assert m.transition(task["id"], "running", "review")["progress"] == 85
    assert m.complete(task["id"], m.DecisionInput(note="Reviewed"))["progress"] == 100
    assert m.projects()[0]["done_count"] == 1


def test_cli_output_is_streamed_to_task(tmp_path, monkeypatch):
    import sys
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    task = m.create_task(m.TaskInput(title="Simple script", description="Create a script", acceptance="Script exists"))
    m.transition(task["id"], "draft", "approved")
    m.transition(task["id"], "approved", "running")
    code, output = m.stream_codex(task["id"], [sys.executable, "-c", "print('work started')"], tmp_path)
    assert code == 0
    assert "work started" in output
    assert "work started" in m.get_task(task["id"])["log"]


def test_verified_code_progress_requires_real_changed_evidence(tmp_path, monkeypatch):
    import json
    import subprocess
    monkeypatch.setenv("NORA_DATA", str(tmp_path / "data"))
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    task = m.create_task(m.TaskInput(title="Two scripts", description="Create two scripts", acceptance="Script A exists\nScript B exists"))
    m.transition(task["id"], "draft", "approved")
    m.transition(task["id"], "approved", "running")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "A.cs").write_text("class A {}")
    (repo / ".nora-progress.json").write_text(json.dumps({"items": [
        {"title": "Script A exists", "done": True, "evidence": "A.cs"},
        {"title": "Script B exists", "done": True, "evidence": "missing.cs"},
    ]}))
    m.inspect_code_progress(task["id"], repo)
    progress = m.get_task(task["id"])
    assert progress["code_percent"] == 50
    assert progress["code_completed"] == 1
    assert json.loads(progress["changed_files"]) == ["A.cs"]


def test_migrate_v01_db(tmp_path, monkeypatch):
    import sqlite3
    db = tmp_path / "studio.sqlite3"
    with sqlite3.connect(db) as c:
        c.execute("""CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT NOT NULL, acceptance TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', branch TEXT,
            log TEXT DEFAULT '', approved_at TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""")
        c.execute("INSERT INTO tasks(title,description,acceptance,created_at,updated_at) VALUES('Legacy','Old task','Old criterion','date','date')")
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    assert m.tasks()[0]["title"] == "Legacy"
    assert "project_id" in m.tasks()[0]
    assert len(m.agents()) == 4


def test_http_auth_and_workflow(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "secret-token")
    monkeypatch.setenv("NORA_CODEX_ENABLED", "0")
    m = importlib.reload(importlib.import_module("studio.app"))
    with TestClient(m.app) as client:
        assert client.get("/api/tasks").status_code == 200
        assert client.get("/api/health").json()["role"] == "guest"
        headers = {"X-Nora-Token": "secret-token"}
        assert client.get("/", headers=headers).status_code == 200
        p = client.post("/api/projects", headers=headers, json={"name": "Arcadia"})
        assert p.status_code == 200
        a = client.get("/api/agents", headers=headers).json()
        t = client.post("/api/tasks", headers=headers, json={
            "title": "Treasure node", "description": "Implement reward table",
            "acceptance": "Relevant tests pass", "project_id": p.json()["id"],
            "agent_id": a[2]["id"], "priority": "high"})
        assert t.status_code == 200
        task_id = t.json()["id"]
        assert client.post("/api/run-next", headers=headers).status_code == 409
        assert client.post(f"/api/tasks/{task_id}/approve", headers=headers, json={"note": "approved"}).status_code == 200
        assert client.get("/api/dashboard", headers=headers).json()["pending_approvals"] == 0
        assert client.get("/api/approvals", headers=headers).json()["history"][0]["note"] == "approved"


def test_guest_is_read_only_and_logs_are_hidden(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "secret-token")
    m = importlib.reload(importlib.import_module("studio.app"))
    with TestClient(m.app) as client:
        task = client.post("/api/tasks", headers={"X-Nora-Token": "secret-token"}, json={
            "title": "Secret task", "description": "Test guest access", "acceptance": "Guest cannot write"}).json()
        with m.connect() as c:
            c.execute("UPDATE tasks SET log='PRIVATE_LOG' WHERE id=?", (task["id"],))
        assert client.get("/api/tasks").json()[0]["log"] == ""
        assert client.get("/api/tasks", headers={"X-Nora-Token": "secret-token"}).json()[0]["log"] == "PRIVATE_LOG"
        assert client.post(f"/api/tasks/{task['id']}/approve").status_code == 401
        assert client.post("/api/projects", json={"name":"Guest Project"}).status_code == 401
        assert client.post("/api/run-next").status_code == 401
        assert client.get("/api/health", headers={"X-Nora-Token":"bad"}).status_code == 401
