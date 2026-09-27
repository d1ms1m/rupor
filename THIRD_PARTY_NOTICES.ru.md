# Сторонние компоненты Рупора

[English](THIRD_PARTY_NOTICES.md) · **Русский**

Сам Рупор распространяется по лицензии MIT (см. [LICENSE](LICENSE)). В этом файле перечислено
стороннее ПО, которое входит в установщик (`Rupor_<версия>_x64-setup.exe` на странице Releases;
при локальной сборке файл называется `Рупор_<версия>_x64-setup.exe`) или которое программа
скачивает при первом запуске, и лицензии этого ПО. Сторонние компоненты не модифицируются: в
сборку попадают файлы из опубликованных пакетов (колёс PyPI, пакетов npm, крейтов crates.io);
PyInstaller лишь компилирует модули Python в байт-код, а Vite и Cargo — код интерфейса и
оболочки.

Полных текстов лицензий здесь нет: они лежат в самих пакетах (каталоги `*.dist-info/licenses`,
файлы `LICENSE` в `node_modules` и в исходниках крейтов) и доступны по ссылкам. Версии указаны
для сборки **0.3.0**. Как пересобрать перечень после обновления зависимостей, описано
[в конце файла](#как-обновить-перечень).

## Коротко

| Что | Где | Распространяется с Рупором |
|---|---|---|
| Среда Python, пакеты Python, их нативные библиотеки | ядро `rupor-core` (PyInstaller), папка `core\` в установленной программе | да |
| Пакеты npm, шрифт Inter, CSS Tailwind | интерфейс (собранные JS/CSS/woff2 внутри `rupor.exe`) | да |
| Крейты Rust, загрузчик WebView2 | оболочка `rupor.exe` (Tauri 2) | да |
| NSIS и модули установщика | сам установщик | да |
| Модель распознавания Whisper large-v3-turbo | кэш Hugging Face, скачивается при первом запуске | нет, скачивается с Hugging Face |
| NVIDIA cuBLAS | `%LOCALAPPDATA%\Rupor\cuda`, скачивается при первом запуске | нет, скачивается с PyPI |
| Microsoft Edge WebView2 Runtime | входит в Windows 10/11 | нет |

Компоненты под «копилефт»-лицензиями (LGPL и MPL) собраны в отдельный раздел:
[LGPL и MPL](#lgpl-и-mpl). Компонентов под GPL в установщике нет (кроме загрузчика PyInstaller
и среды выполнения GCC в OpenBLAS — у обоих есть исключения, разрешающие распространять программу
на любых условиях).

Установщик кладёт рядом с программой `LICENSE.txt` (лицензия Рупора) и английскую версию этого
файла (`THIRD_PARTY_NOTICES.md`).

## 1. Ядро (`rupor-core`)

Ядро — программа на Python, собранная PyInstaller в папку `rupor-core` (исполняемый файл и
каталог `_internal`).

### 1.1. Среда выполнения

| Компонент | Версия | Лицензия | Ссылка |
|---|---|---|---|
| CPython (интерпретатор и стандартная библиотека) | 3.13.3 | PSF-2.0 | https://docs.python.org/3.13/license.html |
| — OpenSSL (`libssl-3.dll`, `libcrypto-3.dll`) | 3.0.16 | Apache-2.0 | https://www.openssl.org/source/license.html |
| — libffi (`libffi-8.dll`) | 3.4 | MIT | https://github.com/libffi/libffi |
| — SQLite (`sqlite3.dll`) | 3.49.1 | общественное достояние | https://www.sqlite.org/copyright.html |
| — Expat, zlib, bzip2, liblzma (xz), mpdecimal (внутри модулей Python) | — | MIT, Zlib, bzip2-1.0.6, 0BSD, BSD-2-Clause | https://docs.python.org/3.13/license.html |
| Загрузчик PyInstaller (часть `rupor-core.exe`) | 6.22.3 | GPL-2.0-or-later с исключением для загрузчика | https://pyinstaller.org/en/stable/license.html |
| Microsoft Visual C++ Runtime и Universal CRT (`vcruntime140*.dll`, `msvcp140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`) | — | распространяемые компоненты Microsoft (Visual Studio / Windows SDK) | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

Исключение в лицензии PyInstaller прямо разрешает распространять собранные им программы на
любых условиях; сам PyInstaller в сборку не входит.

### 1.2. Пакеты Python

Пакеты, модули которых попадают в сборку ядра (данные метаданных `importlib.metadata`
окружения сборки).

| Пакет | Версия | Лицензия (SPDX) | Исходники |
|---|---|---|---|
| anyio | 4.15.1 | MIT | https://github.com/agronholm/anyio |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi (только `_cffi_backend`) | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
| click | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| comtypes | 1.4.17 | MIT | https://github.com/enthought/comtypes |
| ctranslate2 | 4.8.2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| faster-whisper | 1.2.1 | MIT | https://github.com/SYSTRAN/faster-whisper |
| filelock | 4.0.3 | MIT | https://github.com/tox-dev/filelock |
| fsspec | 2026.9.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.6.0 | Apache-2.0 | https://github.com/huggingface/xet-core |
| httpcore | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| huggingface_hub | 1.33.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| numpy | 2.5.3 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://github.com/numpy/numpy |
| onnxruntime | 1.30.0 | MIT | https://github.com/microsoft/onnxruntime |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pillow | 12.3.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| Pygments | 2.21.0 | BSD-2-Clause | https://github.com/pygments/pygments |
| pystray | 0.19.5 | **LGPL-3.0-or-later** — см. [LGPL](#lgpl-и-mpl) | https://github.com/moses-palmer/pystray |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| setuptools (`pkg_resources`, `_distutils_hack`) | 84.0.0 | MIT | https://github.com/pypa/setuptools |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| sounddevice | 0.5.6 | MIT | https://github.com/spatialaudio/python-sounddevice |
| tokenizers | 0.23.2 | Apache-2.0 | https://github.com/huggingface/tokenizers |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| websockets | 17.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

`tokenizers` и `hf-xet` написаны на Rust и статически включают крейты под лицензиями MIT,
Apache-2.0 и совместимыми с ними; их перечень — SBOM в каталоге `*.dist-info/sboms` колеса.

**PyAV (`av`) со встроенным FFmpeg в сборку не входит.** faster-whisper нужен он только для
чтения аудиофайлов, а Рупор распознаёт звук с микрофона. Вместо PyAV в собранном ядре —
заглушка (`packaging/rthook_no_av.py`), поэтому в установщике нет библиотек FFmpeg и кодеков,
в том числе x264/x265 под GPL. PyAV ставится только в окружение разработки (как зависимость
faster-whisper) и там распространяется по своим лицензиям (BSD-3-Clause, FFmpeg — LGPL/GPL).

### 1.3. Нативные библиотеки внутри пакетов

Эти библиотеки поставляются внутри колёс PyPI перечисленных выше пакетов и попадают в сборку
вместе с ними. Вариант PortAudio с ASIO (`libportaudio64bit-asio.dll`, код Steinberg ASIO SDK)
из колеса sounddevice в сборку не берётся: без переменной `SD_ENABLE_ASIO` он не загружается.

| Компонент | Файлы в сборке | Лицензия | Примечание |
|---|---|---|---|
| PortAudio | `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` | MIT | звук с микрофона (sounddevice) |
| CTranslate2 | `ctranslate2/ctranslate2.dll` | MIT | статически включает Intel oneAPI Math Kernel Library (Intel Simplified Software License), oneDNN (Apache-2.0), spdlog (MIT) и среду выполнения NVIDIA CUDA (распространяемый компонент по [CUDA EULA](https://docs.nvidia.com/cuda/eula/)) |
| Intel OpenMP Runtime | `ctranslate2/libiomp5md.dll` | Intel Simplified Software License | распространяемая библиотека среды выполнения Intel oneAPI |
| NVIDIA cuDNN (диспетчер) | `ctranslate2/cudnn64_9.dll` (9.10.2) | NVIDIA cuDNN Software License Agreement | распространяемый компонент из колеса ctranslate2; полный cuDNN Рупору не нужен и в сборку не входит |
| ONNX Runtime | `onnxruntime/capi/onnxruntime*.dll` | MIT | сторонние компоненты — [ThirdPartyNotices.txt](https://github.com/microsoft/onnxruntime/blob/main/ThirdPartyNotices.txt) |
| Silero VAD v6 | `faster_whisper/assets/silero_vad_v6.onnx` | MIT | детектор речи; https://github.com/snakers4/silero-vad |
| OpenBLAS (scipy-openblas) | `numpy.libs/libscipy_openblas64_*.dll` | BSD-3-Clause | включает LAPACK (BSD-3-Clause-Open-MPI) и среду выполнения GCC (GPL-3.0-or-later WITH GCC-exception-3.1); подробно — `numpy-*.dist-info/licenses/LICENSE.txt` |
| Библиотеки Pillow | внутри `PIL/_imaging*.pyd`, `PIL/_avif*.pyd`, `PIL/_webp*.pyd` | brotli 1.2.0 (MIT), FreeType 2.14.3 (FTL), HarfBuzz 14.2.1 (MIT), Little CMS 2.19.1 (MIT), libavif 1.4.2 (BSD-2-Clause, с частями dav1d и libyuv под BSD), libjpeg-turbo 3.1.4.1 (IJG, BSD-3-Clause, Zlib), libpng 1.6.58 (libpng-2.0), libwebp 1.6.0 (BSD-3-Clause), OpenJPEG 2.5.4 (BSD-2-Clause), LibTIFF 4.7.1 (libtiff), xz 5.8.3 (0BSD), zlib-ng 2.3.3 (Zlib) | тексты — `LICENSE` колеса Pillow; Pillow используется только для иконки трея |

### 1.4. Собственные данные ядра

Частотные списки `core/rupor/data/common_*.txt` составлены для Рупора и распространяются по его
лицензии (MIT). Стеммер русского языка в `rupor/vocab.py` — собственная реализация алгоритма
Snowball (алгоритм: M. Porter, https://snowballstem.org, BSD-3-Clause).

## 2. Интерфейс (React)

Зависимости из `ui/package.json` (раздел `dependencies`) и их зависимости — всё, что попадает в
собранный интерфейс. Инструменты сборки из `devDependencies` (Vite, TypeScript, плагины) в
программу не входят.

| Пакет | Версия | Лицензия (SPDX) | Исходники |
|---|---|---|---|
| @fontsource-variable/inter | 5.3.0 | OFL-1.1 | https://github.com/fontsource/font-files |
| @tauri-apps/api | 2.11.1 | Apache-2.0 OR MIT | https://github.com/tauri-apps/tauri |
| @tauri-apps/plugin-autostart | 2.5.1 | MIT OR Apache-2.0 | https://github.com/tauri-apps/plugins-workspace |
| framer-motion | 12.43.0 | MIT | https://github.com/motiondivision/motion |
| motion-dom | 12.43.0 | MIT | https://github.com/motiondivision/motion |
| motion-utils | 12.39.0 | MIT | https://github.com/motiondivision/motion |
| lucide-react | 1.48.0 | ISC | https://github.com/lucide-icons/lucide |
| react | 18.3.1 | MIT | https://github.com/facebook/react |
| react-dom | 18.3.1 | MIT | https://github.com/facebook/react |
| scheduler | 0.23.2 | MIT | https://github.com/facebook/react |
| loose-envify | 1.4.0 | MIT | https://github.com/zertosh/loose-envify |
| js-tokens | 4.0.0 | MIT | https://github.com/lydell/js-tokens |
| tslib | 2.8.1 | 0BSD | https://github.com/microsoft/tslib |
| tailwindcss (сгенерированный CSS, включая базовые стили preflight) | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |

### Шрифт Inter

Шрифт **Inter** (The Inter Project Authors, https://github.com/rsms/inter) входит в интерфейс
файлами `woff2` из пакета `@fontsource-variable/inter` и распространяется по лицензии
**SIL Open Font License 1.1** (https://openfontlicense.org). Файлы шрифта берутся из пакета без
изменений и отдельно от программы не распространяются.

## 3. Оболочка (`rupor.exe`, Tauri 2)

### 3.1. Крейты Rust

Крейты, которые компилируются в `rupor.exe` для `x86_64-pc-windows-msvc` (обычные зависимости
без процедурных макросов и сборочных зависимостей: они работают только при компиляции и в
программу не попадают). Всего 164 крейта; все лицензии разрешительные, кроме MPL-2.0 у
`option-ext` (см. [MPL](#lgpl-и-mpl)).

| Лицензия (SPDX) | Крейты |
|---|---|
| MIT OR Apache-2.0 (108) | anyhow 1.0.104, base64 0.23.1, bitflags 2.13.2, cfg-if 1.0.5, cookie 0.18.2, crc32fast 1.5.2, crossbeam-channel 0.5.17, crossbeam-utils 0.8.23, ctor 0.8.0, deranged 0.5.8, dirs 6.0.0, dirs-sys 0.5.0, equivalent 1.0.2, erased-serde 0.4.10, fdeflate 0.3.7, flate2 1.1.10, fnv 1.0.7, form_urlencoded 1.2.2, getrandom 0.3.4, glob 0.3.4, hashbrown 0.17.1, heck 0.5.0, http 1.5.0, idna 1.1.0, idna_adapter 1.2.2, image 0.25.10, indexmap 2.14.2, itoa 1.0.18, json-patch 3.0.1, jsonptr 0.6.3, keyboard-types 0.7.0, libc 0.2.189, lock_api 0.4.14, log 0.4.34, mime 0.3.17, muda 0.19.3, num-conv 0.2.2, num-traits 0.2.19, once_cell 1.21.4, parking_lot 0.12.5, parking_lot_core 0.9.12, percent-encoding 2.3.2, pin-project-lite 0.2.17, png 0.18.1, powerfmt 0.2.0, regex 1.13.1, regex-automata 0.4.18, regex-syntax 0.8.11, scopeguard 1.2.0, semver 1.0.28, serde 1.0.229, serde-untagged 0.1.9, serde_core 1.0.229, serde_json 1.0.151, serde_spanned 1.1.1, serde_with 3.23.0, serialize-to-javascript 0.1.2, siphasher 1.0.4, smallvec 1.16.2, socket2 0.6.5, softbuffer 0.4.8, stable_deref_trait 1.2.1, tauri 2.11.6, tauri-plugin-autostart 2.5.1, tauri-plugin-single-instance 2.4.5, tauri-runtime 2.11.3, tauri-runtime-wry 2.11.4, tauri-utils 2.9.3, thiserror 1.0.69, thiserror 2.0.21, time 0.3.55, time-core 0.1.9, toml 1.1.6+spec-1.1.0, toml_datetime 1.1.1+spec-1.1.0, toml_parser 1.1.3+spec-1.1.0, toml_writer 1.1.2+spec-1.1.0, tray-icon 0.24.2, typeid 1.0.3, unic-char-property 0.9.0, unic-char-range 0.9.0, unic-common 0.9.0, unic-ucd-ident 0.9.0, unic-ucd-version 0.9.0, unicode-segmentation 1.13.3, url 2.5.8, utf8_iter 1.0.4, uuid 1.26.1, winapi 0.3.9, window-vibrancy 0.6.0, windows 0.61.3, windows-collections 0.2.0, windows-core 0.61.2, windows-future 0.2.1, windows-link 0.1.3, windows-link 0.2.1, windows-numerics 0.2.0, windows-result 0.3.4, windows-strings 0.4.2, windows-sys 0.59.0, windows-sys 0.60.2, windows-sys 0.61.2, windows-targets 0.52.6, windows-targets 0.53.5, windows-threading 0.1.0, windows-version 0.1.7, windows_x86_64_msvc 0.52.6, windows_x86_64_msvc 0.53.1, wry 0.55.1 |
| MIT (19) | auto-launch 0.5.0, bytes 1.12.1, cfb 0.7.3, infer 0.19.0, mio 1.2.3, phf 0.13.1, phf_shared 0.13.1, plist 1.10.1, quick-xml 0.42.0, simd-adler32 0.3.10, tokio 1.53.1, tracing 0.1.44, tracing-core 0.1.36, urlpattern 0.3.0, webview2-com 0.38.2, webview2-com-sys 0.38.2, winnow 1.0.4, winreg 0.10.1, zmij 1.0.23 |
| Unicode-3.0 (15) | icu_collections 2.3.0, icu_locale_core 2.3.0, icu_normalizer 2.3.0, icu_normalizer_data 2.3.0, icu_properties 2.3.0, icu_properties_data 2.3.0, icu_provider 2.3.1, litemap 0.8.3, potential_utf 0.1.6, tinystr 0.8.4, writeable 0.6.4, yoke 0.8.3, zerofrom 0.1.8, zerotrie 0.2.5, zerovec 0.11.8 |
| MIT OR Unlicense (7) | aho-corasick 1.1.5, byteorder 1.5.0, byteorder-lite 0.1.0, memchr 2.8.3, same-file 1.0.6, walkdir 2.5.0, winapi-util 0.1.11 |
| MIT OR Apache-2.0 OR Zlib (4) | bytemuck 1.25.2, miniz_oxide 0.8.9, miniz_oxide 0.9.1, raw-window-handle 0.6.2 |
| Apache-2.0 OR BSD-3-Clause (2) | moxcms 0.8.1, pxfm 0.1.30 |
| BSD-3-Clause (2) | alloc-no-stdlib 2.0.4, alloc-stdlib 0.2.4 |
| Apache-2.0 (1) | tao 0.35.3 |
| Apache-2.0 AND MIT (1) | dpi 0.1.2 |
| Apache-2.0 OR CC0-1.0 OR MIT-0 (1) | dunce 1.0.5 |
| BSD-3-Clause AND MIT (1) | brotli 8.0.4 |
| MIT OR Apache-2.0 OR 0BSD (1) | adler2 2.0.1 |
| MIT OR BSD-3-Clause (1) | brotli-decompressor 5.0.3 |
| MPL-2.0 (1) | option-ext 0.2.0 |

Исходники каждого крейта — на https://crates.io/crates/<имя>.

### 3.2. Microsoft WebView2

| Компонент | Лицензия | Примечание |
|---|---|---|
| Загрузчик WebView2 (`WebView2LoaderStatic.lib` из Microsoft WebView2 SDK, через `webview2-com-sys`) | лицензия Microsoft WebView2 SDK | статически скомпонован в `rupor.exe`; https://www.nuget.org/packages/Microsoft.Web.WebView2 |
| Microsoft Edge WebView2 Runtime | условия Microsoft | **не распространяется** с Рупором: входит в Windows 10/11; если его нет, установщик скачивает официальный загрузчик с сайта Microsoft |

## 4. Установщик

| Компонент | Версия | Лицензия | Ссылка |
|---|---|---|---|
| NSIS (заглушка установщика, модули, языковые файлы — английский и русский) | 3.11 | Zlib (zlib/libpng); модуль сжатия bzip2 — bzip2-1.0.6; модуль сжатия LZMA — CPL-1.0 | https://nsis.sourceforge.io/License |
| nsis_tauri_utils (модуль NSIS от Tauri) | — | MIT OR Apache-2.0 | https://github.com/tauri-apps/nsis-tauri-utils |
| Шаблон установщика Tauri (с его английским и русским языковыми файлами) | 2.x | MIT OR Apache-2.0 | https://github.com/tauri-apps/tauri |

## 5. Что скачивается при первом запуске

Эти компоненты **не входят** в установщик. Мастер первого запуска скачивает их с официальных
источников напрямую на компьютер пользователя.

| Компонент | Источник | Лицензия | Куда |
|---|---|---|---|
| Модель распознавания **Whisper large-v3-turbo** (OpenAI) в формате CTranslate2 | Hugging Face, репозиторий `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (сейчас Hugging Face перенаправляет его на `dropbox-dash/faster-whisper-large-v3-turbo`) | MIT (веса OpenAI Whisper — MIT, https://github.com/openai/whisper; конвертация — MIT по карточке модели) | кэш Hugging Face пользователя |
| Другие модели на выбор (`large-v3`, `medium`, `small`, `base`, `tiny`) | Hugging Face, репозитории `Systran/faster-whisper-*` | MIT | кэш Hugging Face пользователя |
| **NVIDIA cuBLAS** (колесо `nvidia-cublas-cu12` 12.9.2.10) | PyPI | лицензия NVIDIA (`LicenseRef-NVIDIA-Proprietary`, [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/)) | из колеса извлекаются только DLL в `%LOCALAPPDATA%\Rupor\cuda`; нужны только для распознавания на видеокарте NVIDIA |

Для ИИ-очистки текста Рупор по желанию пользователя обращается к внешним сервисам (например,
OpenRouter) по ключу пользователя; к таким обращениям применяются условия выбранного сервиса.

## LGPL и MPL

### LGPL: pystray

**pystray** 0.19.5 (иконка в трее ядра) распространяется по лицензии
**GNU LGPL 3.0 или более поздней** ([текст LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html),
[текст GPL-3.0](https://www.gnu.org/licenses/gpl-3.0.html)). Как соблюдаются её условия:

* pystray входит в сборку **без изменений** как отдельный пакет Python: его модули лежат в
  архиве модулей ядра рядом с модулями других пакетов, а код Рупора пользуется только
  публичным API pystray;
* исходники pystray доступны: https://github.com/moses-palmer/pystray (версия 0.19.5) и
  исходный архив на PyPI (https://pypi.org/project/pystray/0.19.5/);
* **замена возможна**: исходный код Рупора и сценарии сборки (`build.cmd`,
  `packaging/rupor-core.spec`) открыты по лицензии MIT, поэтому ядро можно пересобрать с
  изменённой или другой версией pystray.

### MPL-2.0: certifi, tqdm, option-ext

`certifi` (набор корневых сертификатов), `tqdm` (частично) и крейт `option-ext` распространяются
по [Mozilla Public License 2.0](https://www.mozilla.org/MPL/2.0/). Это файловый копилефт:
файлы этих пакетов входят в сборку без изменений, их исходники доступны по ссылкам выше.

## Как обновить перечень

Команды запускаются из корня репозитория после сборки (`build.cmd`).

* **Python.** Модули в сборке — из `build/rupor-core/PYZ-00.toc` и каталога
  `dist/rupor-core/_internal`; пакет, версия и лицензия — через
  `importlib.metadata.packages_distributions()` и `importlib.metadata.metadata(<пакет>)`
  (поля `License-Expression`, `License`, классификаторы `License ::`). Нативные библиотеки —
  содержимое `_internal/*.libs`, `_internal/ctranslate2`, `_internal/onnxruntime/capi`.
* **npm.** Дерево `dependencies` из `ui/package.json` с учётом вложенных зависимостей; лицензия —
  поле `license` в `ui/node_modules/<пакет>/package.json`.
* **Rust.** `cargo tree -e normal,no-proc-macro --target x86_64-pc-windows-msvc --prefix none
  -f "{p}|{l}"` в `ui/src-tauri`.

Английскую и русскую версии этого файла обновляйте вместе.
