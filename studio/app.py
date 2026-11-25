"""Local-first, approval-gated Nora Studio prototype.

Run with: uvicorn studio.app:app --host 127.0.0.1 --port 8765
"""

import asyncio
import json
import os
import queue
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from studio import updater

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA = Path(os.environ.get("NORA_DATA", str(BASE / "data"))).resolve()
DB = DATA / "studio.sqlite3"
REPO = Path(os.environ.get("NORA_REPO", "")).expanduser()
TOKEN = os.environ.get("NORA_TOKEN", "")
MODEL = os.environ.get("NORA_MODEL", "qwen3:8b")
OLLAMA = os.environ.get("NORA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
CODEX_ENABLED = os.environ.get("NORA_CODEX_ENABLED", "0") == "1"
AUTO_RUN = os.environ.get("NORA_AUTO_RUN", "0") == "1"
MAX_RUNTIME = int(os.environ.get("NORA_CODEX_TIMEOUT", "1200"))
RELEASE_REPO = os.environ.get("NORA_RELEASE_REPO", "")
UPDATE_DIR = DATA.parent / "updates"
_ready_update = None
lock = asyncio.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            description TEXT NOT NULL, acceptance TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft', branch TEXT,
            log TEXT DEFAULT '', approved_at TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL DEFAULT 'prototype',
            repo_path TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            role TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
            instructions TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1)""")
        c.execute("""CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
            decision TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            message TEXT NOT NULL, created_at TEXT NOT NULL)""")
        existing = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
        for col, definition in [("project_id", "INTEGER"), ("agent_id", "INTEGER"),
                                ("priority", "TEXT NOT NULL DEFAULT 'medium'"),
                                ("progress", "INTEGER NOT NULL DEFAULT 0"),
                                ("current_step", "TEXT NOT NULL DEFAULT '승인 대기'"),
                                ("last_activity", "TEXT"),
                                ("code_percent", "INTEGER"),
                                ("code_completed", "INTEGER NOT NULL DEFAULT 0"),
                                ("code_total", "INTEGER NOT NULL DEFAULT 0"),
                                ("changed_files", "TEXT NOT NULL DEFAULT '[]'"),
                                ("code_reported_at", "TEXT")]:
            if col not in existing:
                c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {definition}")
        if c.execute("SELECT COUNT(*) FROM agents").fetchone()[0] == 0:
            c.executemany("INSERT INTO agents(name,role,provider,model,instructions) VALUES(?,?,?,?,?)", [
                ("AI 운영실장", "Project Manager", "ollama", MODEL, "작업 분석 및 승인 요청"),
                ("AI 게임 기획자", "Game Designer", "ollama", MODEL, "명세와 완료 조건 작성"),
                ("AI 프로그래머", "Unity C# Developer", "codex", "Codex", "승인된 작업만 구현"),
                ("AI QA 엔지니어", "QA Engineer", "ollama", MODEL, "검증 가능한 결과 보고"),
            ])
        # Never automatically rerun a process interrupted by shutdown.
        c.execute("UPDATE tasks SET status='interrupted', current_step='앱 종료로 중단', updated_at=? WHERE status='running'", (now(),))
        # Older databases keep their existing workflow, without fabricated completion percentages.
        c.execute("UPDATE tasks SET progress=100, current_step='최종 승인 완료' WHERE status='done'")


def auth(x_nora_token: str | None = Header(default=None)):
    if not TOKEN or TOKEN == "CHANGE_ME":
        raise HTTPException(503, "Set a secure NORA_TOKEN before starting")
    if not x_nora_token or not secrets.compare_digest(x_nora_token, TOKEN):
        raise HTTPException(401, "Invalid studio token")


def guest_or_admin(x_nora_token: str | None = Header(default=None)):
    """Read-only local guest; only a valid token grants write privileges."""
    if x_nora_token:
        auth(x_nora_token)
        return True
    return False


class TaskInput(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=5, max_length=8000)
    acceptance: str = Field(min_length=5, max_length=4000)
    project_id: int | None = None
    agent_id: int | None = None
    priority: str = Field(default="medium", pattern="^(low|medium|high|critical)$")


class ProjectInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=3000)
    stage: str = Field(default="prototype", pattern="^(idea|prototype|production|testing|released)$")
    repo_path: str = Field(default="", max_length=700)


class AgentInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(min_length=2, max_length=120)
    provider: str = Field(pattern="^(ollama|codex)$")
    model: str = Field(min_length=2, max_length=120)
    instructions: str = Field(default="", max_length=6000)
    enabled: bool = True


class DecisionInput(BaseModel):
    note: str = Field(default="", max_length=2000)


def record(c, category, message):
    c.execute("INSERT INTO activity(category,message,created_at) VALUES(?,?,?)", (category, message, now()))


def exists(c, table, item_id):
    return c.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone() is not None


class PlanInput(BaseModel):
    idea: str = Field(min_length=5, max_length=4000)


def get_task(task_id):
    with connect() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    return dict(row)


def transition(task_id, before, after):
    milestones = {"approved": (10, "대표 승인 완료 · 실행 대기"),
                  "running": (15, "Git 환경 점검 중"),
                  "done": (100, "최종 승인 완료"),
                  "review": (85, "Codex 종료 · 대표 검토 대기")}
    with connect() as c:
        progress, step = milestones.get(after, (None, None))
        cur = c.execute(
            "UPDATE tasks SET status=?, progress=COALESCE(?,progress), current_step=COALESCE(?,current_step), last_activity=?, updated_at=?, approved_at=CASE WHEN ?='approved' THEN ? ELSE approved_at END WHERE id=? AND status=?",
            (after, progress, step, now(), now(), after, now(), task_id, before),
        )
        if cur.rowcount != 1:
            raise HTTPException(409, "Task state changed; refresh")
        record(c, "task", f"#{task_id}: {before} → {after}")
    return get_task(task_id)


def command(args, cwd, timeout=30):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          errors="replace", timeout=timeout, check=False)


def find_executable(name, extra_paths=()):
    """Resolve a tool independently of the frozen desktop app's search path."""
    discovered = shutil.which(name)
    if discovered:
        return str(Path(discovered).resolve())
    for candidate in extra_paths:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return None


