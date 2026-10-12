# PowerShell Build & Packaging Script for Input Locker
param(
    [switch]$SkipTests = $false,
    [switch]$SkipMsix = $false,
    [string]$Version = "0.2.11"
)

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Input Locker Windows Release Builder " -ForegroundColor Cyan
Write-Host " Target Version: v$Version             " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Run Tests
if (-not $SkipTests) {
    Write-Host "`n[1/5] Running unit test suite..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe -m pytest tests/unit/ -v
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed. Aborting build."
    }
}

# 2. Build Standalone Executable
Write-Host "`n[2/5] Compiling standalone executable with PyInstaller..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -m PyInstaller input_locker.spec --noconfirm --clean

if (-not (Test-Path "dist\InputLocker.exe")) {
    Write-Error "Build failed: dist\InputLocker.exe not found."
}

$exeSize = (Get-Item "dist\InputLocker.exe").Length / 1MB
Write-Host "InputLocker.exe built successfully ($([math]::Round($exeSize, 2)) MB)" -ForegroundColor Green

# 3. Create Zip Package
Write-Host "`n[3/5] Creating distribution zip archive..." -ForegroundColor Yellow
$zipPath = "dist\InputLocker-v$Version-Windows-x64.zip"
Compress-Archive -Path dist\InputLocker.exe, README.md, LICENSE, SECURITY.md -DestinationPath $zipPath -Force
Copy-Item $zipPath "dist\InputLocker-Windows-x64.zip" -Force
$zipSize = (Get-Item $zipPath).Length / 1MB
Write-Host "Release archives created: $zipPath & dist\InputLocker-Windows-x64.zip ($([math]::Round($zipSize, 2)) MB)" -ForegroundColor Green

# 4. Inno Setup Compiler
Write-Host "`n[4/5] Checking for Inno Setup compiler..." -ForegroundColor Yellow
$isccCandidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($iscc) {
    Write-Host "Found Inno Setup at: $iscc" -ForegroundColor DarkCyan
    Write-Host "Compiling setup installer with Inno Setup..." -ForegroundColor Cyan
    & $iscc "/DMyAppVersion=$Version" "installer\input_locker_setup.iss"
    $setupExe = "dist\InputLocker-Setup-v$Version.exe"
    if (Test-Path $setupExe) {
        Write-Host "Installer compiled at $setupExe" -ForegroundColor Green
    } else {
        Write-Warning "Inno Setup ran but $setupExe was not found."
    }
} else {
    Write-Warning "Inno Setup compiler not found in candidate paths."
}

# 5. Build and Validate MSIX Package (optional)
if (-not $SkipMsix) {
    Write-Host "`n[5/5] Building Microsoft Store MSIX package..." -ForegroundColor Yellow
    & .\.venv\Scripts\python.exe scripts\package_msix.py $Version
    if ($LASTEXITCODE -ne 0) {
        Write-Error "MSIX packaging failed."
    }

    $msixPath = "dist\InputLocker-v$Version.msix"
    if (Test-Path $msixPath) {
        $msixSize = (Get-Item $msixPath).Length / 1MB
        Write-Host "MSIX package validated and ready: $msixPath ($([math]::Round($msixSize, 2)) MB)" -ForegroundColor Green
    }
} else {
    Write-Host "`n[5/5] Skipping MSIX package (-SkipMsix)." -ForegroundColor DarkYellow
}

Write-Host "`nAll build and packaging steps completed successfully!" -ForegroundColor Green
