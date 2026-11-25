"""Local-first, approval-gated Nora Studio prototype.

Run with: uvicorn studio.app:app --host 127.0.0.1 --port 8765
"""

import os
import re
import secrets
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

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
RELEASE_REPO = os.environ.get("NORA_RELEASE_REPO", "")
UPDATE_DIR = DATA.parent / "updates"
_ready_update = None


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
        c.execute("""CREATE TABLE IF NOT EXISTS milestones (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            title TEXT NOT NULL, due_date TEXT, status TEXT NOT NULL DEFAULT 'planned',
            created_at TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES projects(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS features (
            id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL,
            milestone_id INTEGER, title TEXT NOT NULL, criteria TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned', evidence_url TEXT NOT NULL DEFAULT '',
            review_note TEXT NOT NULL DEFAULT '', reviewed_at TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id))""")
        c.execute("""CREATE TABLE IF NOT EXISTS feature_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT, feature_id INTEGER NOT NULL,
            decision TEXT NOT NULL, note TEXT NOT NULL, evidence_url TEXT NOT NULL,
            decided_at TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS github_commits (
            project_id INTEGER NOT NULL, sha TEXT NOT NULL, message TEXT NOT NULL,
            author TEXT NOT NULL, committed_at TEXT, url TEXT NOT NULL,
            PRIMARY KEY(project_id, sha))""")
        existing_projects = {r[1] for r in c.execute("PRAGMA table_info(projects)")}
        if "github_repo" not in existing_projects:
            c.execute("ALTER TABLE projects ADD COLUMN github_repo TEXT NOT NULL DEFAULT ''")
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
                                ("code_reported_at", "TEXT"),
                                ("codex_thread_id", "TEXT"), ("codex_turn_id", "TEXT"),
                                ("attempt", "INTEGER NOT NULL DEFAULT 0")]:
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


class ProjectInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = Field(default="", max_length=3000)
    stage: str = Field(default="prototype", pattern="^(idea|prototype|production|testing|released)$")
    repo_path: str = Field(default="", max_length=700)
    github_repo: str = Field(default="", max_length=150)


class MilestoneInput(BaseModel):
    project_id: int
    title: str = Field(min_length=2, max_length=160)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class MilestoneStatus(BaseModel):
    status: str = Field(pattern="^(planned|active|done)$")


class FeatureInput(BaseModel):
    project_id: int
    milestone_id: int | None = None
    title: str = Field(min_length=2, max_length=160)
    criteria: str = Field(min_length=5, max_length=3000)


class FeatureSubmit(BaseModel):
    evidence_url: str = Field(min_length=6, max_length=700)
    note: str = Field(default="", max_length=2000)


class FeatureReview(BaseModel):
    decision: str = Field(pattern="^(accept|reject)$")
    note: str = Field(default="", max_length=2000)


class AgentInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(min_length=2, max_length=120)
    provider: str = Field(pattern="^(ollama|codex)$")
    model: str = Field(min_length=2, max_length=120)
    instructions: str = Field(default="", max_length=6000)
    enabled: bool = True


def record(c, category, message):
    c.execute("INSERT INTO activity(category,message,created_at) VALUES(?,?,?)", (category, message, now()))


def exists(c, table, item_id):
    return c.execute(f"SELECT 1 FROM {table} WHERE id=?", (item_id,)).fetchone() is not None


def validate_github_repo(value):
    raw = value.strip().removeprefix("https://github.com/").removesuffix("/")
    if raw and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        raise HTTPException(422, "GitHub 저장소는 owner/repository 형식으로 입력하세요")
    return raw


def get_task(task_id):
    with connect() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Task not found")
    return dict(row)


@asynccontextmanager
async def lifespan(_):
    # Legacy SQLite data is preserved; no agent subprocesses run at startup.
    init_db()
    yield


app = FastAPI(title="Nora Studio", lifespan=lifespan)


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "dashboard.html")


@app.get("/api/health")
def health(admin: bool = Depends(guest_or_admin)):
    return {"model": MODEL, "mode": "management", "codex_enabled": False,
            "auto_run": False, "role": "admin" if admin else "guest"}


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
        feature_counts = {r["status"]:r["total"] for r in c.execute("SELECT status,COUNT(*) total FROM features GROUP BY status")}
        milestone_counts = {r["status"]:r["total"] for r in c.execute("SELECT status,COUNT(*) total FROM milestones GROUP BY status")}
        commit_count = c.execute("SELECT COUNT(*) FROM github_commits").fetchone()[0]
        overdue = c.execute("""SELECT COUNT(*) FROM milestones WHERE status!='done'
            AND due_date IS NOT NULL AND due_date < date('now')""").fetchone()[0]
    return {"projects": projects_count, "agents": agents_count, "statuses": counts,
            "pending_approvals": feature_counts.get("review",0), "recent": recent,
            "features":feature_counts,"milestones":milestone_counts,
            "github_commits":commit_count,"overdue_milestones":overdue}