def tool_commands():
    """Use absolute paths; never pass task text through a Windows batch shell."""
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    git = find_executable("git", [
        Path(program_files) / "Git" / "cmd" / "git.exe",
        Path(local) / "Programs" / "Git" / "cmd" / "git.exe" if local else None,
    ])
    if not git:
        raise FileNotFoundError("Git 실행 파일을 찾을 수 없습니다. Git for Windows를 설치하고 Nora Studio를 재시작하세요.")

    codex = find_executable("codex.exe")
    if codex:
        return git, [codex]
    shim = find_executable("codex.cmd", [
        Path(roaming) / "npm" / "codex.cmd" if roaming else None,
        Path(local) / "npm" / "codex.cmd" if local else None,
    ])
    if shim:
        # npm's Windows shim is a .cmd file. Run its JS entrypoint via Node
        # instead of relying on CreateProcess/.cmd argument quoting.
        entrypoint = Path(shim).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = find_executable("node.exe", [Path(program_files) / "nodejs" / "node.exe"])
        if entrypoint.is_file() and node:
            return git, [node, str(entrypoint)]
        raise FileNotFoundError("Codex npm 실행 파일은 발견했지만 Node.js 또는 codex.js를 찾지 못했습니다. npm install -g @openai/codex 로 재설치하세요.")
    codex = find_executable("codex")
    if codex and Path(codex).suffix.lower() not in (".cmd", ".bat"):
        return git, [codex]
    raise FileNotFoundError("Codex CLI 실행 파일을 찾을 수 없습니다. npm install -g @openai/codex 후 Nora Studio를 재시작하세요.")


def progress_update(task_id, value, step, log=None):
    """Report verified workflow milestones; never estimate AI code completion."""
    stamp = now()
    with connect() as c:
        if log is None:
            c.execute("UPDATE tasks SET progress=?,current_step=?,last_activity=?,updated_at=? WHERE id=? AND status='running'",
                      (value, step, stamp, stamp, task_id))
        else:
            c.execute("UPDATE tasks SET progress=?,current_step=?,last_activity=?,updated_at=?,log=? WHERE id=? AND status='running'",
                      (value, step, stamp, stamp, log[-32000:], task_id))


def criteria_list(acceptance):
    """One nonblank completion criterion per line; no invented substeps."""
    lines = [line.strip().lstrip("-• ") for line in acceptance.splitlines() if line.strip()]
    return lines[:30]


