@echo off
cd /d "%~dp0.."
echo Building Input Locker v0.2.11 (tests + exe + zip + Setup, no MSIX)...
powershell -ExecutionPolicy Bypass -File ".\scripts\build.ps1" -Version 0.2.11 -SkipMsix
echo.
echo Exit code: %ERRORLEVEL%
pause