@app.get("/api/projects")
def projects(admin: bool = Depends(guest_or_admin)):
    with connect() as c:
        result = [dict(r) for r in c.execute("""SELECT p.*,
            (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id) task_count,
            (SELECT COUNT(*) FROM tasks t WHERE t.project_id=p.id AND t.status='done') done_count,
            (SELECT COUNT(*) FROM features f WHERE f.project_id=p.id) feature_count,
            (SELECT COUNT(*) FROM features f WHERE f.project_id=p.id AND f.status='verified') verified_count
            FROM projects p ORDER BY p.id DESC""")]
    if not admin:
        for p in result:
            p["repo_path"] = ""
    return result


@app.post("/api/projects", dependencies=[Depends(auth)])
def create_project(payload: ProjectInput):
    github_repo = validate_github_repo(payload.github_repo)
    with connect() as c:
        cur = c.execute("INSERT INTO projects(name,description,stage,repo_path,github_repo,created_at) VALUES(?,?,?,?,?,?)",
                        (payload.name, payload.description, payload.stage, payload.repo_path, github_repo, now()))
        record(c, "project", f"프로젝트 생성: {payload.name}")
        project_id = cur.lastrowid
    with connect() as c:
        return dict(c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())


@app.patch("/api/projects/{project_id}", dependencies=[Depends(auth)])
def update_project(project_id: int, payload: ProjectInput):
    github_repo = validate_github_repo(payload.github_repo)
    with connect() as c:
        result = c.execute("""UPDATE projects SET name=?,description=?,stage=?,repo_path=?,github_repo=? WHERE id=?""",
                           (payload.name,payload.description,payload.stage,payload.repo_path,github_repo,project_id))
        if not result.rowcount:
            raise HTTPException(404, "Project not found")
        record(c,"project",f"프로젝트 설정 변경: #{project_id}")
    return {"ok": True}


@app.get("/api/milestones", dependencies=[Depends(guest_or_admin)])
def milestones(project_id: int | None = None):
    with connect() as c:
        return [dict(r) for r in c.execute("""SELECT m.*,
            (SELECT COUNT(*) FROM features f WHERE f.milestone_id=m.id) feature_count,
            (SELECT COUNT(*) FROM features f WHERE f.milestone_id=m.id AND f.status='verified') verified_count
            FROM milestones m WHERE (? IS NULL OR m.project_id=?) ORDER BY m.id DESC""",
            (project_id,project_id))]


@app.post("/api/milestones", dependencies=[Depends(auth)])
def create_milestone(payload: MilestoneInput):
    with connect() as c:
        if not exists(c,"projects",payload.project_id):
            raise HTTPException(422,"Unknown project")
        cur = c.execute("INSERT INTO milestones(project_id,title,due_date,created_at) VALUES(?,?,?,?)",
                        (payload.project_id,payload.title,payload.due_date,now()))
        record(c,"milestone",f"마일스톤 등록: {payload.title}")
        return {"id":cur.lastrowid,"status":"planned"}


@app.patch("/api/milestones/{milestone_id}", dependencies=[Depends(auth)])
def update_milestone(milestone_id: int, payload: MilestoneStatus):
    with connect() as c:
        if payload.status == "done":
            total, pending = c.execute("""SELECT COUNT(*),SUM(CASE WHEN status!='verified' THEN 1 ELSE 0 END)
                FROM features WHERE milestone_id=?""",(milestone_id,)).fetchone()
            if not total or pending:
                raise HTTPException(409,"완료하려면 하나 이상의 기능이 등록되고 모두 검증되어야 합니다")
        cur = c.execute("UPDATE milestones SET status=? WHERE id=?",(payload.status,milestone_id))
        if not cur.rowcount: raise HTTPException(404,"Milestone not found")
        record(c,"milestone",f"마일스톤 #{milestone_id}: {payload.status}")
    return {"ok":True}


@app.get("/api/features", dependencies=[Depends(guest_or_admin)])
def features(project_id: int | None = None):
    with connect() as c:
        return [dict(r) for r in c.execute("""SELECT * FROM features
            WHERE (? IS NULL OR project_id=?) ORDER BY id DESC""",(project_id,project_id))]


@app.post("/api/features", dependencies=[Depends(auth)])
def create_feature(payload: FeatureInput):
    with connect() as c:
        if not exists(c,"projects",payload.project_id):
            raise HTTPException(422,"Unknown project")
        if payload.milestone_id is not None and not c.execute(
            "SELECT 1 FROM milestones WHERE id=? AND project_id=?",
            (payload.milestone_id,payload.project_id)).fetchone():
            raise HTTPException(422,"Milestone belongs to another project")
        cur = c.execute("""INSERT INTO features(project_id,milestone_id,title,criteria,created_at,updated_at)
            VALUES(?,?,?,?,?,?)""",(payload.project_id,payload.milestone_id,payload.title,payload.criteria,now(),now()))
        record(c,"feature",f"완료 조건 등록: {payload.title}")
        return {"id":cur.lastrowid,"status":"planned"}


