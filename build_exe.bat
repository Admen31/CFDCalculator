@echo off
REM Builds dist\CFD Signal Calculator\CFD Signal Calculator.exe (folder build: starts fast, zip the folder to share).
setlocal
cd /d "%~dp0"
if not exist .venv python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -e ".[dev,build]" || exit /b 1
python -m pytest -q || (echo Testy selhaly - EXE se nevytvori. & exit /b 1)
pyinstaller --noconfirm --clean --windowed --name "CFD Signal Calculator" ^
  --collect-all rapidocr_onnxruntime --paths src src\cfdcalc\__main__.py || exit /b 1
echo.
echo Hotovo: dist\CFD Signal Calculator\CFD Signal Calculator.exe
