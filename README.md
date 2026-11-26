# Nora Studio v0.6.0 — Executive Office

## v0.6.0 대표 집무실

- 출근 시 날짜별 업무일(`workdays`)을 생성하고 현재 SQLite 데이터 기반 **출근 브리핑**을 기록합니다. 같은 날 중복 출근은 막습니다.
- AI 부서 보고는 운영실장, 개발팀장, 기획자, QA 팀장을 대상으로 생성합니다. 기본값은 **규칙 기반 사실 브리핑**이고, `config.json`의 `aiReportsEnabled: true`로 설정하고 Ollama를 실행하면 선택적으로 로컬 AI 초안을 작성합니다. AI를 사용하지 않았을 때는 AI 작성으로 표시하지 않습니다.
- 보고서와 경영 안건은 각각 독립된 **대표 승인/반려 기록**을 보존합니다. 이 결재는 실제 Git/Unity 프로젝트를 자동으로 수정하지 않습니다.
- 회사 일정과 회의록용 날짜·시간·프로젝트 연결, 일정 완료·취소 상태를 관리합니다.
- 퇴근 시 대표 메모와 현재 누적 기능 검수 현황을 분리 기록합니다. 일간 순증가량으로 표시하지 않습니다.
- 기존 `projects`, `tasks`, `features`, `github_commits` 등 SQLite 데이터는 그대로 보존하고 새 테이블만 추가합니다.

### CEO 근무 시나리오

1. 앱 실행 → **대표 집무실** → `출근하기`
2. 프로젝트 현황·검수 대기·지연된 마일스톤 브리핑 확인
3. **부서 보고**에서 필요한 부서의 보고서 초안 생성 후 근거 확인
4. **전자결재**에서 보고서를 승인·반려하고 경영 안건 기록
5. **회사 일정**에 회의·검수·마감을 등록
6. Codex 앱과 Unity에서 직접 개발한 뒤 GitHub 동기화
7. **퇴근 보고 작성**으로 하루를 마무리

### 로컬 Ollama 선택 사용

`%LOCALAPPDATA%\NoraStudio\config.json`의 `aiReportsEnabled`를 `true`로 설정하고 앱을 재시작하세요.
모델 이름은 기존 `model` 설정(기본 `qwen3:8b`)을 사용합니다. 비활성화되거나 응답하지 않을 경우에는 AI 결과인 척하지 않고 근거 기반 일반 브리핑으로 돌아갑니다.
Ollama 결과는 자동 승인되지 않으며, 출처 사실을 재확인할 책임은 대표에게 있습니다.

### 새로운 SQLite 테이블

| 테이블 | 용도 |
|---|---|
| `workdays` | 출퇴근 시각, 목표, 퇴근 메모·요약 |
| `executive_reports` | 부서 보고서, 근거 스냅샷, 생성 방식, 결재 이력 |
| `executive_decisions` | 경영 안건 및 승인·반려 이력 |
| `calendar_events` | 회사 회의·일정 및 상태 |

## v0.5.1 변경 사항

- PyInstaller `--onefile`을 `--onedir`로 전환했습니다. EXE와 `_internal` 폴더를 Inno Setup이 함께 설치하므로 실행 시 임시 `_MEI` 폴더에 Python DLL을 풀지 않습니다.
- 자동 업데이트 보조 프로그램은 기존 `NoraStudio.exe` 프로세스가 모두 종료되었는지 최대 90초 확인하고, 설치 종료 코드 0을 확인한 뒤 3초 대기하여 앱을 시작합니다. 실패하면 자동 재실행하지 않고 `updates/update-install.log`를 남깁니다.
- **Private 저장소 동기화:** GitHub fine-grained Personal Access Token을 설정 → GitHub 연결에서 등록하세요. 대상 저장소를 선택하고 Repository permissions의 **Contents: Read-only** 권한을 부여합니다.
- 토큰은 Windows Credential Manager에 저장합니다. SQLite나 `config.json`에 저장하지 않습니다. 다른 OS의 개발 환경은 `NORA_GITHUB_TOKEN` 환경 변수를 사용할 수 있습니다.
- GitHub 동기화는 여전히 커밋 조회 전용이며, 코드 쓰기·푸시·병합 권한이 필요하지 않습니다.

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

GitHub Releases의 `NoraStudio-Setup-0.6.0.exe`를 설치합니다(릴리스 빌드 후 제공).
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
성공 시 `installer-output\NoraStudio-Setup-0.6.0.exe` 생성.

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
- Private 저장소는 회사 설정에서 GitHub fine-grained PAT을 등록하세요. 본인 계정에서 접근 가능한 저장소를 선택하고 `Contents: Read-only`를 부여합니다.
- 토큰은 Windows Credential Manager에 별도로 보관되며 화면이나 API 응답에 값이 노출되지 않습니다.
- 선택: `NORA_GITHUB_TOKEN` 환경 변수가 있으면 Windows 저장소의 토큰보다 우선 적용됩니다.
- API 장애, 레이트 제한, 네트워크 오류는 사용자에게 표시하며 기존 SQLite 데이터는 유지
- 커밋이 없더라도 기능이 자동 반려되지 않고, 커밋이 많더라도 자동 검수되지 않음

## 테스트

```powershell
.venv\Scripts\python.exe -m pytest -q
```

GitHub Actions 워크플로 `.github/workflows/windows-release.yml`에서 Windows EXE 및 Inno Setup 설치 파일을 생성하고 Releases에 게시할 수 있습니다.
