import importlib
import json
import sys


def test_desktop_config_defaults_to_guest_and_no_codex(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NoraStudio.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    module = importlib.import_module("desktop")
    assert module.config() == 8765
    config = json.loads((tmp_path / "local" / "NoraStudio" / "config.json").read_text(encoding="utf-8"))
    assert config["adminToken"] == ""
    assert config["codexEnabled"] is False
    assert config["autoRunApprovedTasks"] is False
    assert (tmp_path / "local" / "NoraStudio" / "data").as_posix() in module.os.environ["NORA_DATA"].replace("\\", "/")


def test_legacy_config_migrates_to_user_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "NoraStudio.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    legacy = tmp_path / "NoraStudio.config.json"
    legacy.write_text(json.dumps({"port": 8899, "adminToken": "legacy-secret", "codexEnabled": False}), encoding="utf-8")
    module = importlib.import_module("desktop")
    assert module.config() == 8899
    migrated = tmp_path / "local" / "NoraStudio" / "config.json"
    assert json.loads(migrated.read_text(encoding="utf-8"))["adminToken"] == "legacy-secret"


def test_desktop_uses_qt_webengine_without_edge_dependency():
    import inspect
    module = importlib.import_module("desktop")
    source = inspect.getsource(module.run_desktop_window)
    assert "QWebEngineView" in source
    assert "QSystemTrayIcon" in source
