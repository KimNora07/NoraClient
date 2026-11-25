$ErrorActionPreference = 'Stop'
$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $studioRoot '.venv\Scripts\python.exe'
$desktop = [Environment]::GetFolderPath('Desktop')

try {
    if (-not (Test-Path $venvPython)) {
        Write-Host 'Python 가상환경 생성 중...' -ForegroundColor Cyan
        py -3 -m venv (Join-Path $studioRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python 3를 찾지 못했습니다.' }
    }
    Write-Host 'Nora Studio 의존성을 설치합니다...' -ForegroundColor Cyan
    & $venvPython -m pip install -r (Join-Path $studioRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치에 실패했습니다.' }

    $shell = New-Object -ComObject WScript.Shell
    foreach ($shortcut in @(
        @{ Name='Nora Studio.lnk'; Script='Launch-NoraStudio.ps1'; Description='Nora Studio 실행' },
        @{ Name='Nora Studio 종료.lnk'; Script='Stop-NoraStudio.ps1'; Description='Nora Studio 서버 종료' }
    )) {
        $link = $shell.CreateShortcut((Join-Path $desktop $shortcut.Name))
        $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
        $scriptPath = Join-Path $PSScriptRoot $shortcut.Script
        $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
        $link.WorkingDirectory = $studioRoot
        $link.IconLocation = "$env:SystemRoot\System32\shell32.dll,3"
        $link.Description = $shortcut.Description
        $link.Save()
    }
    Write-Host '설치 완료! 바탕화면의 Nora Studio 아이콘을 더블클릭하세요.' -ForegroundColor Green
} catch {
    Write-Host "설치 실패: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
