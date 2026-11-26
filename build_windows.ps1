# Build the PwMan Windows installer on your own PC.
#
# Requirements: Python 3.11+ (python.org) and Inno Setup 6 (jrsoftware.org/isinfo.php).
# Usage (from the repository folder, in PowerShell):
#     powershell -ExecutionPolicy Bypass -File build_windows.ps1
# Result: dist\PwMan-Setup-<version>.exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) { python -m venv .venv }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt -r requirements-dev.txt

$env:QT_QPA_PLATFORM = "offscreen"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
Remove-Item Env:\QT_QPA_PLATFORM

& $py -m PyInstaller --noconfirm --clean packaging\pwman.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$p = Start-Process -FilePath "dist\PwMan\PwMan.exe" -ArgumentList "--self-test", "selftest.txt" -Wait -PassThru
Get-Content selftest.txt
if ($p.ExitCode -ne 0) { throw "Self-test of the built app failed" }
Remove-Item selftest.txt

$version = & $py -c "import sys; sys.path.insert(0, 'src'); import pwman; print(pwman.__version__)"
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($iscc) { $iscc = $iscc.Source } else {
    $iscc = Get-ChildItem "C:\Program Files*\Inno Setup*\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup*\ISCC.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $iscc) { throw "Inno Setup not found. Install it from https://jrsoftware.org/isinfo.php" }
& $iscc "/DMyAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "`nDone: dist\PwMan-Setup-$version.exe" -ForegroundColor Green