def inspect_code_progress(task_id, cwd, git="git"):
    """Verify an AI-reported criterion only when its evidence file changed in Git."""
    result = command([git, "status", "--porcelain", "-z", "--untracked-files=all"], cwd, 8)
    if result.returncode:
        return
    filenames = []
    entries = result.stdout.split("\0")
    i = 0
    while i < len(entries) and entries[i]:
        entry = entries[i]
        if len(entry) < 4:
            break
        filenames.append(entry[3:])
        i += 2 if entry[0] in "RC" or entry[1] in "RC" else 1
    changed = sorted(set(name for name in filenames if name != ".nora-progress.json"))[:100]
    task = get_task(task_id)
    criteria = criteria_list(task["acceptance"])
    completed = 0
    report_path = cwd / ".nora-progress.json"
    reported = False
    if report_path.is_file() and report_path.stat().st_size <= 32768:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            items = report.get("items", [])
            if isinstance(items, list) and len(items) == len(criteria):
                for criterion, item in zip(criteria, items):
                    if not isinstance(item, dict) or item.get("title") != criterion:
                        continue
                    evidence = item.get("evidence")
                    if not item.get("done") or not isinstance(evidence, str) or evidence not in changed:
                        continue
                    candidate = (cwd / evidence).resolve()
                    if candidate.is_relative_to(cwd.resolve()) and candidate.is_file():
                        completed += 1
                reported = True
        except (OSError, ValueError, TypeError):
            pass
    percent = round(completed / len(criteria) * 100) if reported and criteria else None
    stamp = now()
    changed_json = json.dumps(changed, ensure_ascii=False)
    evidence_changed = changed_json != (task.get("changed_files") or "[]") or percent != task.get("code_percent")
    with connect() as c:
        c.execute("""UPDATE tasks SET code_percent=?, code_completed=?,code_total=?,
                     changed_files=?,code_reported_at=CASE WHEN ? THEN ? ELSE code_reported_at END,
                     last_activity=CASE WHEN ? THEN ? ELSE last_activity END
                     WHERE id=? AND status='running'""",
                  (percent, completed, len(criteria), changed_json,
                   int(reported and evidence_changed), stamp, int(evidence_changed), stamp, task_id))


def stream_codex(task_id, args, cwd, prompt=None, git="git"):
    """Stream merged CLI output safely without blocking the API event loop."""
    proc = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)
    if prompt is not None:
        proc.stdin.write(prompt)
        proc.stdin.close()
    lines = queue.Queue()
    def read_output():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    output = ""
    started = time.monotonic()
    last_flush = 0
    finished = False
    dirty = False
    progress_update(task_id, 35, "Codex 프로세스 실행 중 · 완료율 미확인")
    try:
        while not finished:
            if time.monotonic() - started > MAX_RUNTIME:
                raise subprocess.TimeoutExpired(args, MAX_RUNTIME)
            try:
                line = lines.get(timeout=0.5)
                if line is None:
                    finished = True
                else:
                    output = (output + line)[-32000:]
                    dirty = True
            except queue.Empty:
                pass
            if time.monotonic() - last_flush > 2:
                inspect_code_progress(task_id, cwd, git)
                if dirty:
                    progress_update(task_id, 35, "Codex 코드 작업 중", output)
                last_flush = time.monotonic()
                dirty = False
        proc.wait(timeout=5)
        inspect_code_progress(task_id, cwd, git)
        return proc.returncode, output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def do_work(task_id):
    task = get_task(task_id)
    if not CODEX_ENABLED:
        return "disabled", "Codex is disabled: set NORA_CODEX_ENABLED=1"
    with connect() as c:
        project = c.execute("SELECT repo_path FROM projects WHERE id=?", (task.get("project_id"),)).fetchone()
        agent = c.execute("SELECT provider,enabled FROM agents WHERE id=?", (task.get("agent_id"),)).fetchone()
    if agent is not None and (agent["provider"] != "codex" or not agent["enabled"]):
        return "failed", "Execution requires an enabled Codex agent"
    repo = Path(project["repo_path"]).expanduser() if project and project["repo_path"] else REPO
    if not repo.is_dir() or not (repo / ".git").exists():
        return "failed", "NORA_REPO or project repo_path must point to a Git working tree"
    try:
        git, codex = tool_commands()
        state = command([git, "status", "--porcelain"], repo)
        if state.returncode or state.stdout.strip():
            return "failed", "Git worktree is not clean; preserve existing changes before running"
        branch = f"ai/nora-{task_id}-{int(time.time())}"
        # Do not change the user's currently checked-out branch: create a separate worktree.
        worktrees = DATA / "worktrees"
        worktrees.mkdir(parents=True, exist_ok=True)
        target = worktrees / f"task-{task_id}-{int(time.time())}"
        created = command([git, "worktree", "add", "-b", branch, str(target), "HEAD"], repo, 60)
        if created.returncode:
            return "failed", created.stderr[-5000:]
        with connect() as c:
            c.execute("UPDATE tasks SET branch=? WHERE id=?", (branch, task_id))
        progress_update(task_id, 25, "격리된 Git 작업 공간 준비 완료")
        prompt = (
            "You are a Unity C# developer. Perform ONLY this approved task. "
            "Read AGENTS.md if present. Do not push, merge, deploy, delete assets, "
            "or modify unrelated files. Do not modify Unity scenes or prefabs. "
            "Report tests actually run, otherwise state 'not run'.\n\n"
            "For progress reporting, maintain .nora-progress.json in the worktree. "
            "Its schema is {\"items\": [{\"title\": exact acceptance criterion, "
            "\"done\": true/false, \"evidence\": relative path to a file you changed}]}. "
            "Use exactly the acceptance criteria below in order, one nonempty line per item. "
            "Only mark done after implementation and cite a real modified file. "
            "Update this file during the task, not only at the end. "
            "This is self-reported progress; final review is performed by the owner.\n\n"
            f"Title: {task['title']}\nRequirements: {task['description']}\n"
            f"Acceptance criteria: {task['acceptance']}\n"
        )
        # Non-interactive Codex. Always isolated to a task-specific worktree.
        exit_code, output = stream_codex(task_id, codex + ["exec", "--sandbox", "workspace-write", "-"], target, prompt=prompt, git=git)
        status = "review" if exit_code == 0 else "failed"
        return status, f"Worktree: {target}\nBranch: {branch}\nExit: {exit_code}\n{output}"
    except FileNotFoundError as exc:
        return "failed", f"Required executable unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return "interrupted", "Codex timed out. Inspect its worktree before retrying."
    except Exception as exc:
        return "failed", f"Execution error: {type(exc).__name__}: {exc}"


