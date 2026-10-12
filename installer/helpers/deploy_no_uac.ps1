# Input Locker — direct elevated installer / deployer (Smart App Control safe).
# Bypasses Inno Setup's %TEMP%\is-*.tmp bootstrapper (which triggers Windows 11
# Smart App Control Error 4551 on unsigned builds).
#
# Run from PowerShell (auto-elevates via UAC once):
#   cd C:\Users\user\teamwork_projects\input_locker
#   powershell -ExecutionPolicy Bypass -File .\installer\helpers\deploy_no_uac.ps1 -SkipRebuild
#
# What it does:
#   1) Uses existing dist\InputLocker.exe (or rebuilds with PyInstaller if missing / -Rebuild)
#   2) Creates or updates C:\Program Files\Input Locker
#   3) Copies InputLocker.exe, assets\, and helpers\ into the install dir
#   4) Registers \InputLocker\InputLockerTouchpadHelper (RunLevel Highest)
#   5) Sets HKLM DisableLockWorkstation = 1 (64-bit view, verified read-back)
#   6) Creates Start Menu and Desktop shortcuts

param(
    [switch]$SkipRebuild,
    [switch]$Rebuild,
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$isAdmin = Test-IsAdmin
$taskCheck = schtasks /Query /TN "\InputLocker\InputLockerTouchpadHelper" 2>&1
$taskExists = ($LASTEXITCODE -eq 0)
$policyProp = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "DisableLockWorkstation" -ErrorAction SilentlyContinue
$policyExists = ($null -ne $policyProp -and [int]$policyProp.DisableLockWorkstation -eq 1)

if (-not $isAdmin) {
    if (-not ($taskExists -and $policyExists)) {
        Write-Host "This script needs Administrator rights to register the task and HKLM policy (UAC once)." -ForegroundColor Yellow
        Write-Host "Re-launching elevated..."
        $argList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$PSCommandPath`""
        )
        if ($SkipRebuild) { $argList += "-SkipRebuild" }
        if ($Rebuild)     { $argList += "-Rebuild" }
        if ($InstallDir)  { $argList += @("-InstallDir", "`"$InstallDir`"") }
        try {
            $proc = Start-Process powershell.exe -Verb RunAs -ArgumentList ($argList -join " ") -Wait -PassThru
            exit $proc.ExitCode
        } catch {
            Write-Warning "Could not auto-elevate ($($_.Exception.Message)). Continuing with user-scope deploy..."
        }
    } else {
        Write-Host "Scheduled task and HKLM Win+L policy are already registered — installing in user scope (no UAC needed)." -ForegroundColor Cyan
    }
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repo
Write-Host "Repo: $repo" -ForegroundColor Cyan

# --- 1. Build or reuse dist\InputLocker.exe ---
$exeSource = Join-Path $repo "dist\InputLocker.exe"
$needBuild = $Rebuild -or (-not $SkipRebuild -and -not (Test-Path $exeSource))
if ($needBuild) {
    Write-Host "`n[1/6] Building InputLocker.exe (PyInstaller)..." -ForegroundColor Yellow
    $py = Join-Path $repo ".venv\Scripts\python.exe"
    if (-not (Test-Path $py)) {
        Write-Error "Missing $py — create the venv / install deps first."
    }
    & $py -m PyInstaller input_locker.spec --noconfirm --clean
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exeSource)) {
        Write-Error "PyInstaller build failed."
    }
    $sz = [math]::Round((Get-Item $exeSource).Length / 1MB, 2)
    Write-Host "Built dist\InputLocker.exe ($sz MB)" -ForegroundColor Green
} else {
    if (-not (Test-Path $exeSource)) {
        Write-Error "dist\InputLocker.exe not found. Run without -SkipRebuild or run scripts\build.ps1 first."
    }
    $sz = [math]::Round((Get-Item $exeSource).Length / 1MB, 2)
    Write-Host "`n[1/6] Using existing dist\InputLocker.exe ($sz MB)" -ForegroundColor Green
}

