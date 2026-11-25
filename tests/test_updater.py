import hashlib
import io
import json

import pytest

from studio import updater


def test_release_requires_git_hub_asset_digest(monkeypatch):
    binary = b"signed-by-release-digest"
    digest = hashlib.sha256(binary).hexdigest()
    release = {"tag_name": "v0.3.5", "body": "Patch notes", "assets": [{
        "name": "NoraStudio-Setup-0.3.5.exe", "digest": f"sha256:{digest}",
        "browser_download_url": "https://github.com/nora-dev/nora-studio/releases/download/v0.3.5/NoraStudio-Setup-0.3.5.exe",
        "size": len(binary),
    }]}
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(json.dumps(release).encode()))
    info = updater.latest_release("nora-dev/nora-studio")
    assert info["available"] is True
    assert info["digest"] == digest
    assert updater.latest_release("https://github.com/nora-dev/nora-studio")["latest"] == "v0.3.5"
    with pytest.raises(ValueError):
        updater.normalize_repo("https://evil.example/nora-dev/nora-studio")


def test_download_verifies_exact_digest(tmp_path, monkeypatch):
    binary = b"installer payload"
    release = {"filename": "NoraStudio-Setup-0.3.4.exe", "size": len(binary),
               "digest": hashlib.sha256(binary).hexdigest(),
               "download_url": "https://github.com/nora-dev/nora-studio/releases/download/v0.3.4/NoraStudio-Setup-0.3.4.exe"}
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(binary))
    installed = updater.download_release(release, tmp_path)
    assert installed.read_bytes() == binary
    bad = dict(release, digest="0" * 64)
    with pytest.raises(ValueError, match="무결성"):
        updater.download_release(bad, tmp_path)
