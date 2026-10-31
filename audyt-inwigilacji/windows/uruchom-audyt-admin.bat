@echo off
setlocal
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  Prosze o uprawnienia administratora, potwierdz okno Kontroli konta uzytkownika.
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
cd /d "%~dp0"
echo.
echo  Audyt inwigilacji: pelny audyt jako administrator (tylko odczyt).
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0audyt.ps1"
echo.
pause