@app.post("/api/features/{feature_id}/submit", dependencies=[Depends(auth)])
def submit_feature(feature_id: int, payload: FeatureSubmit):
    # Evidence is only a reference, not automatic proof of correctness.
    evidence = payload.evidence_url.strip()
    parsed = urlsplit(evidence)
    if parsed.scheme != "https" or parsed.hostname not in ("github.com","gist.github.com") or not parsed.path.strip("/") or parsed.username or parsed.password:
        raise HTTPException(422,"GitHub 근거 URL을 입력하세요")
    with connect() as c:
        cur = c.execute("""UPDATE features SET status='review',evidence_url=?,review_note=?,
            reviewed_at=NULL,updated_at=? WHERE id=? AND status IN ('planned','rejected','verified')""",
            (evidence,payload.note,now(),feature_id))
        if not cur.rowcount:
            raise HTTPException(409,"Feature not found or already awaiting review")
        record(c,"feature",f"기능 #{feature_id}: 대표 검수 요청")
    return {"status":"review"}


@app.post("/api/features/{feature_id}/review", dependencies=[Depends(auth)])
def review_feature(feature_id: int, payload: FeatureReview):
    status = "verified" if payload.decision == "accept" else "rejected"
    with connect() as c:
        row = c.execute("SELECT evidence_url FROM features WHERE id=? AND status='review'",(feature_id,)).fetchone()
        if not row: raise HTTPException(409,"Only submitted features can be reviewed")
        if status == "rejected" and not payload.note.strip():
            raise HTTPException(422,"반려 사유를 입력하세요")
        c.execute("UPDATE features SET status=?,review_note=?,reviewed_at=?,updated_at=? WHERE id=?",
                  (status,payload.note,now(),now(),feature_id))
        c.execute("INSERT INTO feature_reviews(feature_id,decision,note,evidence_url,decided_at) VALUES(?,?,?,?,?)",
                  (feature_id,payload.decision,payload.note,row["evidence_url"],now()))
        record(c,"review",f"기능 #{feature_id}: {status}")
    return {"status":status}


@app.get("/api/feature-reviews", dependencies=[Depends(guest_or_admin)])
def feature_reviews():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM feature_reviews ORDER BY id DESC LIMIT 100")]


@app.post("/api/projects/{project_id}/github/sync", dependencies=[Depends(auth)])
def sync_github(project_id: int):
    with connect() as c:
        row = c.execute("SELECT github_repo FROM projects WHERE id=?",(project_id,)).fetchone()
    if not row: raise HTTPException(404,"Project not found")
    repo = validate_github_repo(row["github_repo"])
    if not repo: raise HTTPException(409,"프로젝트에 GitHub 저장소를 설정하세요")
    headers = {"Accept":"application/vnd.github+json","User-Agent":"NoraStudio/0.5.0"}
    github_token = os.environ.get("NORA_GITHUB_TOKEN")
    if github_token: headers["Authorization"] = f"Bearer {github_token}"
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.get(f"https://api.github.com/repos/{repo}/commits",
                                  params={"per_page":30},headers=headers)
            response.raise_for_status()
            items = response.json()
        if not isinstance(items,list): raise ValueError("GitHub returned invalid commit data")
    except (httpx.HTTPError,ValueError) as exc:
        raise HTTPException(502,f"GitHub 커밋 조회 실패: {exc}") from exc
    count = 0
    with connect() as c:
        for item in items:
            sha = item.get("sha","")
            detail = item.get("commit") or {}
            if not re.fullmatch(r"[0-9a-f]{40}",sha): continue
            author = detail.get("author") or {}
            url = f"https://github.com/{repo}/commit/{sha}"
            cur = c.execute("""INSERT OR IGNORE INTO github_commits
                (project_id,sha,message,author,committed_at,url) VALUES(?,?,?,?,?,?)""",
                (project_id,sha,str(detail.get("message","")).splitlines()[0][:500],
                 str(author.get("name") or "Unknown")[:120],author.get("date"),url))
            count += cur.rowcount
        record(c,"github",f"{repo}: 최근 커밋 동기화 · 새 기록 {count}개")
    return {"fetched":len(items),"new":count}


@app.get("/api/github-activity", dependencies=[Depends(guest_or_admin)])
def github_activity(project_id: int | None = None):
    with connect() as c:
        return [dict(r) for r in c.execute("""SELECT * FROM github_commits
            WHERE (? IS NULL OR project_id=?) ORDER BY committed_at DESC LIMIT 100""",
            (project_id,project_id))]


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




