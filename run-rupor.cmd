@echo off
rem Запуск Рупора. Для автозапуска положите ярлык на этот файл в shell:startup
rem (или включите «Автозапуск» в настройках самого Рупора - тогда ярлык не нужен).
rem Есть debug-сборка интерфейса (ui\src-tauri\target\debug\rupor.exe) - запускается она:
rem окно, пилюля и трей, ядро из .venv (см. run-dev.cmd). Нет - старый режим этапов 1-2:
rem ядро с треем pystray без окна (параметры передаются ядру, например --cpu).
if exist "%~dp0ui\src-tauri\target\debug\rupor.exe" (
  call "%~dp0run-dev.cmd"
  exit /b
)
cd /d "%~dp0core"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m rupor %*