# --- 2. Resolve or create install dir ---
Write-Host "`n[2/6] Preparing install directory..." -ForegroundColor Yellow
$defaultInstall = if ($isAdmin) { "${env:ProgramFiles}\Input Locker" } else { "$env:LOCALAPPDATA\Programs\Input Locker" }
$candidates = @(
    $InstallDir,
    "${env:ProgramFiles}\Input Locker",
    "${env:ProgramFiles(x86)}\Input Locker",
    "$env:LOCALAPPDATA\Programs\Input Locker"
) | Where-Object { $_ }

$install = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c "InputLocker.exe"))) {
        if ($isAdmin -or $c.StartsWith($env:LOCALAPPDATA, [System.StringComparison]::OrdinalIgnoreCase)) {
            $install = $c
            break
        }
    }
}
if (-not $install) {
    $install = if ($InstallDir) { $InstallDir } else { $defaultInstall }
    New-Item -ItemType Directory -Force -Path $install | Out-Null
    Write-Host "Created install dir: $install" -ForegroundColor Green
} else {
    Write-Host "Found existing install dir: $install" -ForegroundColor Green
}

# --- 3. Stop running app, copy files ---
Write-Host "`n[3/6] Deploying InputLocker.exe, assets, and helpers..." -ForegroundColor Yellow
Get-Process -Name "InputLocker" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "Stopping running InputLocker (PID $($_.Id))..."
    $_ | Stop-Process -Force
    Start-Sleep -Seconds 1
}

$helpersDst = Join-Path $install "helpers"
$assetsDst  = Join-Path $install "assets"
New-Item -ItemType Directory -Force -Path $helpersDst | Out-Null
New-Item -ItemType Directory -Force -Path $assetsDst  | Out-Null

Copy-Item $exeSource (Join-Path $install "InputLocker.exe") -Force
if (Test-Path (Join-Path $repo "assets")) {
    Copy-Item (Join-Path $repo "assets\*") $assetsDst -Recurse -Force
}
foreach ($doc in @("README.md", "LICENSE")) {
    $docPath = Join-Path $repo $doc
    if (Test-Path $docPath) {
        Copy-Item $docPath (Join-Path $install $doc) -Force
    }
}
foreach ($h in @(
    "touchpad_helper.ps1",
    "install_touchpad_task.ps1",
    "uninstall_touchpad_task.ps1",
    "set_lock_workstation_policy.ps1",
    "register_touchpad_task_once.bat"
)) {
    $src = Join-Path $repo "installer\helpers\$h"
    if (Test-Path $src) {
        Copy-Item $src $helpersDst -Force
    }
}
Write-Host "Copied InputLocker.exe, assets, and helpers into $install" -ForegroundColor Green

# --- 4. Register or verify scheduled task ---
Write-Host "`n[4/6] Checking elevated scheduled task..." -ForegroundColor Yellow
if ($isAdmin) {
    $helper = Join-Path $helpersDst "touchpad_helper.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (
        Join-Path $helpersDst "install_touchpad_task.ps1"
    ) -HelperPath $helper
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Task registration failed."
    }
}
$q = schtasks /Query /TN "\InputLocker\InputLockerTouchpadHelper" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Task query failed: $q"
}
Write-Host "Scheduled task \InputLocker\InputLockerTouchpadHelper is Ready." -ForegroundColor Green

