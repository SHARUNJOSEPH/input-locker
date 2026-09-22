@echo off
cd /d "%~dp0"
set PYTHONPATH=src
start "" ".venv\Scripts\pythonw.exe" src\input_locker\main.py %*
