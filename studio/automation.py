"""Bounded, read-only background company monitoring. No code execution."""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import httpx

from studio import github_auth

DEPARTMENTS = {"operations": "운영실장", "development": "개발팀장", "design": "기획팀장", "qa": "QA팀장"}
INTERVAL_SECONDS = 300


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def initialize(c):
    c.execute("""CREATE TABLE IF NOT EXISTS automation_settings (
        name TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS automation_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_key TEXT NOT NULL UNIQUE,
        project_id INTEGER NOT NULL, department TEXT NOT NULL,
        source_sha TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS automation_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE,
        project_id INTEGER NOT NULL, department TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT NOT NULL, evidence_json TEXT NOT NULL, generator TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', decision_note TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, decided_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS automation_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
        title TEXT NOT NULL, message TEXT NOT NULL, is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL)""")
    c.execute("INSERT OR IGNORE INTO automation_settings VALUES('paused','0')")
    c.execute("INSERT OR IGNORE INTO automation_settings VALUES('monitor_enabled','1')")
    # A terminated process must not strand a job in 'running'.
    c.execute("UPDATE automation_jobs SET status='pending' WHERE status='running'")


def setting(c, name):
    row = c.execute("SELECT value FROM automation_settings WHERE name=?", (name,)).fetchone()
    return row[0] if row else None


def notify(c, kind, title, message):
    c.execute("INSERT INTO automation_notifications(kind,title,message,created_at) VALUES(?,?,?,?)",
              (kind, title, message[:500], stamp()))


def poll_github(connect):
    """Fetch up to 30 recent commits per repository; enqueue one batch per project poll.

    Only commits first seen AFTER the monitoring baseline are queued; older cached
    history and a project's initial import do not create artificial employee work.
    """
    with connect() as c:
        if setting(c, 'paused') == '1' or setting(c, 'monitor_enabled') != '1':
            return
        projects = [dict(r) for r in c.execute("SELECT id,name,github_repo FROM projects WHERE github_repo != ''")]
    token = github_auth.get_token()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "NoraStudio/0.7.0"}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    for project in projects:
        repo = project['github_repo'].strip()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            continue
        try:
            with httpx.Client(timeout=12, follow_redirects=False) as client:
                response = client.get(f'https://api.github.com/repos/{repo}/commits',
                                      params={'per_page': 30}, headers=headers)
                response.raise_for_status()
                items = response.json()
            if not isinstance(items, list):
                raise ValueError('Invalid GitHub response')
            with connect() as c:
                baseline_key = f'baseline:{project["id"]}:{repo}'
                baseline_set = setting(c, baseline_key) == '1'
                new_shas = []
                for item in reversed(items):
                    sha = item.get('sha', '')
                    if not re.fullmatch(r'[a-f0-9]{40}', sha):
                        continue
                    detail = item.get('commit') or {}
                    author = detail.get('author') or {}
                    inserted = c.execute("""INSERT OR IGNORE INTO github_commits
                        (project_id,sha,message,author,committed_at,url) VALUES(?,?,?,?,?,?)""",
                        (project['id'], sha, str(detail.get('message', '')).splitlines()[0][:500],
                         str(author.get('name') or 'Unknown')[:120], author.get('date'),
                         f'https://github.com/{repo}/commit/{sha}')).rowcount
                    if inserted:
                        new_shas.append(sha)
                c.execute('INSERT OR REPLACE INTO automation_settings VALUES(?,?)', (baseline_key, '1'))
                if baseline_set and new_shas:
                    latest = new_shas[-1]
                    for department in DEPARTMENTS:
                        event_key = f'{project["id"]}:{repo}:{latest}:{department}'
                        c.execute("""INSERT OR IGNORE INTO automation_jobs
                            (event_key,project_id,department,source_sha,created_at,updated_at)
                            VALUES(?,?,?,?,?,?)""",
                            (event_key, project['id'], department, latest, stamp(), stamp()))
                    notify(c, 'github', f'{project["name"]}: 새 GitHub 활동',
                           f'커밋 {len(new_shas)}개를 감지했습니다. 부서 보고서 4건이 대기 중입니다.')
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            with connect() as c:
                notify(c, 'error', f'{project["name"]}: GitHub 감시 오류', str(exc))


