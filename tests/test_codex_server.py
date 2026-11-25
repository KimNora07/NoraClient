import sys

from studio.codex_server import AppServerSession


FAKE_SERVER = r'''
import json, sys
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if 'id' not in message: continue
    if method == 'thread/start':
        result = {'thread': {'id': 'thread-1'}}
    elif method == 'turn/start':
        result = {'turn': {'id': 'turn-1'}}
    else:
        result = {}
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
    if method == 'turn/start':
        print(json.dumps({'method': 'item/agentMessage/delta', 'params': {'delta': '코드를 수정했습니다'}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'id': 'turn-1', 'status': 'completed'}}}), flush=True)
'''


def test_app_server_handshake_and_utf8_stream(tmp_path):
    events = []
    session = AppServerSession([sys.executable, "-u", "-c", FAKE_SERVER], tmp_path, events.append)
    try:
        assert session.start("한글 작업 지시", tmp_path) == ("thread-1", "turn-1")
        assert session.wait(5) == "completed"
        assert any(e.get("params", {}).get("delta") == "코드를 수정했습니다" for e in events)
    finally:
        session.close()


def test_retry_requires_fresh_approval(tmp_path, monkeypatch):
    import importlib
    monkeypatch.setenv("NORA_DATA", str(tmp_path))
    monkeypatch.setenv("NORA_TOKEN", "test-secret")
    m = importlib.reload(importlib.import_module("studio.app"))
    m.init_db()
    task = m.create_task(m.TaskInput(title="Retry task", description="Update C sharp script", acceptance="Compilation succeeds"))
    m.transition(task["id"], "draft", "approved")
    m.transition(task["id"], "approved", "running")
    m.transition(task["id"], "running", "failed")
    retried = m.retry_task(task["id"])
    assert retried["status"] == "draft"
    assert retried["progress"] == 0
    assert m.approve(task["id"])["status"] == "approved"
    from fastapi import HTTPException
    try:
        m.retry_task(task["id"])
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        assert False, "An approved task must not be reset"
