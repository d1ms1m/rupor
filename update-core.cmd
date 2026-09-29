@echo off
rem Rupor: replace only the core in the installed app with dist\rupor-core (after "build.cmd core")
rem and restart it. Log: %TEMP%\rupor_install.log.
"%~dp0.venv\Scripts\python.exe" "%~dp0tools\update_core.py" %*
if errorlevel 1 pause
