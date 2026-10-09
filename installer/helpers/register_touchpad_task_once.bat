@echo off
REM One-time elevation: registers the Input Locker touchpad helper scheduled task.
REM After this succeeds, launching Input Locker will no longer show a UAC prompt.
REM Right-click -> Run as administrator, or let the UAC prompt from this script through.

setlocal
set "HELPERS=%~dp0"
set "HELPER=%HELPERS%touchpad_helper.ps1"

if not exist "%HELPER%" (
  echo Cannot find touchpad_helper.ps1 next to this script.
  echo Expected: %HELPER%
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HELPERS%install_touchpad_task.ps1" -HelperPath "%HELPER%"
if errorlevel 1 (
  echo.
  echo Registration failed. Make sure you ran this as Administrator.
  pause
  exit /b 1
)

echo.
echo Done. Input Locker can now start the touchpad helper without a UAC prompt.
echo You can close this window and start Input Locker normally.
pause
exit /b 0
