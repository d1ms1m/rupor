@echo off
rem Rupor: install the fresh build for the current user (no admin) and start it.
rem Optional flag --first-run: go through the first start again (autostart, setup check).
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\install_local.py" %*
if errorlevel 1 pause