def process_one(connect, model='qwen3:8b', ai_enabled=False):
    with connect() as c:
        if setting(c, 'paused') == '1':
            return False
        row = c.execute("""SELECT j.*,p.name AS project_name,p.github_repo FROM automation_jobs j
            JOIN projects p ON p.id=j.project_id WHERE j.status='pending'
            ORDER BY j.id LIMIT 1""").fetchone()
        if row is None:
            return False
        job = dict(row)
        c.execute("UPDATE automation_jobs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?",
                  (stamp(), job['id']))
    try:
        with connect() as c:
            facts = [dict(r) for r in c.execute("""SELECT sha,message,author,committed_at,url
                FROM github_commits WHERE project_id=? ORDER BY committed_at DESC LIMIT 10""", (job['project_id'],))]
            feature_count = c.execute("SELECT COUNT(*) FROM features WHERE project_id=? AND status='review'",
                                      (job['project_id'],)).fetchone()[0]
        evidence = {'project': job['project_name'], 'repo': job['github_repo'],
                    'source_sha': job['source_sha'], 'recent_commits': facts, 'features_waiting_review': feature_count}
        fallback = (f"{DEPARTMENTS[job['department']]}의 자동 브리핑: {job['project_name']} GitHub 변경이 감지되었습니다. "
                    f"최근 수집 커밋 {len(facts)}개, 기능 검수 대기 {feature_count}개입니다. "
                    '커밋 존재는 빌드·테스트 통과 또는 기능 완료의 증거가 아닙니다. 대표 검수가 필요합니다.')
        body, generator = fallback, 'facts'
        if ai_enabled:
            try:
                result = httpx.post(os.environ.get('NORA_OLLAMA_URL', 'http://127.0.0.1:11434') + '/api/chat',
                    json={'model': model, 'stream': False, 'messages': [
                        {'role': 'system', 'content': f'You are a Korean game studio {DEPARTMENTS[job["department"]]}. Only use evidence supplied. Separate facts from proposals. Do not claim code was tested or built. Under 250 Korean words.'},
                        {'role': 'user', 'content': json.dumps(evidence, ensure_ascii=False)}]}, timeout=30)
                result.raise_for_status()
                candidate = result.json()['message']['content'].strip()
                if candidate:
                    body, generator = candidate[:4000], 'ollama'
            except (httpx.HTTPError, KeyError, ValueError, TypeError):
                pass
        with connect() as c:
            c.execute("""INSERT OR IGNORE INTO automation_reports
                (job_id,project_id,department,title,body,evidence_json,generator,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (job['id'], job['project_id'], job['department'],
                f'{job["project_name"]} · {DEPARTMENTS[job["department"]]} 자동 보고', body,
                json.dumps(evidence, ensure_ascii=False), generator, stamp()))
            c.execute("UPDATE automation_jobs SET status='done',error='',updated_at=? WHERE id=?", (stamp(),job['id']))
            notify(c, 'report', '새 부서 보고서 결재 대기', f'{job["project_name"]} · {DEPARTMENTS[job["department"]]}')
        return True
    except (sqlite3.Error, ValueError) as exc:
        with connect() as c:
            c.execute("UPDATE automation_jobs SET status='failed',error=?,updated_at=? WHERE id=?",
                      (str(exc)[:400], stamp(),job['id']))
            notify(c, 'error', '자동 보고서 생성 실패', str(exc))
        return False


def windows_autostart(enabled, executable=None):
    if sys.platform != 'win32':
        raise RuntimeError('Windows 앱에서만 자동 시작을 설정할 수 있습니다.')
    import winreg
    import subprocess
    executable = executable or sys.executable
    if not getattr(sys, 'frozen', False):
        raise RuntimeError('설치된 NoraStudio.exe에서만 자동 실행을 설정할 수 있습니다.')
    keypath = r'Software\Microsoft\Windows\CurrentVersion\Run'
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, keypath, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, 'NoraStudio', 0, winreg.REG_SZ,
                              subprocess.list2cmdline([executable, '--background']))
        else:
            try:
                winreg.DeleteValue(key, 'NoraStudio')
            except FileNotFoundError:
                pass


def autostart_status():
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value, _ = winreg.QueryValueEx(key, 'NoraStudio')
            return '--background' in value and os.path.normcase(sys.executable) in os.path.normcase(value)
    except (FileNotFoundError, OSError):
        return False
