@echo off
rem Rupor build script. Usage:
rem   build.cmd        - core (PyInstaller) + copy to ui\src-tauri\resources\core + Tauri installer
rem   build.cmd core   - only core + copy, without Tauri
setlocal EnableExtensions
for /f "tokens=2 delims=:" %%c in ('chcp') do set /a "RUPOR_OLDCP=%%c" 2>nul
chcp 65001 >nul
cd /d "%~dp0"

rem ---------- Сборка Рупора: ядро → ресурсы Tauri → установщик NSIS ----------
set "PY=%~dp0.venv\Scripts\python.exe"
set "DIST=%~dp0dist\rupor-core"
set "RES=%~dp0ui\src-tauri\resources\core"
set "NSIS=%~dp0ui\src-tauri\target\release\bundle\nsis"
set "MODE=%~1"
if /i not "%MODE%"=="" if /i not "%MODE%"=="core" (
  echo [ошибка] Неизвестный параметр "%MODE%". Запуск: build.cmd [core]
  goto :fail
)

if not exist "%PY%" (
  echo [ошибка] Не найден Python окружения разработки: %PY%
  echo          Создайте его: py -3.13 -m venv .venv
  echo          и поставьте зависимости: .venv\Scripts\pip install -e ".[dev]"
  goto :fail
)

echo.
echo ===== [1/3] Сборка ядра: PyInstaller, без консоли =====
set "RUPOR_CONSOLE="
set "PYTHONIOENCODING=utf-8"
"%PY%" -m PyInstaller --noconfirm --clean packaging\rupor-core.spec
if errorlevel 1 (
  echo [ошибка] PyInstaller завершился с ошибкой — подробности выше.
  echo          Если dist\rupor-core занята, закройте запущенный rupor-core.exe.
  goto :fail
)
if not exist "%DIST%\rupor-core.exe" (
  echo [ошибка] После сборки нет файла %DIST%\rupor-core.exe
  goto :fail
)
rem DLL CUDA ставятся при первом запуске и в сборку попадать не должны
dir /s /b "%DIST%\cublas*.dll" "%DIST%\cudnn_*.dll" "%DIST%\nvrtc*.dll" >nul 2>nul
if not errorlevel 1 (
  echo [ошибка] В сборку попали DLL CUDA из пакетов nvidia-* — проверьте packaging\rupor-core.spec
  goto :fail
)
echo Ядро собрано: %DIST%

echo.
echo ===== [2/3] Копирование ядра в ui\src-tauri\resources\core =====
if not exist "%~dp0ui\src-tauri\" (
  echo [ошибка] Нет папки ui\src-tauri — без проекта Tauri копировать ядро некуда.
  goto :fail
)
if exist "%RES%" rmdir /s /q "%RES%"
if exist "%RES%" (
  echo [ошибка] Не удалось удалить старую копию %RES%
  echo          Возможно, из неё запущен rupor-core.exe — закройте Рупор и повторите.
  goto :fail
)
robocopy "%DIST%" "%RES%" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [ошибка] robocopy не смог скопировать ядро в %RES%
  goto :fail
)
if not exist "%RES%\rupor-core.exe" (
  echo [ошибка] После копирования нет %RES%\rupor-core.exe
  goto :fail
)
echo Ядро скопировано: %RES%
rem Ядро в ресурсах должно быть той же версии, что и UI (обучение словаря и пр.):
rem --uia-selftest во временных APPDATA/LOCALAPPDATA/TEMP; старое ядро этого флага не знает
"%PY%" "%~dp0packaging\verify_core.py" "%RES%\rupor-core.exe"
if errorlevel 1 (
  echo [ошибка] Ядро в %RES% не прошло проверку — подробности выше.
  goto :fail
)

if /i "%MODE%"=="core" (
  echo.
  echo Готово: ядро собрано и скопировано, шаг Tauri пропущен по параметру core.
  goto :ok
)

echo.
echo ===== [3/3] Сборка интерфейса и установщика: Tauri =====
where npm >nul 2>nul
if errorlevel 1 (
  echo [ошибка] Не найден npm — установите Node.js 20 или новее.
  goto :fail
)
where cargo >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.cargo\bin\cargo.exe" set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
where cargo >nul 2>nul
if errorlevel 1 (
  echo [ошибка] Не найден cargo — установите Rust: https://rustup.rs
  goto :fail
)
pushd "%~dp0ui"
call npm install
if errorlevel 1 (
  popd
  echo [ошибка] npm install завершился с ошибкой — подробности выше.
  goto :fail
)
call npm run tauri build
if errorlevel 1 (
  popd
  echo [ошибка] Сборка Tauri завершилась с ошибкой — подробности выше.
  goto :fail
)
popd
if not exist "%NSIS%\*-setup.exe" (
  echo [ошибка] Установщик не найден в %NSIS%
  goto :fail
)
echo.
echo Готово. Установщик в %NSIS%:
dir /b "%NSIS%\*-setup.exe"
goto :ok

:fail
echo.
echo Сборка остановлена из-за ошибки.
set "RC=1"
goto :end

:ok
set "RC=0"

:end
if defined RUPOR_OLDCP chcp %RUPOR_OLDCP% >nul
endlocal & exit /b %RC%
