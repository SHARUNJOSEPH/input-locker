# Stops the touchpad helper (if running) and removes the install-time scheduled task.
# Called by the Inno uninstaller.

param(
    [string]$TaskName = "InputLockerTouchpadHelper",
    [string]$TaskFolder = "\InputLocker"
)

$ErrorActionPreference = "SilentlyContinue"

$stateDir = Join-Path $env:ProgramData "InputLocker"
$cmdPath = Join-Path $stateDir "touchpad_cmd.txt"
$ackPath = Join-Path $stateDir "touchpad_ack.txt"
$pidPath = Join-Path $stateDir "touchpad_helper.pid"

# Ask the helper to quit politely if it is still running.
if (Test-Path -LiteralPath $pidPath) {
    try {
        Remove-Item -LiteralPath $ackPath -Force -ErrorAction SilentlyContinue
        Set-Content -Path $cmdPath -Value "quit|" -Encoding ASCII
        $deadline = (Get-Date).AddSeconds(3)
        while ((Get-Date) -lt $deadline) {
            if (-not (Test-Path -LiteralPath $pidPath)) { break }
            Start-Sleep -Milliseconds 100
        }
    } catch {}
    Remove-Item -LiteralPath $pidPath, $cmdPath, $ackPath -Force -ErrorAction SilentlyContinue
}

Unregister-ScheduledTask -TaskName $TaskName -TaskPath "$TaskFolder\" -Confirm:$false -ErrorAction SilentlyContinue

# Remove empty task folder if nothing else remains.
try {
    $svc = New-Object -ComObject Schedule.Service
    $svc.Connect()
    $folder = $svc.GetFolder($TaskFolder)
    if ($folder.GetTasks(0).Count -eq 0) {
        $root = $svc.GetFolder("\")
        $root.DeleteFolder("InputLocker", 0)
    }
} catch {}

Write-Host "Removed scheduled task: $TaskFolder\$TaskName"
exit 0
