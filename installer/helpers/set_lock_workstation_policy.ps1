# Input Locker — set/clear HKCU + HKLM DisableLockWorkstation (Win+L policy).
# Called elevated from Inno Setup at install (Value=1) and uninstall (Value=0).
# Uses the 64-bit registry view so WOW6432Node cannot hide the write.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(0, 1)]
    [int]$Value
)

$ErrorActionPreference = "Stop"
foreach ($hive in @(
    [Microsoft.Win32.RegistryHive]::CurrentUser,
    [Microsoft.Win32.RegistryHive]::LocalMachine
)) {
    $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        $hive,
        [Microsoft.Win32.RegistryView]::Registry64
    )
    $key = $base.CreateSubKey("SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System")
    $key.SetValue("DisableLockWorkstation", $Value, [Microsoft.Win32.RegistryValueKind]::DWord)
    $readBack = [int]$key.GetValue("DisableLockWorkstation")
    $key.Close()
    $base.Close()

    if ($readBack -ne $Value) {
        Write-Error "DisableLockWorkstation read-back mismatch on ${hive}: wanted=$Value got=$readBack"
        exit 1
    }
}
Write-Host "HKCU + HKLM DisableLockWorkstation set to $Value"
exit 0
