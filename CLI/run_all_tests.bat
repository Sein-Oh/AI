@echo off
rem CLI tools: run all tests and collect one result file (see CLI\README.md)
chcp 65001 >nul
cd /d "%~dp0"
python run_all_tests.py %*
pause
