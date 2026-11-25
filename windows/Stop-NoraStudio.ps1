$ErrorActionPreference = 'Stop'
$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pidPath = Join-Path $studioRoot 'data\server.pid'
Add-Type -AssemblyName PresentationFramework

if (-not (Test-Path $pidPath)) {
    [System.Windows.MessageBox]::Show('실행 중인 Nora Studio 서버 기록이 없습니다.', 'Nora Studio') | Out-Null
    exit 0
}

try {
    $serverPid = [int](Get-Content $pidPath -Raw).Trim()
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
    # Do not terminate a recycled PID or an unrelated Python process.
    if ($null -ne $process -and $process.CommandLine -match 'uvicorn' -and
        $process.CommandLine -match 'studio\.app:app') {
        Stop-Process -Id $serverPid -ErrorAction Stop
        Remove-Item $pidPath -Force
        [System.Windows.MessageBox]::Show('Nora Studio 서버를 종료했습니다.', 'Nora Studio') | Out-Null
    } else {
        [System.Windows.MessageBox]::Show('서버 프로세스를 확인할 수 없어 종료하지 않았습니다.', 'Nora Studio') | Out-Null
    }
} catch {
    [System.Windows.MessageBox]::Show("종료 실패: $($_.Exception.Message)", 'Nora Studio') | Out-Null
}
