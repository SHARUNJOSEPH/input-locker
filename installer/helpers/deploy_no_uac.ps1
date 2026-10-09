# Input Locker — rebuild (optional), deploy helpers + exe, register no-UAC task.
# Run from an elevated PowerShell:
#   cd C:\Users\user\teamwork_projects\input_locker
#   powershell -ExecutionPolicy Bypass -File installer\helpers\deploy_no_uac.ps1
#
# Or right-click PowerShell -> Run as administrator, then run the same command.
#
# What it does:
#   1) Rebuilds InputLocker.exe with PyInstaller (SkipRebuild to skip)
#   2) Locates the Program Files install
#   3) Copies helpers\ + new InputLocker.exe into the install dir
#   4) Registers \InputLocker\InputLockerTouchpadHelper (RunLevel Highest)
# After this, launching Input Locker from Start Menu should show NO PowerShell UAC.

param(
    [switch]$SkipRebuild,
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-IsAdmin)) {
    Write-Host "This script must run as Administrator (UAC once)." -ForegroundColor Yellow
    Write-Host "Re-launching elevated..."
    $args = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($SkipRebuild) { $args += " -SkipRebuild" }
    if ($InstallDir) { $args += " -InstallDir `"$InstallDir`"" }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $args -Wait
    exit $LASTEXITCODE
}

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $repo
Write-Host "Repo: $repo" -ForegroundColor Cyan

# --- 1. Rebuild ---
if (-not $SkipRebuild) {
    Write-Host "`n[1/4] Rebuilding InputLocker.exe (PyInstaller)..." -ForegroundColor Yellow
    $py = Join-Path $repo ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Error "Missing $py — create the venv / install deps first."
    }
    & $py -m PyInstaller input_locker.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path "dist\InputLocker.exe")) {
        Write-Error "PyInstaller build failed."
    }
    $sz = [math]::Round((Get-Item "dist\InputLocker.exe").Length / 1MB, 2)
    Write-Host "Built dist\InputLocker.exe ($sz MB)" -ForegroundColor Green
} else {
    Write-Host "`n[1/4] Skipping rebuild (using existing dist\InputLocker.exe)" -ForegroundColor DarkYellow
    if (-not (Test-Path "dist\InputLocker.exe")) {
        Write-Error "dist\InputLocker.exe not found. Run without -SkipRebuild."
    }
}

# --- 2. Find install dir ---
Write-Host "`n[2/4] Locating Program Files install..." -ForegroundColor Yellow
$candidates = @(
    $InstallDir,
    "${env:ProgramFiles}\Input Locker",
    "${env:ProgramFiles(x86)}\Input Locker"
) | Where-Object { $_ }

$install = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c "InputLocker.exe"))) {
        $install = $c
        break
    }
}
if (-not $install) {
    # Fallback: any folder named Input Locker under Program Files
    foreach ($root in @(${env:ProgramFiles}, ${env:ProgramFiles(x86)})) {
        if (-not $root) { continue }
        $hit = Get-ChildItem -Path $root -Directory -Filter "Input Locker" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($hit) { $install = $hit.FullName; break }
    }
}
if (-not $install) {
    Write-Error @"
Could not find an installed Input Locker under Program Files.
Pass -InstallDir 'C:\Program Files\Input Locker' (or your actual path).
"@
}
Write-Host "Install dir: $install" -ForegroundColor Green

# --- 3. Stop running app, copy files ---
Write-Host "`n[3/4] Deploying exe + helpers..." -ForegroundColor Yellow
Get-Process -Name "InputLocker" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping running InputLocker (PID $($_.Id))..."
    $_ | Stop-Process -Force
    Start-Sleep -Seconds 1
}

$helpersDst = Join-Path $install "helpers"
New-Item -ItemType Directory -Force -Path $helpersDst | Out-Null

Copy-Item "dist\InputLocker.exe" (Join-Path $install "InputLocker.exe") -Force
Copy-Item "installer\helpers\touchpad_helper.ps1" $helpersDst -Force
Copy-Item "installer\helpers\install_touchpad_task.ps1" $helpersDst -Force
Copy-Item "installer\helpers\uninstall_touchpad_task.ps1" $helpersDst -Force
Copy-Item "installer\helpers\register_touchpad_task_once.bat" $helpersDst -Force
Write-Host "Copied InputLocker.exe + helpers into $install" -ForegroundColor Green

# --- 4. Register scheduled task ---
Write-Host "`n[4/4] Registering elevated scheduled task..." -ForegroundColor Yellow
$helper = Join-Path $helpersDst "touchpad_helper.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (
    Join-Path $helpersDst "install_touchpad_task.ps1"
) -HelperPath $helper
if ($LASTEXITCODE -ne 0) {
    Write-Error "Task registration failed."
}

# Verify
$q = schtasks /Query /TN "\InputLocker\InputLockerTouchpadHelper" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Task query failed after registration: $q"
}
Write-Host $q
Write-Host "`nDone. Start Input Locker from the Start Menu — you should get NO PowerShell UAC." -ForegroundColor Green
Write-Host "If a prompt still appears, the exe may be stale; re-run without -SkipRebuild." -ForegroundColor DarkCyan
exit 0
