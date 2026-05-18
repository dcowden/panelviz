@echo off
setlocal

set PYTHONDONTWRITEBYTECODE=1
if exist tests\outputs rmdir /s /q tests\outputs
mkdir tests\outputs

".venv\Scripts\python.exe" -B -m pytest --cov %*
if errorlevel 1 exit /b %ERRORLEVEL%

if exist tests\outputs rmdir /s /q tests\outputs
mkdir tests\outputs
".venv\Scripts\python.exe" -B scripts\generate_outputs.py
exit /b %ERRORLEVEL%
