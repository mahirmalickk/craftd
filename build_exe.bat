@echo off
REM Builds Craftd as a one-folder Windows app: dist\Craftd\Craftd.exe, zipped to dist\Craftd-windows.zip.
REM One-time setup: .venv\Scripts\python -m pip install -r requirements-build.txt
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo Craftd's .venv is missing. Follow the Windows setup in README.md first.
  goto :fail
)
"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo PyInstaller is not installed. Run: .venv\Scripts\python -m pip install -r requirements-build.txt
  goto :fail
)

echo Building dist\Craftd\Craftd.exe ...
REM Fonts and assets keep their paths under craftd\ because the code finds them via Path(__file__)
REM (FONTS_DIR / LOGO_FILE in craftd\gui\theme.py, ICON_FILE in craftd\gui\main_window.py).
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN ^
  --onedir --windowed --name Craftd ^
  --icon "%ROOT%craftd\assets\craftd.ico" ^
  --paths "%ROOT%." ^
  --add-data "%ROOT%craftd\fonts\monocraft;craftd\fonts\monocraft" ^
  --add-data "%ROOT%craftd\fonts\craftd-pixel-extras.ttf;craftd\fonts" ^
  --add-data "%ROOT%craftd\assets;craftd\assets" ^
  --distpath "%ROOT%dist" --workpath "%ROOT%build" --specpath "%ROOT%build" ^
  "%ROOT%tools\craftd_exe_entry.py"
if errorlevel 1 (
  echo PyInstaller failed.
  goto :fail
)
if not exist "dist\Craftd\Craftd.exe" (
  echo dist\Craftd\Craftd.exe was not created.
  goto :fail
)

echo Zipping dist\Craftd to dist\Craftd-windows.zip ...
if exist "dist\Craftd-windows.zip" del "dist\Craftd-windows.zip"
tar -a -c -f "dist\Craftd-windows.zip" -C dist Craftd
if errorlevel 1 (
  echo Zipping failed.
  goto :fail
)

echo.
echo Done: dist\Craftd\Craftd.exe and dist\Craftd-windows.zip
endlocal
exit /b 0

:fail
endlocal
if not defined CRAFTD_NO_PAUSE pause
exit /b 1
