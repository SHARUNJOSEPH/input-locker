; Inno Setup Script for Input Locker
; Generates a clean Windows Installer (.exe) with desktop and start menu shortcuts.
; At install time (already elevated), registers an on-demand highest-privilege
; scheduled task for the Precision Touchpad helper so normal app launches never
; show a UAC prompt for PowerShell.

#define MyAppName "Input Locker"
#define MyAppVersion "0.2.11"
#define MyAppPublisher "Joseph Sharun"
#define MyAppURL "https://github.com/SHARUNJOSEPH/input-locker"
#define MyAppExeName "InputLocker.exe"

[Setup]
AppId={{D37E860F-99F1-4DC3-81D2-7E1A186D5892}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=InputLocker-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\app_icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Setup itself is elevated; that single consent covers task registration.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; Elevated touchpad helper + task install/uninstall scripts
Source: "helpers\touchpad_helper.ps1"; DestDir: "{app}\helpers"; Flags: ignoreversion
Source: "helpers\install_touchpad_task.ps1"; DestDir: "{app}\helpers"; Flags: ignoreversion
Source: "helpers\uninstall_touchpad_task.ps1"; DestDir: "{app}\helpers"; Flags: ignoreversion
Source: "helpers\set_lock_workstation_policy.ps1"; DestDir: "{app}\helpers"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Register the on-demand elevated scheduled task (no UAC on later launches).
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\helpers\install_touchpad_task.ps1"" -HelperPath ""{app}\helpers\touchpad_helper.ps1"""; \
  Flags: runhidden waituntilterminated; \
  StatusMsg: "Registering touchpad helper (one-time)..."
; Win+L policy (HKLM). Takes effect on the next interactive logon after install.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\helpers\set_lock_workstation_policy.ps1"" -Value 1"; \
  Flags: runhidden waituntilterminated; \
  StatusMsg: "Configuring Win+L policy (takes effect after next sign-in)..."
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\helpers\uninstall_touchpad_task.ps1"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "RemoveTouchpadTask"
; Clear Win+L policy so uninstall leaves the machine as it was.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\helpers\set_lock_workstation_policy.ps1"" -Value 0"; \
  Flags: runhidden waituntilterminated; RunOnceId: "ClearLockWorkstationPolicy"
