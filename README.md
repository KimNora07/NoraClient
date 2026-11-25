# Nora Studio v0.3.4 — Windows Codex 실행 안정화

## 정식 Windows 설치 마법사 만들기 (NEW)

`windows/Build-Installer.bat`을 더블클릭하면 **설치 마법사 EXE**를 생성합니다. v0.3.0부터 **PySide6 + Qt WebEngine**으로 Nora Studio 자체 창을 구성하므로 Edge나 Chrome이 필요하지 않습니다. 서버와 SQLite 데이터는 기존 방식을 유지합니다.

### 빌드 PC에 필요한 것 (최초 1회)

1. Windows 10/11, Python 3.12~3.15 중 설치된 버전, 인터넷 연결
2. [Inno Setup 6](https://jrsoftware.org/isinfo.php) 설치
3. ZIP 압축 해제 후 `nora-studio/windows/Build-Installer.bat` 더블클릭

빌드가 성공하면 아래 파일이 생성됩니다.

```text
nora-studio/installer-output/NoraStudio-Setup-0.3.4.exe
```

### 설치 마법사가 제공하는 기능

- 한국어/영어 설치 UI, 설치 위치 선택
- 시작 메뉴 아이콘 생성, 바탕화면 아이콘 추가 선택
- 설치가 완료되면 Nora Studio 실행 선택
- Windows **설정 → 설치된 앱**에서 제거 가능
- 관리자 권한 없이 현재 사용자 계정에 설치
- 앱 업데이트와 제거 시 사용자 데이터 및 설정 보존

**주의:** 이번 패키지는 Windows용 설치 마법사를 생성하는 **소스와 빌드 스크립트**입니다. 현재 작업 환경에서는 Windows용 `.exe` 빌드를 수행하지 못했습니다. 설치 결과물 자체를 미리 포함한 것은 아닙니다.

사용자 데이터는 `%LOCALAPPDATA%\NoraStudio\data\studio.sqlite3`, 앱 설정은 `%LOCALAPPDATA%\NoraStudio\config.json`에 저장됩니다. 기존 EXE 옆에 있던 `NoraStudio.config.json`은 신규 저장소가 비어 있을 때 최초 실행 시 이전됩니다. 기존 스크립트 버전의 데이터는 아래 수동 마이그레이션 안내를 참고하세요.

설치·업데이트·제거 전에는 시스템 트레이의 Nora Studio 아이콘에서 **종료**를 눌러 서버를 중지하세요.

설치 후 실행 PC에는 Python이 필요하지 않습니다. 다만 실제 AI 개발을 사용하려면 Ollama, Codex CLI, Git 및 Unity를 별도로 준비해야 합니다.

## Windows 독립 실행형 EXE 빌드 (Python 런타임 포함)

**`windows/Build-Standalone-EXE.bat`을 더블클릭**하면 Windows에서 PyInstaller가 `dist/NoraStudio.exe`를 생성합니다.

1. Windows 10/11 PC에서 Python 3.12~3.15 중 하나를 설치한 후 압축 해제
2. `windows/Build-Standalone-EXE.bat` 더블클릭 (최초 실행 시 패키지 다운로드를 위해 인터넷 필요)
3. 성공하면 `dist/NoraStudio.exe` 실행
4. 최초 실행 시 `%LOCALAPPDATA%\NoraStudio\config.json`이 생성됨
5. Nora Studio 전용 창 자동 실행, 시스템 트레이의 **Nora Studio → 종료**로 서버 종료

EXE 버전에는 **Python, FastAPI, SQLite, UI 파일이 포함**되므로 실행 PC에 별도 Python 설치가 필요 없습니다. 다만 로컬 AI 기획에는 **Ollama와 Qwen3 모델**, 개발 자동화에는 **Codex CLI, Git, Unity**가 별도로 필요합니다.

**기존 데이터 마이그레이션:** 스크립트/바로가기 버전의 `data/studio.sqlite3`를 EXE 첫 실행 전에 `%LOCALAPPDATA%\NoraStudio\data\studio.sqlite3`로 복사하면 기존 프로젝트와 업무가 유지됩니다. 복사 전 두 버전의 서버를 모두 종료하고 원본을 백업하세요.

EXE는 PyInstaller `--onefile --windowed` 방식이며 **Python 런타임과 Qt WebEngine을 함께 포장한 독립 실행형 Windows 앱**입니다. 사용자는 앱 내부 창에서 대시보드를 사용하며, 주소창이나 브라우저 탭이 없습니다. 앱 창을 닫으면 시스템 트레이에서 계속 실행되고, 트레이 메뉴의 **Nora Studio 종료**로 서버까지 중지합니다. 웹 UI가 로컬 FastAPI 서버에서 표시되는 내부 구조는 유지됩니다. **현재 제공하는 것은 Windows 빌드 스크립트와 소스이며, 사전 컴파일된 `.exe` 바이너리는 아닙니다.**

관리자 설정은 `%LOCALAPPDATA%\NoraStudio\config.json`에 저장합니다. 빈 `adminToken`은 게스트 열람만 허용합니다. 평문 토큰이 들어 있으므로 구성 파일을 공개하지 마세요. `codexEnabled`와 `autoRunApprovedTasks`는 기본적으로 `false`입니다.

설정과 DB는 사용자 데이터 폴더에 저장되므로, 설치 폴더와 별개로 유지됩니다.

## Windows 앱 아이콘으로 실행하기 (권장)

이 버전에는 **Windows 바탕화면 바로가기 생성기**가 포함되어 있습니다. 독립적인 `.exe` 앱이 아니라, 바로가기에서 로컬 서버를 켜고 기본 브라우저에서 대시보드를 여는 방식입니다.

1. ZIP을 압축 해제하고 `nora-studio` 폴더를 원하는 위치에 둡니다. (설치 후 폴더를 이동하면 바로가기를 다시 만들어야 합니다.)
2. 사전 준비: Python 3.12, Git, Node.js, Ollama, Codex CLI (아래 설치 안내 참조).
3. **`windows/Install-NoraStudio.bat`을 더블클릭**합니다. 처음 실행 시 Python 의존성 설치가 필요하므로 인터넷 연결이 필요합니다.
4. 바탕화면에 **Nora Studio**와 **Nora Studio 종료** 아이콘이 생성됩니다.
5. **Nora Studio** 아이콘을 더블클릭하면 로컬 서버가 시작되고 브라우저가 열립니다.
6. **Nora Studio 종료** 아이콘을 클릭하면 이 바로가기가 시작한 서버를 종료합니다.

설치 스크립트 실행 예시 (압축 해제한 `nora-studio` 폴더의 PowerShell):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-NoraStudio.ps1
```

### 바로가기 실행 설정

`windows/launcher-settings.json`에서 설정합니다.

- `port`: 대시보드 로컬 포트 (기본값 8765)
- `adminToken`: 관리자 토큰. 빈 값이면 **게스트 열람만 가능**
- `unityRepo`: Unity Git 저장소 경로
- `codexEnabled`: 기본값 `false`; 충분히 검토한 후에만 `true`
- `autoRunApprovedTasks`: 기본값 `false`; 승인 후 자동 실행하려면 `true`

관리자 토큰을 파일에 입력하면 해당 파일에 **평문으로 저장**됩니다. 개인 PC에서만 사용하고 다른 사람에게 파일을 공유하지 마세요. 기존 PowerShell 방식처럼 서버를 수동 실행하면 환경변수도 계속 사용할 수 있습니다.

**주의:** 운영 중인 다른 Nora Studio 서버가 같은 포트를 사용한다면 새 설정이 바로 적용되지 않습니다. 서버를 먼저 종료한 뒤 다시 실행하세요. 앱 아이콘은 시스템 시작 시 자동 실행되도록 등록하지 않습니다.

Windows PC / RTX 3070 Ti Laptop 8GB VRAM / RAM 32GB에 맞춘 로컬 운영실장 + Codex 구조입니다.

## 포함 기능

- Ollama `qwen3:8b`가 한국어 업무 명세 초안 생성
- SQLite 업무 저장 (`draft → approved → running → review/failed/interrupted`)
- 대시보드에서 사용자 승인 / 반려
- 명시적으로 활성화할 경우 **승인된 작업만** Codex 실행
- 작업마다 새 Git worktree와 브랜치 생성 (기존 작업 브랜치 보존)
- 실행 로그 확인, 재부팅 중단 작업 감지
- 회사형 다크 대시보드, 프로젝트 카드, 칸반 업무 보드, AI 직원 관리, 전자결재함
- 프로젝트별 Git 저장소 경로, 업무별 담당 직원과 우선순위
- 결재 메모 및 최근 결재 이력, 활동 로그
- **v0.1 SQLite DB 자동 마이그레이션**: 기존 업무를 유지한 채 새 테이블/컬럼 추가
- 첫 접속 시 토큰 없이 **게스트 입장** 가능 (읽기 전용)
- PC가 꺼지면 작업도 멈춤; 외부 통신 기능 없음
- **v0.3.1 업무 절차 진행률**: 승인 10%, Git 준비 25%, Codex 실행 35%, 검토 대기 85%, 대표 승인 100%. 실제 코드 구현 완성률을 추측한 수치는 아닙니다.
- 실행 중 Codex 표준 출력/오류를 SQLite에 최대 최근 32KB까지 반영하고, 대시보드가 5초마다 마지막 활동 시각과 로그를 갱신합니다. CLI가 출력을 내지 않는 동안에는 진행 상황을 알 수 없습니다.
- **v0.3.2 구현률(별도 지표)**: 업무의 완료 조건을 줄별로 분리하고, Codex가 작업 공간에 생성하는 `.nora-progress.json`의 자기 보고 항목을 Git 변경 파일의 실제 존재 여부와 대조합니다. 증거가 확인된 항목 수 / 전체 항목 수를 `AI 보고 구현 기준 충족률`로 표시하며, 근거가 없으면 `측정 대기`로 표시합니다. 코드 품질·Unity 컴파일·테스트 성공의 독립적인 증명은 아닙니다.
- **v0.3.3 GitHub Releases 업데이트**: 관리자 계정의 `회사 설정 → 앱 업데이트`에서 새 버전을 확인하고, 한 번의 설치 승인으로 다운로드·검증·설치를 진행합니다. 실제 설치된 Windows EXE에서만 활성화됩니다.

## GitHub Releases 자동 업데이트 연결 (v0.3.4)

1. `nora-studio` **폴더의 내용**을 GitHub **공개 저장소의 루트**에 업로드합니다. `config.json`, `studio.sqlite3`, 관리자 토큰이나 개인 게임 소스는 절대로 공개 저장소에 올리지 마세요.
2. 저장소에 `.github/workflows/windows-release.yml`이 포함되었는지 확인합니다. 이 워크플로는 `v0.3.4` 같은 태그를 푸시하면 Windows 빌드 후 같은 이름의 GitHub Release에 `NoraStudio-Setup-0.3.4.exe`를 게시합니다. Actions의 `contents: write` 권한이 필요합니다.
3. 먼저 이 버전의 설치 파일을 GitHub Actions에서 빌드하거나 Windows PC에서 `windows/Build-Installer.bat`으로 빌드하여 **최초 1회 수동 설치**합니다.
4. `%LOCALAPPDATA%\NoraStudio\config.json`에 아래처럼 저장소를 추가하고 앱을 다시 실행합니다. 다른 설정과 관리자 토큰은 유지하세요.

```json
"releaseRepo": "KimNora07/NoraClient"
```

5. 이후 새 릴리스(예: `v0.3.4`)를 게시하면 앱의 **회사 설정 → 앱 업데이트 → 다운로드 후 업데이트**를 눌러 설치할 수 있습니다. 관리자 토큰으로 로그인해야 하며, Codex 업무가 진행 중일 때는 설치를 거부합니다.

> 검증과 한계: GitHub Releases API의 설치 자산 `digest` SHA-256으로 파일 무결성을 확인합니다. 저장소 소유자의 신뢰성이나 코드 서명을 독립적으로 인증하지는 않습니다. 공개 저장소가 공격당하면 부정한 릴리스가 배포될 위험이 있으므로 GitHub 2단계 인증과 저장소 권한 관리를 권장합니다. 앱 종료 후 PowerShell 헬퍼가 Inno Setup 설치 파일을 실행하고 성공 시 앱을 다시 시작합니다. Windows에서 실제 설치·재시작 과정은 별도로 검증해야 합니다.

## 1. 사전 설치 (Windows PowerShell)

Git, Python 3.12+, Node.js LTS, Ollama, Codex CLI를 설치합니다.

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Python.Python.3.12 -e
winget install --id Ollama.Ollama -e
npm install -g @openai/codex
ollama pull qwen3:8b
```

`codex`를 먼저 단독 실행해 로그인하고, 기존 Unity 프로젝트가 Git 저장소인지 확인하세요.

기존 v0.1 사용자는 서버를 끄고 `data/studio.sqlite3` 파일을 별도로 백업한 뒤 v0.2 코드로 교체하세요. 기존 `data` 폴더를 그대로 유지해야 기존 업무가 보존됩니다.

## 2. 실행 환경 만들기

압축을 원하는 경로(예: `C:\NoraStudio`)에 풀고 **압축을 푼 폴더**에서:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

긴 토큰을 생성합니다.

```powershell
$env:NORA_TOKEN = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$env:NORA_REPO = 'C:\Projects\Arcadia'  # 자신의 Unity Git 저장소 경로로 변경
$env:NORA_MODEL = 'qwen3:8b'
$env:NORA_CODEX_ENABLED = '0'
$env:NORA_AUTO_RUN = '0'
.\.venv\Scripts\python.exe -m uvicorn studio.app:app --host 127.0.0.1 --port 8765
```

토큰은 터미널에 표시되지 않으니, 서버 실행 전 같은 PowerShell 창에서 `Write-Output $env:NORA_TOKEN`으로 복사해 두세요. 브라우저에서 `http://127.0.0.1:8765`를 열어 입력합니다. **토큰은 타인에게 공유하지 마세요.** 토큰을 준비하지 않았어도 첫 화면에서 **게스트로 입장**을 누르면 조회할 수 있습니다. 단, 관리자 기능을 사용하려면 서버에 `NORA_TOKEN`을 설정해야 합니다.

## 3. 안전하게 첫 사용

1. Ollama가 실행 중인지 확인합니다 (`ollama list`).
2. 대시보드에서 토큰으로 접속합니다.
3. 프로젝트 화면에서 Unity 프로젝트를 등록하고 Git 저장소 경로를 입력합니다.
4. CEO 대시보드에서 AI 운영실장에게 작은 Unity C# 작업을 입력합니다.
5. 반환된 제목/요구사항/완료 조건을 직접 수정하고 프로젝트·담당 AI를 지정합니다.
6. 업무 초안 저장 후 **전자결재함에서 승인**합니다.
6. 이 상태에서는 Codex 실행이 꺼져 있으므로 작업은 실행되지 않습니다.

## 4. Codex 실행 활성화

**작업 전 Git 상태를 점검하고, 중요 파일을 백업하세요.** 기존 작업 브랜치를 변경하지 않고 새 worktree를 생성하지만, Codex는 실제 파일 수정과 명령 실행이 가능한 도구입니다.

서버를 중단(`Ctrl+C`)한 후 **동일 PowerShell에서**:

```powershell
$env:NORA_CODEX_ENABLED = '1'
$env:NORA_AUTO_RUN = '0'
.\.venv\Scripts\python.exe -m uvicorn studio.app:app --host 127.0.0.1 --port 8765
```

대시보드에서 **승인 작업 1개 실행**을 누르면 대기 중인 승인 작업 하나를 실행합니다. 실행 후 `review` 상태가 되면 생성된 Git worktree와 브랜치의 변경사항을 사람이 검토합니다. **자동 병합/푸시/배포는 하지 않습니다.**

자동 실행까지 원하는 경우 충분히 검증한 뒤 `NORA_AUTO_RUN=1`로 변경하세요. 이 경우 승인 버튼을 누른 이후 5초 이내에 작업이 시작될 수 있습니다. 승인은 실행 권한을 주는 실제 동작입니다.

## 5. 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

테스트는 승인 상태 전이와 기본 실행 차단을 확인합니다. 실제 Codex/Unity 통합 테스트는 **별도로** 수행해야 합니다.

## 제약 / 다음 버전

- 이번 v0.2는 Unity 자동 컴파일과 Play Mode 테스트를 **아직 실행하지 않습니다**. Codex가 수행한 테스트 결과만 로그에서 확인합니다.
- AI 직원 등록/수정은 역할과 지침을 저장하는 기능입니다. 개별 직원별 자동 실행/대화 기능은 아직 지원하지 않습니다. 업무 실행은 Codex 하나로 한정합니다.
- 결재 내역은 데이터베이스에 저장되지만, 위변조가 기술적으로 불가능한 불변 감사 로그는 아직 아닙니다.
- `review → done`은 노라님의 검수 완료 표시이며 Git 자동 병합을 수행하지 않습니다.
- Codex `workspace-write` 샌드박스는 승인된 작업 내용까지 기술적으로 증명해 주지는 못합니다. 별도 worktree, 명확한 범위, 인간 검토가 필요합니다.
- Ollama로 생성한 초안은 오류나 환각이 있을 수 있습니다. 생성 즉시 실행되는 구조가 아닙니다.
- 서버가 실행 중인 Codex 작업 도중 종료되면 다음 시작 때 `interrupted`로 표시합니다. 작업을 무작정 자동 재실행하지 않습니다.
- `NORA_TOKEN`은 서버 시작 전 설정되어야 하며 서버는 반드시 `127.0.0.1`에 바인딩하세요.
- 게스트는 프로젝트·작업·직원·결재 현황을 조회할 수 있지만 업무를 생성하거나 승인/실행할 수 없습니다. 작업 로그와 저장소 경로, 직원 지침은 게스트 응답에서 숨깁니다. 게스트 화면은 로컬 사용자에게 업무 제목 등 일부 내용을 보여주므로 **공용 PC나 외부 포트 공개 환경에서 사용하지 마세요**.
- 향후 추가: Unity 테스트 실행, 실시간 실행 취소, 브랜치 diff 미리보기, 인증 개선, 자동 시작, 작업 수정 및 재시도 워크플로, Notion 동기화.

## 참고

- [Ollama](https://docs.ollama.com/)
- [Codex](https://developers.openai.com/codex/)
- [Unity Test Framework](https://docs.unity.com/)
