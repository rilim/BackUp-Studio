@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 "%~dp0main.py" --demo
) else (
    python "%~dp0main.py" --demo
)
if errorlevel 1 pause
