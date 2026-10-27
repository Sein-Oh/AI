@echo off
REM ml_kit offline installer for Windows closed networks.
REM Usage: copy this folder with the "wheels" folder next to it, then run install_offline.bat
REM Uses the "python" found on PATH (WinPython). The py launcher is not used.
setlocal
set "HERE=%~dp0"
if not exist "%HERE%wheels" (
  echo [ERROR] wheels folder not found: %HERE%wheels
  echo [INFO] See docs\WINDOWS_OFFLINE.md to prepare wheels on an internet-connected PC.
  exit /b 1
)
python -m pip install --no-index --find-links "%HERE%wheels" -r "%HERE%requirements.txt"
if errorlevel 1 (
  echo [ERROR] Offline install failed. Check that wheels match this Python version and win_amd64.
  exit /b 1
)
python -c "import numpy, pandas, sklearn, joblib, openpyxl, docx; print('[STATUS] ml_kit dependencies OK: pandas', pandas.__version__, '/ scikit-learn', sklearn.__version__)"
endlocal
