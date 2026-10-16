@echo off
REM Build OMRChecker.exe (GUI) on Windows. Requires Python 3.10+ on PATH.
cd /d "%~dp0"
REM Prefer the py launcher: "python" may be the Microsoft Store alias
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY set "PY=python"
echo Menggunakan: %PY%
%PY% -m venv .venv-build || goto :error
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip || goto :error
python -m pip install -r requirements.gui.txt || goto :error
REM Optional: vendor\TWAINDSM.dll (64-bit TWAIN DSM) is bundled when present
set "TWAINDSM="
if exist vendor\TWAINDSM.dll set "TWAINDSM=--add-binary vendor\TWAINDSM.dll;."
pyinstaller --noconfirm --clean --onefile --windowed --name OMRChecker ^
  --noupx --paths . --collect-submodules src ^
  --hidden-import openpyxl --hidden-import xlrd --hidden-import win32com.client --hidden-import pythoncom ^
  --hidden-import pywintypes --collect-data sv_ttk --icon assets\icon.ico ^
  --add-data assets\icon.ico;assets --add-data assets\icon.png;assets --add-data assets\logo.png;assets --add-data LICENSE;. --add-data LICENSE-OMRChecker-asli-MIT.txt;. %TWAINDSM% ^
  gui.py || goto :error
xcopy /e /i /y samples dist\samples >nul
copy /y PANDUAN.pdf dist\ >nul
echo.
echo Selesai: dist\OMRChecker.exe
goto :eof
:error
echo Build gagal.
exit /b 1