async def run_next():
    if lock.locked():
        return
    async with lock:
        with connect() as c:
            row = c.execute("SELECT id FROM tasks WHERE status='approved' ORDER BY id LIMIT 1").fetchone()
        if not row:
            return
        task_id = row["id"]
        transition(task_id, "approved", "running")
        status, log = await asyncio.to_thread(do_work, task_id)
        with connect() as c:
            next_progress = 85 if status == "review" else 35
            next_step = "Codex 종료 · 대표 검토 대기" if status == "review" else "실행 종료 · 오류/중단 확인"
            c.execute("UPDATE tasks SET status=?, log=?, progress=?,current_step=?,last_activity=?,updated_at=? WHERE id=? AND status='running'",
                      (status, log, next_progress, next_step, now(), now(), task_id))
            record(c, "execution", f"#{task_id}: {status}")


async def worker_loop():
    while True:
        if AUTO_RUN and CODEX_ENABLED:
            await run_next()
        await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_):
    init_db()
    worker = asyncio.create_task(worker_loop())
    try:
        yield
    finally:
        worker.cancel()


app = FastAPI(title="Nora Studio", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "dashboard.html")


@app.get("/api/health")
def health(admin: bool = Depends(guest_or_admin)):
    return {"model": MODEL, "codex_enabled": CODEX_ENABLED,
            "auto_run": AUTO_RUN, "repo": str(REPO) if admin else "관리자 전용",
            "role": "admin" if admin else "guest"}


@app.get("/api/update/check", dependencies=[Depends(auth)])
def check_update():
    if not RELEASE_REPO.strip():
        return {"configured": False, "current": updater.APP_VERSION, "available": False}
    try:
        return updater.latest_release(RELEASE_REPO)
    except (ValueError, OSError, TimeoutError) as exc:
        raise HTTPException(502, f"GitHub 업데이트 확인 실패: {exc}") from exc


