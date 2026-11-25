$ErrorActionPreference = 'Stop'
$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $studioRoot '.venv\Scripts\python.exe'
$settingsPath = Join-Path $PSScriptRoot 'launcher-settings.json'
$dataDir = Join-Path $studioRoot 'data'
$pidPath = Join-Path $dataDir 'server.pid'

Add-Type -AssemblyName PresentationFramework

function Show-Error([string]$message) {
    [System.Windows.MessageBox]::Show($message, 'Nora Studio', 'OK', 'Error') | Out-Null
}

try {
    if (-not (Test-Path $pythonPath)) {
        throw "Python 가상환경을 찾을 수 없습니다.`n먼저 windows\Install-NoraStudio.ps1을 실행하세요."
    }
    $settings = Get-Content -Raw -Encoding UTF8 $settingsPath | ConvertFrom-Json
    $studioPort = [int]$settings.port
    if ($studioPort -lt 1024 -or $studioPort -gt 65535) { throw '포트는 1024~65535 사이여야 합니다.' }
    $url = "http://127.0.0.1:$studioPort"
    $ready = $false
    try {
        $response = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        if ($response.role -eq 'guest' -or $response.role -eq 'admin') {
            $ready = $true
        } else {
            throw '지정 포트에서 다른 서버가 실행 중입니다.'
        }
    } catch {
        if ($_.Exception.Message -like '*다른 서버*') { throw }
    }

    if (-not $ready) {
        New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
        $env:NORA_TOKEN = [string]$settings.adminToken
        $env:NORA_REPO = [string]$settings.unityRepo
        $env:NORA_CODEX_ENABLED = if ($settings.codexEnabled) { '1' } else { '0' }
        $env:NORA_AUTO_RUN = if ($settings.autoRunApprovedTasks) { '1' } else { '0' }
        $serverArgs = @('-m', 'uvicorn', 'studio.app:app', '--host', '127.0.0.1', '--port', "$studioPort")
        $server = Start-Process -FilePath $pythonPath -ArgumentList $serverArgs -WorkingDirectory $studioRoot -WindowStyle Hidden -PassThru
        Set-Content -Path $pidPath -Value $server.Id -Encoding ASCII
        for ($i = 0; $i -lt 40; $i++) {
            Start-Sleep -Milliseconds 350
            if ($server.HasExited) { throw '서버가 시작 직후 종료되었습니다. Python 의존성 설치 상태를 확인하세요.' }
            try {
                $response = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1
                if ($response.role -eq 'guest' -or $response.role -eq 'admin') { $ready = $true; break }
            } catch { }
        }
    }
    if (-not $ready) { throw "서버가 응답하지 않습니다: $url" }
    Start-Process $url
} catch {
    Show-Error $_.Exception.Message
    exit 1
}
