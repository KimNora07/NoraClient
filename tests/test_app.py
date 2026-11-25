import importlib
import sqlite3

from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "test-secret")
    m = importlib.reload(importlib.import_module("studio.app"))
    client = TestClient(m.app)
    client.__enter__()
    return m, client, {"X-Nora-Token": "test-secret"}


def test_management_has_no_codex_execution(tmp_path, monkeypatch):
    m, c, h = make_client(tmp_path, monkeypatch)
    try:
        assert c.get("/api/health").json()["mode"] == "management"
        assert c.post("/api/run-next", headers=h).status_code == 404
        assert c.post("/api/tasks/1/stop", headers=h).status_code == 404
        assert c.get("/").status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_project_milestone_feature_review_flow(tmp_path, monkeypatch):
    m, c, h = make_client(tmp_path, monkeypatch)
    try:
        project = c.post("/api/projects", headers=h, json={"name":"Arcadia","github_repo":"KimNora07/NoraClient"}).json()
        mid = c.post("/api/milestones", headers=h, json={"project_id":project["id"],"title":"Map prototype","due_date":"2026-12-01"}).json()["id"]
        fid = c.post("/api/features", headers=h, json={"project_id":project["id"],"milestone_id":mid,
            "title":"Treasure node", "criteria":"Map node is connected and scene loads"}).json()["id"]
        assert c.patch(f"/api/milestones/{mid}",headers=h,json={"status":"done"}).status_code == 409
        assert c.post(f"/api/features/{fid}/review",headers=h,json={"decision":"accept"}).status_code == 409
        assert c.post(f"/api/features/{fid}/submit",headers=h,json={"evidence_url":"https://github.com/KimNora07/NoraClient/commit/a"*1}).status_code == 200
        assert c.post(f"/api/features/{fid}/review",headers=h,json={"decision":"accept","note":"EditMode passed"}).json()["status"] == "verified"
        assert c.patch(f"/api/milestones/{mid}",headers=h,json={"status":"done"}).status_code == 200
        assert c.get("/api/dashboard").json()["features"]["verified"] == 1
        assert c.get("/api/projects").json()[0]["verified_count"] == 1
        assert c.get("/api/feature-reviews").json()[0]["note"] == "EditMode passed"
    finally:
        c.__exit__(None, None, None)


def test_rejected_feature_requires_reason_and_resubmission(tmp_path, monkeypatch):
    m, c, h = make_client(tmp_path, monkeypatch)
    try:
        p = c.post("/api/projects",headers=h,json={"name":"Arcadia"}).json()
        f = c.post("/api/features",headers=h,json={"project_id":p["id"],"title":"Map collision","criteria":"All paths are connected"}).json()
        url = "https://github.com/KimNora07/NoraClient/pull/1"
        assert c.post(f"/api/features/{f['id']}/submit",headers=h,json={"evidence_url":"file:///tmp/a"}).status_code == 422
        assert c.post(f"/api/features/{f['id']}/submit",headers=h,json={"evidence_url":url}).status_code == 200
        assert c.post(f"/api/features/{f['id']}/review",headers=h,json={"decision":"reject"}).status_code == 422
        assert c.post(f"/api/features/{f['id']}/review",headers=h,json={"decision":"reject","note":"Re-test"}).json()["status"] == "rejected"
        assert c.post(f"/api/features/{f['id']}/submit",headers=h,json={"evidence_url":url}).status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_guest_read_only_and_legacy_data_preserved(tmp_path, monkeypatch):
    m, c, h = make_client(tmp_path, monkeypatch)
    try:
        with m.connect() as db:
            cur = db.execute("""INSERT INTO tasks(title,description,acceptance,created_at,updated_at,log)
                VALUES('Legacy task','Previously submitted task','Manual verification',?,?,?)""",
                (m.now(),m.now(),"PRIVATE_LOG"))
            task_id = cur.lastrowid
        assert c.get("/api/tasks").json()[0]["log"] == ""
        assert c.get("/api/tasks",headers=h).json()[0]["log"] == "PRIVATE_LOG"
        assert c.post("/api/tasks",headers=h,json={"title":"No longer possible"}).status_code == 405
        assert c.post("/api/features",json={"project_id":1,"title":"Secret","criteria":"Cannot write"}).status_code == 401
        m.init_db()
        assert m.get_task(task_id)["log"] == "PRIVATE_LOG"
    finally:
        c.__exit__(None, None, None)


def test_github_sync_deduplicates_and_does_not_mark_verified(tmp_path, monkeypatch):
    m, c, h = make_client(tmp_path, monkeypatch)
    try:
        p = c.post("/api/projects",headers=h,json={"name":"Arcadia","github_repo":"KimNora07/NoraClient"}).json()
        f = c.post("/api/features",headers=h,json={"project_id":p["id"],"title":"Test feature","criteria":"Manual test passes"}).json()
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self):
                return [{"sha":"a"*40,"commit":{"message":"Fix Map nodes\nBody","author":{"name":"Nora","date":"2026-11-26T10:00:00Z"}}}]
        class FakeClient:
            def __init__(self,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def get(self,*args,**kwargs): return FakeResponse()
        monkeypatch.setattr(m.httpx,"Client",FakeClient)
        assert c.post(f"/api/projects/{p['id']}/github/sync",headers=h).json()["new"] == 1
        assert c.post(f"/api/projects/{p['id']}/github/sync",headers=h).json()["new"] == 0
        assert len(c.get("/api/github-activity").json()) == 1
        assert c.get("/api/features").json()[0]["status"] == "planned"
    finally:
        c.__exit__(None, None, None)


def test_migrate_v01_sqlite_without_removing_existing_tables(tmp_path, monkeypatch):
    with sqlite3.connect(tmp_path/"studio.sqlite3") as db:
        db.execute("""CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,
            description TEXT NOT NULL,acceptance TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
            branch TEXT,log TEXT DEFAULT '',approved_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
        db.execute("INSERT INTO tasks(title,description,acceptance,created_at,updated_at) VALUES('Old','Old task','Old criteria','date','date')")
    monkeypatch.setenv("NORA_DATA",str(tmp_path))
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    assert m.get_task(1)["title"] == "Old"
    with m.connect() as db:
        assert "github_repo" in [x[1] for x in db.execute("PRAGMA table_info(projects)")]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='features'").fetchone()