@app.post("/api/update/download", dependencies=[Depends(auth)])
def download_update():
    global _ready_update
    if not RELEASE_REPO.strip():
        raise HTTPException(400, "config.json에서 releaseRepo를 먼저 설정하세요.")
    try:
        release = updater.latest_release(RELEASE_REPO)
        if not release["available"]:
            raise HTTPException(409, "새로운 버전이 없습니다.")
        verified = updater.download_release(release, UPDATE_DIR)
        _ready_update = (str(verified), release["size"], release["digest"])
        return {"ready": True, "version": release["latest"], "filename": verified.name}
    except HTTPException:
        raise
    except (ValueError, OSError, TimeoutError) as exc:
        raise HTTPException(502, f"업데이트 다운로드/검증 실패: {exc}") from exc


@app.post("/api/update/install", dependencies=[Depends(auth)])
def install_update():
    global _ready_update
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise HTTPException(409, "자동 설치는 Windows 설치형 Nora Studio.exe에서만 가능합니다.")
    if lock.locked():
        raise HTTPException(409, "Codex 업무 실행이 끝난 후 업데이트하세요.")
    if not _ready_update:
        raise HTTPException(409, "검증된 다운로드가 없습니다. 업데이트를 다시 다운로드하세요.")
    path, expected_size, expected_digest = _ready_update
    if not updater.verify_file(path, expected_size, expected_digest):
        _ready_update = None
        raise HTTPException(409, "설치 직전 해시 검증에 실패했습니다. 다시 다운로드하세요.")
    updater.prepare_install(path)
    _ready_update = None
    return {"scheduled": True, "message": "앱 종료 후 설치 프로그램이 실행됩니다."}


