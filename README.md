# Nora Studio v0.5.0 — 1인 게임 스튜디오 경영 시스템

Unity/C# 프로젝트를 Codex 앱에서 직접 개발하고, Nora Studio에서는 **프로젝트 경영·마일스톤·GitHub 개발 활동·기능 검수**를 관리합니다.

## 핵심 원칙

- **Codex 직접 실행 제거:** Nora Studio는 Codex CLI/App Server, Unity 에디터를 실행하지 않습니다. 이전 실행 API `/api/run-next`, `/api/tasks/{id}/stop`, `/api/tasks/{id}/retry`는 제거되었습니다.
- **로컬 우선:** 모든 업무·프로젝트·검수 데이터는 SQLite 파일에 저장됩니다.
- **증거 기반 완료율:** 등록된 기능 중 대표가 검수 승인한 기능의 비율만 완성률로 표시합니다. GitHub 커밋 개수는 개발 활동일 뿐 완료율이 아닙니다.
- **읽기 전용 GitHub 연동:** GitHub 공개 저장소의 최신 커밋 30개를 명시적 동기화 시 조회하고 SQLite에 중복 없이 저장합니다. 코드 변경·푸시·병합을 수행하지 않습니다.
- **대표 승인:** 기능의 근거 URL을 제출한 후 대표가 검수 승인 또는 반려합니다. 반려 시 사유가 필요합니다.
- **이전 데이터 보존:** 기존 `projects`, `tasks`, `agents`, `approvals`, `activity` 테이블을 변경 없이 유지하며 필요한 컬럼·테이블을 추가합니다. `tasks`는 UI에서 읽기 전용 아카이브로 표시합니다.

## 설치 및 실행

### 설치형 Windows 앱

GitHub Releases의 `NoraStudio-Setup-0.5.0.exe`를 설치합니다(릴리스 빌드 후 제공).
앱 실행 시 `config.json`의 `noraToken`으로 관리자 접속할 수 있으며, 토큰 없이 게스트 조회도 가능합니다.

### Python 개발 실행

```powershell
cd nora-studio
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:NORA_DATA = "$PWD\data"
$env:NORA_TOKEN = "여기에-안전한-관리자-토큰"
.venv\Scripts\python.exe -m uvicorn studio.app:app --host 127.0.0.1 --port 8765
```

브라우저에서 `http://127.0.0.1:8765`에 접속합니다.

### 설치 파일 직접 빌드

Windows에서 Python 3.12, Inno Setup 6을 설치한 후 `windows\Build-Installer.bat` 실행.
성공 시 `installer-output\NoraStudio-Setup-0.5.0.exe` 생성.

## 업무 흐름

1. 프로젝트 등록 및 GitHub 공개 저장소(`owner/repo`) 연결
2. 개발 목표를 마일스톤으로 등록
3. 기능별 검증 가능한 완료 조건 정의
4. Codex 앱에서 Unity 프로젝트 개발하고 GitHub에 커밋/PR 생성
5. Nora Studio에서 **GitHub 동기화**로 활동 이력 확인
6. 기능의 GitHub 근거 URL 제출 → 대표 검수 승인/반려
7. 모든 연결 기능이 검증되면 마일스톤 완료 처리

## SQLite 마이그레이션

앱이 시작될 때 `init_db()`가 기존 DB에 다음을 추가합니다.

| 테이블/컬럼 | 용도 |
|---|---|
| `projects.github_repo` | 공개 GitHub 저장소 경로 |
| `milestones` | 프로젝트별 목표와 기한 |
| `features` | 기능/완료 조건/근거/검수 상태 |
| `feature_reviews` | 승인·반려 감사 이력 |
| `github_commits` | 읽기 전용 커밋 캐시 (프로젝트+SHA 중복 방지) |

기존 `studio.sqlite3`는 삭제하지 않습니다. 업데이트 전에는 데이터 파일을 별도로 백업하는 것을 권장합니다.

## GitHub 연동 정책

- 형식: `KimNora07/NoraClient` 또는 `https://github.com/KimNora07/NoraClient`
- GitHub REST API를 사용하며 공개 저장소는 별도 토큰 없이 조회 가능
- 선택: `NORA_GITHUB_TOKEN` 환경 변수를 설정하면 등록된 토큰으로 조회(비공개 저장소 지원을 보장하지 않음)
- API 장애, 레이트 제한, 네트워크 오류는 사용자에게 표시하며 기존 SQLite 데이터는 유지
- 커밋이 없더라도 기능이 자동 반려되지 않고, 커밋이 많더라도 자동 검수되지 않음

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions 워크플로 `.github/workflows/windows-release.yml`에서 Windows EXE 및 Inno Setup 설치 파일을 생성하고 Releases에 게시할 수 있습니다.
