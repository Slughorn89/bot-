@echo off
setlocal
cd /d "%~dp0"
echo.
echo  Audyt inwigilacji: faza czytania (bez uprawnien administratora).
echo  Nic nie jest usuwane ani zmieniane. Wyniki zostaja na tym komputerze.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0audyt.ps1"
echo.
echo  Nastepny krok: uruchom uruchom-audyt-admin.bat (pelny audyt).
pause