@app.get("/api/dashboard", dependencies=[Depends(guest_or_admin)])
def dashboard():
    with connect() as c:
        counts = {r["status"]: r["total"] for r in c.execute("SELECT status, COUNT(*) total FROM tasks GROUP BY status")}
        projects_count = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        agents_count = c.execute("SELECT COUNT(*) FROM agents WHERE enabled=1").fetchone()[0]
        recent = [dict(r) for r in c.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 12")]
    return {"projects": projects_count, "agents": agents_count, "statuses": counts,
            "pending_approvals": counts.get("draft", 0) + counts.get("review", 0), "recent": recent}


@app.get("/api/projects")
def projects(admin: bool = Depends(guest_or_admin)):
    with connect() as c:
        result = [dict(r) for r in c.execute("""SELECT p.*,
            (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_count,
            (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') done_count
            FROM projects p ORDER BY p.id DESC""")]
    if not admin:
        for p in result:
            p["repo_path"] = ""
    return result


@app.post("/api/projects", dependencies=[Depends(auth)])
def create_project(payload: ProjectInput):
    with connect() as c:
        cur = c.execute("INSERT INTO projects(name,description,stage,repo_path,created_at) VALUES(?,?,?,?,?)",
                        (payload.name, payload.description, payload.stage, payload.repo_path, now()))
        record(c, "project", f"프로젝트 생성: {payload.name}")
        project_id = cur.lastrowid
    with connect() as c:
        return dict(c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())


@app.get("/api/agents")
def agents(admin: bool = Depends(guest_or_admin)):
    with connect() as c:
        result = [dict(r) for r in c.execute("""SELECT a.*,
            (SELECT COUNT(*) FROM tasks t WHERE t.agent_id=a.id AND t.status IN ('approved','running','review')) active_tasks
            FROM agents a ORDER BY a.id""")]
    if not admin:
        for a in result:
            a["instructions"] = ""
    return result


@app.post("/api/agents", dependencies=[Depends(auth)])
def create_agent(payload: AgentInput):
    with connect() as c:
        cur = c.execute("INSERT INTO agents(name,role,provider,model,instructions,enabled) VALUES(?,?,?,?,?,?)",
                        (payload.name,payload.role,payload.provider,payload.model,payload.instructions,int(payload.enabled)))
        record(c, "agent", f"직원 등록: {payload.name}")
        agent_id = cur.lastrowid
    with connect() as c:
        return dict(c.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone())


@app.patch("/api/agents/{agent_id}", dependencies=[Depends(auth)])
def update_agent(agent_id: int, payload: AgentInput):
    with connect() as c:
        cur = c.execute("UPDATE agents SET name=?,role=?,provider=?,model=?,instructions=?,enabled=? WHERE id=?",
                        (payload.name,payload.role,payload.provider,payload.model,payload.instructions,int(payload.enabled),agent_id))
        if not cur.rowcount:
            raise HTTPException(404, "Agent not found")
        record(c, "agent", f"직원 설정 변경: {payload.name}")
    return {"ok": True}


@app.get("/api/approvals", dependencies=[Depends(guest_or_admin)])
def approvals():
    with connect() as c:
        pending = [dict(r) for r in c.execute("SELECT * FROM tasks WHERE status IN ('draft','review') ORDER BY id DESC")]
        history = [dict(r) for r in c.execute("SELECT * FROM approvals ORDER BY id DESC LIMIT 50")]
    return {"pending": pending, "history": history}


@app.get("/api/tasks")
def tasks(admin: bool = Depends(guest_or_admin)):
    with connect() as c:
        result = [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()]
    if not admin:
        for t in result:
            t["log"] = ""
    return result


@app.post("/api/tasks", dependencies=[Depends(auth)])
def create_task(payload: TaskInput):
    with connect() as c:
        if payload.project_id is not None and not exists(c, "projects", payload.project_id):
            raise HTTPException(422, "Unknown project")
        if payload.agent_id is not None and not exists(c, "agents", payload.agent_id):
            raise HTTPException(422, "Unknown agent")
        cur = c.execute("""INSERT INTO tasks(title,description,acceptance,project_id,agent_id,priority,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?)""", (payload.title,payload.description,payload.acceptance,
            payload.project_id,payload.agent_id,payload.priority,now(),now()))
        task_id = cur.lastrowid
        record(c, "task", f"업무 초안 등록: #{task_id} {payload.title}")
    return get_task(task_id)


@app.post("/api/tasks/{task_id}/approve", dependencies=[Depends(auth)])
def approve(task_id: int, decision: DecisionInput | None = None):
    result = transition(task_id, "draft", "approved")
    with connect() as c:
        c.execute("INSERT INTO approvals(task_id,decision,note,decided_at) VALUES(?,?,?,?)",
                  (task_id,"approved",decision.note if decision else "",now()))
    return result


@app.post("/api/tasks/{task_id}/reject", dependencies=[Depends(auth)])
def reject(task_id: int, decision: DecisionInput | None = None):
    result = transition(task_id, "draft", "rejected")
    with connect() as c:
        c.execute("INSERT INTO approvals(task_id,decision,note,decided_at) VALUES(?,?,?,?)",
                  (task_id,"rejected",decision.note if decision else "",now()))
    return result


@app.post("/api/tasks/{task_id}/complete", dependencies=[Depends(auth)])
def complete(task_id: int, decision: DecisionInput | None = None):
    result = transition(task_id, "review", "done")
    with connect() as c:
        c.execute("INSERT INTO approvals(task_id,decision,note,decided_at) VALUES(?,?,?,?)",
                  (task_id,"review_accepted",decision.note if decision else "",now()))
    return result


@app.post("/api/tasks/{task_id}/request-changes", dependencies=[Depends(auth)])
def request_changes(task_id: int, decision: DecisionInput | None = None):
    result = transition(task_id, "review", "changes_requested")
    with connect() as c:
        c.execute("INSERT INTO approvals(task_id,decision,note,decided_at) VALUES(?,?,?,?)",
                  (task_id,"changes_requested",decision.note if decision else "",now()))
    return result


@app.post("/api/run-next", dependencies=[Depends(auth)])
async def run_one():
    if not CODEX_ENABLED:
        raise HTTPException(409, "Enable Codex explicitly first")
    if lock.locked():
        raise HTTPException(409, "Another task is running")
    asyncio.create_task(run_next())
    return {"message": "Run requested. Refresh the task list."}


@app.post("/api/plan", dependencies=[Depends(auth)])
async def plan(payload: PlanInput):
    system = (
        "You are Nora Studio's Unity game production manager. In Korean, propose "
        "a scoped task with concise title, implementation requirements, and "
        "testable acceptance criteria. You cannot authorize execution. "
        "Respond ONLY as JSON with string keys title, description, acceptance."
    )
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            result = await client.post(f"{OLLAMA}/api/chat", json={
                "model": MODEL, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": payload.idea}],
                "options": {"num_ctx": 4096}})
            result.raise_for_status()
        content = result.json()["message"]["content"]
        proposal = TaskInput.model_validate(json.loads(content))
        return proposal.model_dump()  # A proposal, never an approved task.
    except (ValueError, KeyError, httpx.HTTPError) as exc:
        raise HTTPException(502, f"Local model error: {type(exc).__name__}: {exc}") from exc
