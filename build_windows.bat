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
pyinstaller --noconfirm --clean --onefile --windowed --name OMRChecker ^
  --noupx --paths . --collect-submodules src ^
  --hidden-import openpyxl ^
  gui.py || goto :error
xcopy /e /i /y samples dist\samples >nul
echo.
echo Selesai: dist\OMRChecker.exe
goto :eof
:error
echo Build gagal.
exit /b 1
