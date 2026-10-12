# Input Locker — elevated Precision Touchpad helper
# Runs with admin rights via a scheduled task registered at install time.
# The main (non-elevated) app writes commands to a cmd file; this process
# applies Disable/Enable-PnpDevice and writes an ack file.
#
# Usage:
#   touchpad_helper.ps1 [-StateDir <path>]
# Defaults StateDir to %PROGRAMDATA%\InputLocker (shared IPC with the app).

param(
    [string]$StateDir = ""
)

$ErrorActionPreference = "SilentlyContinue"

if (-not $StateDir) {
    $StateDir = Join-Path $env:ProgramData "InputLocker"
}

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

$cmdPath = Join-Path $StateDir "touchpad_cmd.txt"
$ackPath = Join-Path $StateDir "touchpad_ack.txt"
$pidPath = Join-Path $StateDir "touchpad_helper.pid"

Set-Content -Path $pidPath -Value $PID -Encoding ASCII

function Set-LockWorkstationPolicyBothHives {
    param([int]$Val)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Stop"
    try {
        foreach ($hive in @(
            [Microsoft.Win32.RegistryHive]::CurrentUser,
            [Microsoft.Win32.RegistryHive]::LocalMachine
        )) {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
                $hive,
                [Microsoft.Win32.RegistryView]::Registry64
            )
            $key = $base.CreateSubKey("SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")
            $key.SetValue("DisableLockWorkstation", [int]$Val, [Microsoft.Win32.RegistryValueKind]::DWord)
            $rb = [int]$key.GetValue("DisableLockWorkstation")
            $key.Close()
            $base.Close()
            if ($rb -ne $Val) {
                throw "read-back mismatch on $hive wanted=$Val got=$rb"
            }
        }
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

# Apply Win+L policy in both HKCU and HKLM at helper start so it takes effect immediately.
try {
    Set-LockWorkstationPolicyBothHives -Val 1
} catch {
    # Non-fatal — lock-time lockpolicy command will retry.
}

while ($true) {
    if (Test-Path -LiteralPath $cmdPath) {
        try {
            $raw = Get-Content -LiteralPath $cmdPath -Raw -ErrorAction Stop
            Remove-Item -LiteralPath $cmdPath -Force -ErrorAction SilentlyContinue
        } catch {
            Start-Sleep -Milliseconds 50
            continue
        }

        $line = ($raw -split "`r?`n")[0]
        if (-not $line) { continue }

        $parts = $line.Split("|")
        $action = $parts[0]
        $ids = @()
        if ($parts.Length -gt 1 -and $parts[1]) {
            $ids = $parts[1].Split(";") | Where-Object { $_ }
        }

        if ($action -eq "quit") {
            Set-Content -Path $ackPath -Value "ok|quit" -Encoding ASCII
            Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
            break
        }
        if ($action -eq "disable") {
            foreach ($i in $ids) {
                Disable-PnpDevice -InstanceId $i -Confirm:$false
            }
            Set-Content -Path $ackPath -Value "ok|disable" -Encoding ASCII
            continue
        }
        if ($action -eq "enable") {
            foreach ($i in $ids) {
                Enable-PnpDevice -InstanceId $i -Confirm:$false
            }
            Set-Content -Path $ackPath -Value "ok|enable" -Encoding ASCII
            continue
        }
        # lockpolicy|1  → set HKCU + HKLM DisableLockWorkstation=1 (blocks Win+L immediately)
        # lockpolicy|0  → clear it
        if ($action -eq "lockpolicy") {
            $val = 0
            if ($parts.Length -gt 1 -and $parts[1]) {
                try { $val = [int]$parts[1] } catch { $val = 0 }
            }
            try {
                Set-LockWorkstationPolicyBothHives -Val $val
                Set-Content -Path $ackPath -Value ("ok|lockpolicy|" + $val) -Encoding ASCII
            } catch {
                Set-Content -Path $ackPath -Value ("err|lockpolicy|" + $_.Exception.Message) -Encoding ASCII
            }
            continue
        }
        Set-Content -Path $ackPath -Value ("err|unknown|" + $action) -Encoding ASCII
    }
    Start-Sleep -Milliseconds 50
}
