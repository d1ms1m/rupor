@echo off
rem Рупор из исходников: debug-сборка оболочки Tauri (окно, пилюля, трей) + ядро из .venv.
rem   run-dev.cmd         - запустить; если debug-сборки нет или она устарела - сначала собрать
rem   run-dev.cmd build   - только пересобрать (после правок в ui\src или ui\src-tauri)
rem Интерфейс встраивается в exe (tauri build --debug), dev-сервер Vite не нужен.
rem Ядро всегда берётся из .venv (python -m rupor), даже если build.cmd положил собранное
rem ядро в ресурсы. Подробный лог ядра: set RUPOR_CORE_ARGS=-v перед запуском.
setlocal EnableExtensions
for /f "tokens=2 delims=:" %%c in ('chcp') do set /a "RUPOR_OLDCP=%%c" 2>nul
chcp 65001 >nul

set "ROOT=%~dp0"
set "EXE=%ROOT%ui\src-tauri\target\debug\rupor.exe"
set "MARK=%ROOT%ui\src-tauri\target\debug\rupor-embedded.txt"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "MODE=%~1"
if /i not "%MODE%"=="" if /i not "%MODE%"=="build" (
  echo [ошибка] Неизвестный параметр "%MODE%". Запуск: run-dev.cmd [build]
  goto :fail
)
if not exist "%PY%" (
  echo [ошибка] Не найден Python окружения разработки: %PY%
  goto :fail
)
if /i "%MODE%"=="build" goto :build

rem Сборка годится, только если её сделал этот скрипт: обычный "cargo build" даёт exe,
rem который ждёт dev-сервер на localhost:1420, - такой пересобираем (сверка по размеру exe).
if not exist "%EXE%" goto :build
if not exist "%MARK%" goto :build
set "SIZE="
set "MARKSIZE="
for %%F in ("%EXE%") do set "SIZE=%%~zF"
set /p MARKSIZE=<"%MARK%"
if not "%SIZE%"=="%MARKSIZE%" goto :build
goto :run

:build
echo ===== Сборка debug-версии Рупора (интерфейс + оболочка Tauri) =====
where npm >nul 2>nul
if errorlevel 1 (
  echo [ошибка] Не найден npm - установите Node.js 20 или новее.
  goto :fail
)
where cargo >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
where cargo >nul 2>nul
if errorlevel 1 (
  echo [ошибка] Не найден cargo - установите Rust: https://rustup.rs
  goto :fail
)
pushd "%ROOT%ui"
if not exist "node_modules\" call npm install
call npm run tauri build -- --debug --no-bundle
if errorlevel 1 (
  popd
  echo [ошибка] Сборка завершилась с ошибкой - подробности выше.
  goto :fail
)
popd
if not exist "%EXE%" (
  echo [ошибка] После сборки нет %EXE%
  goto :fail
)
for %%F in ("%EXE%") do >"%MARK%" echo %%~zF
echo Готово: %EXE%
if /i "%MODE%"=="build" goto :ok

:run
rem Кавычки внутри значения нужны: путь к python может содержать пробелы.
set "RUPOR_CORE="%PY%" -m rupor"
start "" "%EXE%"
goto :ok

:fail
echo.
set "RC=1"
pause
goto :end

:ok
set "RC=0"

:end
if defined RUPOR_OLDCP chcp %RUPOR_OLDCP% >nul
endlocal & exit /b %RC%
