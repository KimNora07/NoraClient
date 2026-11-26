import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from studio import app as module, automation


@pytest.fixture
def studio(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'DATA', tmp_path)
    monkeypatch.setattr(module, 'DB', tmp_path / 'studio.sqlite3')
    monkeypatch.setattr(module, 'TOKEN', 'test-secret')
    module.init_db()
    with module.connect() as c:
        c.execute("INSERT INTO projects(name,description,stage,repo_path,created_at,github_repo) VALUES(?,?,?,?,?,?)",
                  ('Arcadia', '', 'prototype', '', module.now(), 'KimNora07/NoraClient'))
    return TestClient(module.app)


def _github_commit(sha):
    return {'sha': sha, 'commit': {'message': 'fix map collision',
            'author': {'name': 'Nora', 'date': '2026-11-26T00:00:00Z'}}}


def test_background_queue_preserves_baseline_and_requires_review(studio, monkeypatch):
    monkeypatch.setattr(automation.github_auth, 'get_token', lambda: None)
    sha_old, sha_new = 'a' * 40, 'b' * 40
    items = [_github_commit(sha_old)]
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return list(items)
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, *args, **kwargs):
            return FakeResponse()
    monkeypatch.setattr(automation.httpx, 'Client', FakeClient)
    automation.poll_github(module.connect)
    assert not studio.get('/api/automation/overview').json()['jobs']
    items.insert(0, _github_commit(sha_new))
    automation.poll_github(module.connect)
    automation.poll_github(module.connect)
    jobs = studio.get('/api/automation/overview').json()['jobs']
    assert len(jobs) == 4
    assert {j['source_sha'] for j in jobs} == {sha_new}
    assert automation.process_one(module.connect, ai_enabled=False)
    reports = studio.get('/api/automation/overview').json()['reports']
    assert len(reports) == 1
    assert reports[0]['status'] == 'pending'
    assert reports[0]['generator'] == 'facts'
    assert '커밋' in reports[0]['body']
    assert studio.post(f'/api/automation/reports/{reports[0]["id"]}/review', json={
        'decision': 'approved', 'note': ''}).status_code == 401
    assert studio.post(f'/api/automation/reports/{reports[0]["id"]}/review', json={
        'decision': 'approved', 'note': ''}, headers={'X-Nora-Token': 'test-secret'}).status_code == 200


def test_pause_is_durable_and_guest_cannot_change(studio):
    assert studio.post('/api/automation/pause', json={'enabled': True}).status_code == 401
    assert studio.post('/api/automation/pause', json={'enabled': True},
                       headers={'X-Nora-Token': 'test-secret'}).status_code == 200
    assert studio.get('/api/automation/overview').json()['paused']
    with module.connect() as c:
        assert automation.setting(c, 'paused') == '1'
        automation.initialize(c)
        assert automation.setting(c, 'paused') == '1'


def test_existing_database_keeps_previous_records(studio):
    with module.connect() as c:
        c.execute("INSERT INTO workdays(work_date,started_at) VALUES('2026-11-25',?)", (module.now(),))
        c.execute("INSERT INTO features(project_id,title,criteria,created_at,updated_at) VALUES(?,?,?,?,?)",
                  (1, 'Map', 'No overlapping corridors', module.now(), module.now()))
    module.init_db()
    with module.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM workdays').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM features').fetchone()[0] == 1
