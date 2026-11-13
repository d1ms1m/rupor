; Хуки установщика Рупора (bundle > windows > nsis > installerHooks в tauri.conf.json).
; Шаблон Tauri вставляет PREINSTALL в начало секции Install (до копирования файлов),
; POSTINSTALL — в её конец (после записи в реестр и ярлыков), PREUNINSTALL и
; POSTUNINSTALL — в начало и конец секции Uninstall.
;
; 1. Ядро ($INSTDIR\core, PyInstaller onedir) всегда ставится целиком. При установке поверх
;    («Добавить/переустановить» ту же версию) File /a только перезаписывает совпадающие файлы,
;    а файлы прежней сборки, которых нет в новой (av.libs\*-<хэш>.dll, старые *.dist-info),
;    остались бы. Деинсталлятор удаляет только файлы последней сборки — остатки ядра
;    снимаем целиком.
; 2. Галочка «Удалить данные приложения» в шаблоне стирает только $APPDATA\<identifier> и
;    $LOCALAPPDATA\<identifier> (кэш WebView2). Данные Рупора лежат в других местах:
;    %APPDATA%\Rupor (настройки, история диктовок rupor.db, журналы), %LOCALAPPDATA%\Rupor
;    (DLL CUDA, около 2 ГБ) и ключи ИИ в диспетчере учётных данных Windows
;    (все записи Rupor/* — см. core/rupor/credman.py и core/rupor/keys.py). Удаляем и их.
;    При обновлении (/UPDATE) и без галочки данные не трогаем: деинсталлятор старой версии
;    запускается и при обычной установке новой версии поверх («удалить перед установкой»),
;    а скачивать CUDA заново после каждого обновления незачем.
;    Модель faster-whisper лежит в папке моделей (настройка model_dir; по умолчанию — общий
;    кэш HuggingFace %USERPROFILE%\.cache\huggingface) и здесь не удаляется: эту папку могут
;    использовать другие программы.
;
; Языки установщика — bundle > windows > nsis > languages (English, Russian): каждое
; сообщение хуков задано LangString на обоих языках. Шаблон подключает этот файл раньше
; MUI_LANGUAGE, поэтому ${LANG_ENGLISH} и ${LANG_RUSSIAN} здесь ещё не определены — языки
; указаны своими LANGID. Переменные ($INSTDIR, $APPDATA…) в строках подставляются при выводе.

!define RUPOR_LANG_EN 1033 ; LANG_ENGLISH
!define RUPOR_LANG_RU 1049 ; LANG_RUSSIAN

; Название программы в сообщениях (productName в tauri.conf.json остаётся «Рупор»: от него
; зависят папка установки и ключи реестра прежних установок).
LangString RuporAppName ${RUPOR_LANG_EN} "Rupor"
LangString RuporAppName ${RUPOR_LANG_RU} "Рупор"

; Название в окне и на страницах мастера — на языке установщика: «Rupor Setup»,
; «Welcome to Rupor Setup», «Setup will install Rupor…», «Run Rupor», «Rupor Uninstall».
; Шаблон ставит Name "${PRODUCTNAME}" (то есть «Рупор» на всех языках) после этого файла, но
; строка ^Name / ^NameDA, заданная для языка раньше атрибута Name, для этого языка главнее
; (проверено на makensis 3.11: Name после LangString ^Name её не перебивает). Сам
; ${PRODUCTNAME} не меняется — папка установки, имя ярлыка и ключи реестра прежние. Тексты
; шаблона о переустановке («Рупор <версия> is already installed…», «Uninstall Рупор») собраны
; из ${PRODUCTNAME} при компиляции и здесь не переопределяются.
LangString ^Name ${RUPOR_LANG_EN} "Rupor"
LangString ^Name ${RUPOR_LANG_RU} "Рупор"
LangString ^NameDA ${RUPOR_LANG_EN} "Rupor"
LangString ^NameDA ${RUPOR_LANG_RU} "Рупор"
LangString RuporRemovingOldCore ${RUPOR_LANG_EN} "Removing the previous engine build: $INSTDIR\core"
LangString RuporRemovingOldCore ${RUPOR_LANG_RU} "Удаление прежней сборки ядра: $INSTDIR\core"
LangString RuporOldCoreLeft ${RUPOR_LANG_EN} "Some files of the previous engine build couldn't be removed: $INSTDIR\core"
LangString RuporOldCoreLeft ${RUPOR_LANG_RU} "Не все файлы прежнего ядра удалось удалить: $INSTDIR\core"
LangString RuporRemovingData ${RUPOR_LANG_EN} "Removing Rupor data: $APPDATA\Rupor"
LangString RuporRemovingData ${RUPOR_LANG_RU} "Удаление данных Рупора: $APPDATA\Rupor"
LangString RuporRemovingCuda ${RUPOR_LANG_EN} "Removing components Rupor downloaded (CUDA): $LOCALAPPDATA\Rupor"
LangString RuporRemovingCuda ${RUPOR_LANG_RU} "Удаление загруженных компонентов Рупора (CUDA): $LOCALAPPDATA\Rupor"
LangString RuporKeysRemoved ${RUPOR_LANG_EN} "Rupor's AI keys removed from Windows Credential Manager"
LangString RuporKeysRemoved ${RUPOR_LANG_RU} "Ключи ИИ Рупора удалены из диспетчера учётных данных"
LangString RuporKeysFailed ${RUPOR_LANG_EN} "Some Rupor AI keys could not be removed from Windows Credential Manager"
LangString RuporKeysFailed ${RUPOR_LANG_RU} "Не удалось удалить некоторые ключи ИИ Рупора из диспетчера учётных данных"

; Enumerate the app namespace, including keys no longer listed in settings.json.
; Keep TargetName as a pointer so NSIS string length limits cannot truncate it.
; Filter is parameterized for an integration test using synthetic credentials only.
!macro RUPOR_REMOVE_CREDENTIALS Filter
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    Push $0
    Push $1
    Push $2
    Push $3
    Push $4
    Push $5
    Push $6
    Push $7
    Push $8
    StrCpy $7 0
    System::Call 'advapi32::CredEnumerateW(w "${Filter}", i 0, *i .r0, *p .r1) i .r6 ?e'
    Pop $8
    ${If} $6 <> 0
      StrCpy $2 $1
      ${While} $0 > 0
        System::Call '*$1(p .r3)'
        ; CREDENTIALW starts with DWORD Flags, DWORD Type, LPWSTR TargetName.
        System::Call '*$3(i .r6, i .r4, p .r5)'
        System::Call 'advapi32::CredDeleteW(p r5, i r4, i 0) i .r6 ?e'
        Pop $8
        ${If} $6 = 0
          ; Another process may already have removed this credential.
          ${If} $8 <> 1168
            StrCpy $7 1
          ${EndIf}
        ${EndIf}
        IntOp $1 $1 + ${NSIS_PTR_SIZE}
        IntOp $0 $0 - 1
      ${EndWhile}
      System::Call 'advapi32::CredFree(p r2)'
    ${Else}
      ${If} $8 <> 1168
        StrCpy $7 1
      ${EndIf}
    ${EndIf}
    ${If} $7 = 0
      DetailPrint "$(RuporKeysRemoved)"
    ${Else}
      DetailPrint "$(RuporKeysFailed)"
      SetErrorLevel 1
    ${EndIf}
    Pop $8
    Pop $7
    Pop $6
    Pop $5
    Pop $4
    Pop $3
    Pop $2
    Pop $1
    Pop $0
  ${EndIf}
!macroend

; 1, если в $INSTDIR\core перед удалением было наше ядро (rupor-core.exe).
Var RuporCoreInstalled

!macro RUPOR_REMOVE_CORE_DIR
  ClearErrors
  RMDir /r "$INSTDIR\core"
  ${If} ${Errors}
    ; ядро могло ещё не успеть завершиться после закрытия Рупора
    Sleep 1500
    ClearErrors
    RMDir /r "$INSTDIR\core"
    ${If} ${Errors}
      DetailPrint "$(RuporOldCoreLeft)"
    ${EndIf}
  ${EndIf}
!macroend

!macro NSIS_HOOK_PREINSTALL
  ; Шаблон проверяет, что Рупор закрыт, только после этого хука, а ядро удаляется здесь.
  ; Имя в сообщении «… запущен» — на языке установщика.
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "$(RuporAppName)"
  ${If} $INSTDIR != ""
  ${AndIf} ${FileExists} "$INSTDIR\core\rupor-core.exe"
    DetailPrint "$(RuporRemovingOldCore)"
    !insertmacro RUPOR_REMOVE_CORE_DIR
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Запись в «Установленных приложениях» — на языке установщика. Шаблон только что записал
  ; DisplayName = ${PRODUCTNAME} и Publisher = ${MANUFACTURER} (оба «Рупор»); меняем только
  ; эти подписи. Ключ ${UNINSTKEY} и ключ ${MANUKEY}, где лежат папка установки и язык
  ; установщика, остаются прежними — обновления поверх и автозапуск не ломаются. Шаблон
  ; эти значения нашего ключа не читает (сверка DisplayName/Publisher — только для чужих
  ; MSI-ключей в HKLM).
  WriteRegStr SHCTX "${UNINSTKEY}" "DisplayName" "$(RuporAppName)"
  WriteRegStr SHCTX "${UNINSTKEY}" "Publisher" "$(RuporAppName)"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Та же проверка «Рупор запущен», что шаблон делает сразу после этого хука, — но с именем
  ; на языке деинсталлятора: после неё шаблону уже нечего закрывать.
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "$(RuporAppName)"

  ; После удаления файлов по списку rupor-core.exe уже не будет — запоминаем сейчас,
  ; что $INSTDIR\core — наше ядро, а не чужая папка с таким именем.
  StrCpy $RuporCoreInstalled 0
  ${If} $INSTDIR != ""
  ${AndIf} ${FileExists} "$INSTDIR\core\rupor-core.exe"
    StrCpy $RuporCoreInstalled 1
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $RuporCoreInstalled = 1
    RMDir /r /REBOOTOK "$INSTDIR\core"
    RMDir "$INSTDIR"
  ${EndIf}

  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    ${If} $APPDATA != ""
      DetailPrint "$(RuporRemovingData)"
      RMDir /r /REBOOTOK "$APPDATA\Rupor"
    ${EndIf}
    ${If} $LOCALAPPDATA != ""
      DetailPrint "$(RuporRemovingCuda)"
      RMDir /r /REBOOTOK "$LOCALAPPDATA\Rupor"
    ${EndIf}
    !insertmacro RUPOR_REMOVE_CREDENTIALS "Rupor/*"
  ${EndIf}
!macroend