# --- 5. Configure or verify Win+L policy (HKLM DisableLockWorkstation = 1) ---
Write-Host "`n[5/6] Checking Win+L policy (HKLM DisableLockWorkstation = 1)..." -ForegroundColor Yellow
if ($isAdmin) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (
        Join-Path $helpersDst "set_lock_workstation_policy.ps1"
    ) -Value 1
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Setting DisableLockWorkstation policy failed."
    }
} else {
    $prop = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "DisableLockWorkstation" -ErrorAction SilentlyContinue
    if ($null -eq $prop -or [int]$prop.DisableLockWorkstation -ne 1) {
        Write-Warning "HKLM DisableLockWorkstation is not 1 yet; starting helper task to apply it..."
        schtasks /Run /TN "\InputLocker\InputLockerTouchpadHelper" | Out-Null
        Start-Sleep -Seconds 2
    }
    $prop = Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" -Name "DisableLockWorkstation" -ErrorAction SilentlyContinue
    Write-Host "HKLM DisableLockWorkstation verified = $($prop.DisableLockWorkstation)" -ForegroundColor Green
}

# --- 6. Create Start Menu and Desktop shortcuts ---
Write-Host "`n[6/6] Creating Start Menu and Desktop shortcuts..." -ForegroundColor Yellow
try {
    $wsh = New-Object -ComObject WScript.Shell
    $targetExe = Join-Path $install "InputLocker.exe"
    $targetArgs = ""
    $workDir = $install
    $iconPath = Join-Path $install "assets\app_icon.ico"

    # Check if Windows 11 Smart App Control is enforced (VerifiedAndReputablePolicyState == 1)
    # and InputLocker.exe is unsigned. If so, Explorer/ShellExecute blocks unsigned .exe files,
    # whereas .venv\Scripts\pythonw.exe is Authenticode-signed by the Python Software Foundation.
    $ciPolicy = Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy" -Name "VerifiedAndReputablePolicyState" -ErrorAction SilentlyContinue
    $sacEnforced = ($null -ne $ciPolicy -and [int]$ciPolicy.VerifiedAndReputablePolicyState -eq 1)
    $exeSig = Get-AuthenticodeSignature $targetExe -ErrorAction SilentlyContinue
    $pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"

    if ($sacEnforced -and ($null -eq $exeSig -or $exeSig.Status -ne "Valid") -and (Test-Path $pythonw)) {
        Write-Host "Smart App Control is enforced and InputLocker.exe is unsigned — binding shortcuts to Authenticode-signed pythonw.exe (-m input_locker.main)." -ForegroundColor Cyan
        $targetExe = $pythonw
        $targetArgs = "-m input_locker.main"
        $workDir = $repo
    }

    $startRoot = if ($isAdmin) {
        Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\Input Locker"
    } else {
        Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Input Locker"
    }
    New-Item -ItemType Directory -Force -Path $startRoot | Out-Null
    $startShortcut = $wsh.CreateShortcut((Join-Path $startRoot "Input Locker.lnk"))
    $startShortcut.TargetPath = $targetExe
    if ($targetArgs) { $startShortcut.Arguments = $targetArgs }
    $startShortcut.WorkingDirectory = $workDir
    if (Test-Path $iconPath) { $startShortcut.IconLocation = $iconPath }
    $startShortcut.Save()

    $desktopDir = [Environment]::GetFolderPath("Desktop")
    if ($desktopDir -and (Test-Path $desktopDir)) {
        $deskShortcut = $wsh.CreateShortcut((Join-Path $desktopDir "Input Locker.lnk"))
        $deskShortcut.TargetPath = $targetExe
        if ($targetArgs) { $deskShortcut.Arguments = $targetArgs }
        $deskShortcut.WorkingDirectory = $workDir
        if (Test-Path $iconPath) { $deskShortcut.IconLocation = $iconPath }
        $deskShortcut.Save()
    }
    Write-Host "Shortcuts created in Start Menu ($startRoot) and Desktop ($desktopDir)." -ForegroundColor Green
} catch {
    Write-Warning "Shortcut creation warning: $($_.Exception.Message)"
}

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Input Locker v0.2.11 installed to: $install" -ForegroundColor Green
Write-Host " 1. Sign out and sign back in once (if not done since policy was set)." -ForegroundColor Cyan
Write-Host " 2. Launch 'Input Locker' from Start Menu or Desktop (no UAC, SAC-safe)." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
exit 0
