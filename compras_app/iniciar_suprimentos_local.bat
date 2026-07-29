@echo off
setlocal
cd /d "%~dp0"
py -3.14 app.py
if errorlevel 1 pause
