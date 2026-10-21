@echo off
setlocal
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pyw -3 "%~dp0main.py"
    exit /b 0
)
where pythonw >nul 2>nul
if %errorlevel% equ 0 (
    start "" pythonw "%~dp0main.py"
    exit /b 0
)
echo Python was not found. Install Python 3.10 or newer with Tcl/Tk support.
echo Then open this file again, or run: py -3 main.py
pause
