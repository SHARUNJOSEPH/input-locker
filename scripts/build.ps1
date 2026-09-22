# PowerShell Build & Packaging Script for Input Locker
param(
    [switch]$SkipTests = $false
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Input Locker Windows Release Builder " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Run Tests
if (-not $SkipTests) {
    Write-Host "`n[1/4] Running unit test suite..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe -m pytest tests/unit/ -v
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed. Aborting build."
    }
}

# 2. Build Standalone Executable
Write-Host "`n[2/4] Compiling standalone executable with PyInstaller..." -ForegroundColor Yellow
& .\.venv\Scripts\pyinstaller.exe input_locker.spec --noconfirm --clean

if (-not (Test-Path "dist\InputLocker.exe")) {
    Write-Error "Build failed: dist\InputLocker.exe not found."
}

$exeSize = (Get-Item "dist\InputLocker.exe").Length / 1MB
Write-Host "InputLocker.exe built successfully ($([math]::Round($exeSize, 2)) MB)" -ForegroundColor Green

# 3. Create Zip Package
Write-Host "`n[3/4] Creating distribution zip archive..." -ForegroundColor Yellow
$zipPath = "dist\InputLocker-v0.2.3-Windows-x64.zip"
Compress-Archive -Path dist\InputLocker.exe, README.md, LICENSE, SECURITY.md -DestinationPath $zipPath -Force
$zipSize = (Get-Item $zipPath).Length / 1MB
Write-Host "Release archive created: $zipPath ($([math]::Round($zipSize, 2)) MB)" -ForegroundColor Green

# 4. Inno Setup Compiler check (optional)
Write-Host "`n[4/4] Checking for Inno Setup compiler..." -ForegroundColor Yellow
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (Test-Path $iscc) {
    Write-Host "Compiling setup installer with Inno Setup..." -ForegroundColor Cyan
    & $iscc "installer\input_locker_setup.iss"
    Write-Host "Installer compiled at dist\InputLocker-Setup-v0.2.3.exe" -ForegroundColor Green
} else {
    Write-Host "Inno Setup not detected at default path (Optional - standalone .exe and .zip ready)." -ForegroundColor DarkGray
}

Write-Host "`nAll build and packaging steps completed successfully!" -ForegroundColor Green
