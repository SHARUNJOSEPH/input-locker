# Registers an on-demand, highest-privilege scheduled task for the touchpad helper.
# Called once by the elevated Inno installer. After this, the normal (non-elevated)
# Input Locker process can start the helper with `schtasks /Run` — no UAC prompt.
#
# Usage:
#   install_touchpad_task.ps1 -HelperPath "C:\Program Files\Input Locker\helpers\touchpad_helper.ps1" [-UserName "DOMAIN\user"]

param(
    [Parameter(Mandatory = $true)]
    [string]$HelperPath,

    [string]$UserName = "",

    [string]$TaskName = "InputLockerTouchpadHelper",

    [string]$TaskFolder = "\InputLocker"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $HelperPath)) {
    Write-Error "Helper script not found: $HelperPath"
    exit 1
}

# Shared IPC directory — both the elevated helper and the user app use this.
$stateDir = Join-Path $env:ProgramData "InputLocker"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
try {
    # Allow interactive users to write cmd/ack files the helper reads.
    icacls $stateDir /grant "*S-1-5-32-545:(OI)(CI)M" /T | Out-Null
} catch {
    # Non-fatal; folder still usable for the installing user.
}

if (-not $UserName) {
    $UserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

$fullTaskPath = "$TaskFolder\$TaskName"

# Ensure task folder exists
$schedule = New-Object -ComObject Schedule.Service
$schedule.Connect()
try {
    $null = $schedule.GetFolder($TaskFolder)
} catch {
    $root = $schedule.GetFolder("\")
    $null = $root.CreateFolder("InputLocker")
}

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$HelperPath`" -StateDir `"$stateDir`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -Hidden

# Remove any previous registration so reinstall is clean.
Unregister-ScheduledTask -TaskName $TaskName -TaskPath "$TaskFolder\" -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath "$TaskFolder\" `
    -Action $action `
    -Principal $principal `
    -Settings $settings `
    -Description "Input Locker elevated Precision Touchpad helper (started on demand, no UAC after install)." `
    -Force | Out-Null

# Allow Authenticated Users to start the task (so the non-elevated app can schtasks /Run).
try {
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $folder = $svc.GetFolder($TaskFolder)
    $task = $folder.GetTask($TaskName)
    # DACL: allow Authenticated Users (S-1-5-11) Read + Execute (start)
    # Keep Administrators full control.
    $sddl = "D:(A;;FA;;;BA)(A;;FRFX;;;AU)(A;;FA;;;SY)"
    $task.SetSecurityDescriptor($sddl, 0)
} catch {
    Write-Warning "Could not loosen task ACL for Authenticated Users: $_"
}

Write-Host "Registered scheduled task: $fullTaskPath (RunLevel Highest, on demand)"
exit 0
