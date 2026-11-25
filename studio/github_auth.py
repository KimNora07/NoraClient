"""Per-user GitHub credentials, kept out of Nora Studio SQLite and config.json."""

import os
import sys

SERVICE = "NoraStudio.GitHub"
USERNAME = "personal-access-token"


def credential_store():
    if sys.platform != "win32":
        raise RuntimeError("토큰 앱 저장은 Windows Credential Manager에서만 지원합니다. 다른 환경에서는 NORA_GITHUB_TOKEN을 설정하세요.")
    try:
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    except (ImportError, OSError) as exc:
        raise RuntimeError("Windows 자격 증명 저장소를 열 수 없습니다") from exc


def stored_token():
    if sys.platform != "win32":
        return None
    return credential_store().get_password(SERVICE, USERNAME)


def token_source():
    if os.environ.get("NORA_GITHUB_TOKEN"):
        return "environment"
    return "windows" if stored_token() else "none"


def get_token():
    return os.environ.get("NORA_GITHUB_TOKEN") or stored_token()


def set_token(token):
    credential_store().set_password(SERVICE, USERNAME, token)


def clear_token():
    store = credential_store()
    if store.get_password(SERVICE, USERNAME):
        store.delete_password(SERVICE, USERNAME)
