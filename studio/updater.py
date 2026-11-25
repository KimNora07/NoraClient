"""Opt-in updater for public GitHub Releases; never runs an unverified installer."""

import hashlib
import json
import re
import urllib.request
from pathlib import Path

APP_VERSION = "0.4.0"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
MAX_DOWNLOAD_BYTES = 850 * 1024 * 1024
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "NoraStudio-Updater"}
_pending_install = None


def normalize_repo(value):
    repo = (value or "").strip()
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):].strip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not REPO_PATTERN.fullmatch(repo) or ".." in repo:
        raise ValueError("releaseRepo는 GitHub 공개 저장소 owner/repo 형식이어야 합니다.")
    return repo


def parse_version(value):
    match = VERSION_PATTERN.fullmatch(value or "")
    if not match:
        raise ValueError("지원되지 않는 릴리스 버전 형식입니다. 예: v0.3.4")
    return tuple(map(int, match.groups()))


def latest_release(repo):
    repo = normalize_repo(repo)
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as response:
        release = json.load(response)
    tag = release.get("tag_name", "")
    newer = parse_version(tag) > parse_version(APP_VERSION)
    result = {"configured": True, "current": APP_VERSION, "latest": tag, "available": newer,
              "notes": (release.get("body") or "")[:5000], "repo": repo}
    if not newer:
        return result
    name = f"NoraStudio-Setup-{tag.removeprefix('v')}.exe"
    asset = next((a for a in release.get("assets", []) if a.get("name") == name), None)
    if not asset:
        raise ValueError(f"릴리스에 {name} 설치 파일이 없습니다.")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("GitHub 릴리스 자산에 SHA-256 digest가 없어 자동 설치를 중단합니다.")
    url = asset.get("browser_download_url", "")
    if not url.startswith(f"https://github.com/{repo}/releases/download/"):
        raise ValueError("릴리스 다운로드 주소가 신뢰할 수 있는 형식이 아닙니다.")
    size = asset.get("size", 0)
    if not isinstance(size, int) or not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise ValueError("설치 파일 크기가 허용 범위를 벗어났습니다.")
    result.update({"filename": name, "download_url": url,
                   "digest": digest[7:].lower(), "size": size})
    return result


def download_release(release, folder):
    """Atomic download with size and SHA-256 checks; reuse only verified bytes."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    filename = release["filename"]
    if not re.fullmatch(r"NoraStudio-Setup-\d+\.\d+\.\d+\.exe", filename):
        raise ValueError("설치 파일 이름이 유효하지 않습니다.")
    final = folder / filename
    part = folder / (filename + ".part")
    expected_hash = release["digest"]
    expected_size = release["size"]

    if verify_file(final, expected_size, expected_hash):
        return final
    try:
        req = urllib.request.Request(release["download_url"], headers=HEADERS)
        total = 0
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=60) as response, part.open("wb") as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                total += len(chunk)
                if total > expected_size:
                    raise ValueError("다운로드 파일이 예상 크기를 초과했습니다.")
                h.update(chunk)
                output.write(chunk)
        if total != expected_size or h.hexdigest() != expected_hash:
            raise ValueError("다운로드 무결성 검증 실패. 설치하지 않습니다.")
        part.replace(final)
        return final
    finally:
        part.unlink(missing_ok=True)


def verify_file(path, expected_size, expected_hash):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != expected_size:
        return False
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest() == expected_hash


def prepare_install(path):
    global _pending_install
    _pending_install = str(Path(path).resolve())


def consume_install_request():
    global _pending_install
    requested = _pending_install
    _pending_install = None
    return requested


def make_helper(folder):
    """PowerShell helper waits for app exit, installs, then relaunches the app."""
    helper = Path(folder) / "apply-update.ps1"
    helper.write_text('''param([int]$ParentProcessId, [string]$InstallerPath, [string]$AppPath)
$limit = (Get-Date).AddSeconds(45)
while ((Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $limit)) {
    Start-Sleep -Milliseconds 350
}
if (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue) { exit 3 }
$result = Start-Process -FilePath $InstallerPath -ArgumentList '/SILENT','/NORESTART','/CLOSEAPPLICATIONS' -PassThru -Wait
if ($result.ExitCode -eq 0) { Start-Process -FilePath $AppPath }
exit $result.ExitCode
''', encoding="utf-8")
    return helper
