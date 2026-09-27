# Rupor third-party notices

**English** · [Русский](THIRD_PARTY_NOTICES.ru.md)

Rupor itself is released under the MIT license (see [LICENSE](LICENSE)). This file lists the
third-party software that ships in the installer (`Rupor_<version>_x64-setup.exe` on the Releases
page; a local build names it `Рупор_<version>_x64-setup.exe`) or that the app downloads on first
launch, together with the licenses of that software. Third-party components are not modified:
the build takes files from published packages (PyPI wheels, npm packages, crates.io crates);
PyInstaller only compiles Python modules to bytecode, and Vite and Cargo compile the UI and shell
code.

Full license texts are not reproduced here: they ship inside the packages themselves
(`*.dist-info/licenses` folders, `LICENSE` files in `node_modules` and in the crate sources) and
are available at the links below. Versions are given for build **0.3.0**. How to regenerate this
list after updating dependencies is described [at the end of the file](#how-to-update-this-list).

## Summary

| What | Where | Shipped with Rupor |
|---|---|---|
| Python runtime, Python packages, their native libraries | the `rupor-core` engine (PyInstaller), the `core\` folder of the installed app | yes |
| npm packages, the Inter typeface, Tailwind CSS | the UI (bundled JS/CSS/woff2 inside `rupor.exe`) | yes |
| Rust crates, the WebView2 loader | the `rupor.exe` shell (Tauri 2) | yes |
| NSIS and installer plugins | the installer itself | yes |
| Whisper large-v3-turbo speech model | Hugging Face cache, downloaded on first launch | no, downloaded from Hugging Face |
| NVIDIA cuBLAS | `%LOCALAPPDATA%\Rupor\cuda`, downloaded on first launch | no, downloaded from PyPI |
| Microsoft Edge WebView2 Runtime | part of Windows 10/11 | no |

Components under copyleft licenses (LGPL and MPL) are covered in a separate section:
[LGPL and MPL](#lgpl-and-mpl). There are no GPL components in the installer (except the
PyInstaller bootloader and the GCC runtime inside OpenBLAS — both carry exceptions that allow the
program to be distributed under any terms).

The installer places `LICENSE.txt` (Rupor's license) and this file next to the app.

## 1. Engine (`rupor-core`)

The engine is a Python program built by PyInstaller into the `rupor-core` folder (an executable
and an `_internal` folder).

### 1.1. Runtime

| Component | Version | License | Link |
|---|---|---|---|
| CPython (interpreter and standard library) | 3.13.3 | PSF-2.0 | https://docs.python.org/3.13/license.html |
| — OpenSSL (`libssl-3.dll`, `libcrypto-3.dll`) | 3.0.16 | Apache-2.0 | https://www.openssl.org/source/license.html |
| — libffi (`libffi-8.dll`) | 3.4 | MIT | https://github.com/libffi/libffi |
| — SQLite (`sqlite3.dll`) | 3.49.1 | public domain | https://www.sqlite.org/copyright.html |
| — Expat, zlib, bzip2, liblzma (xz), mpdecimal (inside Python modules) | — | MIT, Zlib, bzip2-1.0.6, 0BSD, BSD-2-Clause | https://docs.python.org/3.13/license.html |
| PyInstaller bootloader (part of `rupor-core.exe`) | 6.22.3 | GPL-2.0-or-later with the bootloader exception | https://pyinstaller.org/en/stable/license.html |
| Microsoft Visual C++ Runtime and Universal CRT (`vcruntime140*.dll`, `msvcp140*.dll`, `ucrtbase.dll`, `api-ms-win-*.dll`) | — | Microsoft redistributable components (Visual Studio / Windows SDK) | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |

The exception in the PyInstaller license explicitly allows programs built with it to be
distributed under any terms; PyInstaller itself is not part of the build.

### 1.2. Python packages

Packages whose modules end up in the engine build (from the `importlib.metadata` data of the
build environment).

| Package | Version | License (SPDX) | Source |
|---|---|---|---|
| anyio | 4.15.1 | MIT | https://github.com/agronholm/anyio |
| certifi | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi (only `_cffi_backend`) | 2.1.1 | MIT-0 | https://github.com/python-cffi/cffi |
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
| pystray | 0.19.5 | **LGPL-3.0-or-later** — see [LGPL](#lgpl-and-mpl) | https://github.com/moses-palmer/pystray |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| setuptools (`pkg_resources`, `_distutils_hack`) | 84.0.0 | MIT | https://github.com/pypa/setuptools |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| sounddevice | 0.5.6 | MIT | https://github.com/spatialaudio/python-sounddevice |
| tokenizers | 0.23.2 | Apache-2.0 | https://github.com/huggingface/tokenizers |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| websockets | 17.1 | BSD-3-Clause | https://github.com/python-websockets/websockets |

`tokenizers` and `hf-xet` are written in Rust and statically include crates under MIT,
Apache-2.0 and compatible licenses; the list is the SBOM in the wheel's `*.dist-info/sboms`
folder.

**PyAV (`av`) with its bundled FFmpeg is not part of the build.** faster-whisper needs it only to
read audio files, while Rupor recognizes sound from the microphone. The built engine contains a
stub instead of PyAV (`packaging/rthook_no_av.py`), so the installer has no FFmpeg libraries or
codecs, including the GPL-licensed x264/x265. PyAV is installed only in the development
environment (as a faster-whisper dependency) and is distributed there under its own licenses
(BSD-3-Clause; FFmpeg — LGPL/GPL).

### 1.3. Native libraries inside packages

These libraries ship inside the PyPI wheels of the packages listed above and end up in the build
together with them. The PortAudio variant with ASIO (`libportaudio64bit-asio.dll`, Steinberg ASIO
SDK code) from the sounddevice wheel is not taken into the build: it is not loaded without the
`SD_ENABLE_ASIO` variable.

| Component | Files in the build | License | Note |
|---|---|---|---|
| PortAudio | `_sounddevice_data/portaudio-binaries/libportaudio64bit.dll` | MIT | microphone input (sounddevice) |
| CTranslate2 | `ctranslate2/ctranslate2.dll` | MIT | statically includes the Intel oneAPI Math Kernel Library (Intel Simplified Software License), oneDNN (Apache-2.0), spdlog (MIT) and the NVIDIA CUDA runtime (a redistributable component under the [CUDA EULA](https://docs.nvidia.com/cuda/eula/)) |
| Intel OpenMP Runtime | `ctranslate2/libiomp5md.dll` | Intel Simplified Software License | a redistributable Intel oneAPI runtime library |
| NVIDIA cuDNN (dispatcher) | `ctranslate2/cudnn64_9.dll` (9.10.2) | NVIDIA cuDNN Software License Agreement | a redistributable component from the ctranslate2 wheel; Rupor doesn't need the full cuDNN, and it is not part of the build |
| ONNX Runtime | `onnxruntime/capi/onnxruntime*.dll` | MIT | third-party components — [ThirdPartyNotices.txt](https://github.com/microsoft/onnxruntime/blob/main/ThirdPartyNotices.txt) |
| Silero VAD v6 | `faster_whisper/assets/silero_vad_v6.onnx` | MIT | voice activity detector; https://github.com/snakers4/silero-vad |
| OpenBLAS (scipy-openblas) | `numpy.libs/libscipy_openblas64_*.dll` | BSD-3-Clause | includes LAPACK (BSD-3-Clause-Open-MPI) and the GCC runtime (GPL-3.0-or-later WITH GCC-exception-3.1); details in `numpy-*.dist-info/licenses/LICENSE.txt` |
| Pillow libraries | inside `PIL/_imaging*.pyd`, `PIL/_avif*.pyd`, `PIL/_webp*.pyd` | brotli 1.2.0 (MIT), FreeType 2.14.3 (FTL), HarfBuzz 14.2.1 (MIT), Little CMS 2.19.1 (MIT), libavif 1.4.2 (BSD-2-Clause, with parts of dav1d and libyuv under BSD), libjpeg-turbo 3.1.4.1 (IJG, BSD-3-Clause, Zlib), libpng 1.6.58 (libpng-2.0), libwebp 1.6.0 (BSD-3-Clause), OpenJPEG 2.5.4 (BSD-2-Clause), LibTIFF 4.7.1 (libtiff), xz 5.8.3 (0BSD), zlib-ng 2.3.3 (Zlib) | texts in the `LICENSE` of the Pillow wheel; Pillow is used only for the tray icon |

### 1.4. The engine's own data

The frequency lists `core/rupor/data/common_*.txt` were compiled for Rupor and are distributed
under its license (MIT). The Russian stemmer in `rupor/vocab.py` is an original implementation of
the Snowball algorithm (algorithm: M. Porter, https://snowballstem.org, BSD-3-Clause).

## 2. UI (React)

The dependencies from `ui/package.json` (the `dependencies` section) and their dependencies —
everything that ends up in the built UI. Build tools from `devDependencies` (Vite, TypeScript,
plugins) are not part of the app.

| Package | Version | License (SPDX) | Source |
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
| tailwindcss (generated CSS, including the preflight base styles) | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |

### The Inter typeface

The **Inter** typeface (The Inter Project Authors, https://github.com/rsms/inter) is included in
the UI as `woff2` files from the `@fontsource-variable/inter` package and is distributed under the
**SIL Open Font License 1.1** (https://openfontlicense.org). The font files are taken from the
package unchanged and are not distributed separately from the app.

## 3. Shell (`rupor.exe`, Tauri 2)

### 3.1. Rust crates

Crates compiled into `rupor.exe` for `x86_64-pc-windows-msvc` (normal dependencies without
procedural macros and build dependencies: those run only at compile time and don't end up in the
program). 164 crates in total; all licenses are permissive except MPL-2.0 for `option-ext` (see
[MPL](#lgpl-and-mpl)).

| License (SPDX) | Crates |
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

The source of every crate is at https://crates.io/crates/<name>.

### 3.2. Microsoft WebView2

| Component | License | Note |
|---|---|---|
| WebView2 loader (`WebView2LoaderStatic.lib` from the Microsoft WebView2 SDK, via `webview2-com-sys`) | Microsoft WebView2 SDK license | statically linked into `rupor.exe`; https://www.nuget.org/packages/Microsoft.Web.WebView2 |
| Microsoft Edge WebView2 Runtime | Microsoft terms | **not distributed** with Rupor: it is part of Windows 10/11; if it's missing, the installer downloads the official bootstrapper from Microsoft |

## 4. Installer

| Component | Version | License | Link |
|---|---|---|---|
| NSIS (installer stub, plugins, language files — English and Russian) | 3.11 | Zlib (zlib/libpng); bzip2 compression module — bzip2-1.0.6; LZMA compression module — CPL-1.0 | https://nsis.sourceforge.io/License |
| nsis_tauri_utils (NSIS plugin by Tauri) | — | MIT OR Apache-2.0 | https://github.com/tauri-apps/nsis-tauri-utils |
| Tauri installer template (with its English and Russian language files) | 2.x | MIT OR Apache-2.0 | https://github.com/tauri-apps/tauri |

## 5. Downloaded on first launch

These components are **not included** in the installer. The first-run wizard downloads them from
their official sources directly to the user's computer.

| Component | Source | License | Destination |
|---|---|---|---|
| **Whisper large-v3-turbo** speech model (OpenAI) in CTranslate2 format | Hugging Face, the `mobiuslabsgmbh/faster-whisper-large-v3-turbo` repository (Hugging Face currently redirects it to `dropbox-dash/faster-whisper-large-v3-turbo`) | MIT (OpenAI Whisper weights — MIT, https://github.com/openai/whisper; the conversion — MIT per the model card) | the user's Hugging Face cache |
| Other selectable models (`large-v3`, `medium`, `small`, `base`, `tiny`) | Hugging Face, the `Systran/faster-whisper-*` repositories | MIT | the user's Hugging Face cache |
| **NVIDIA cuBLAS** (the `nvidia-cublas-cu12` 12.9.2.10 wheel) | PyPI | NVIDIA license (`LicenseRef-NVIDIA-Proprietary`, [CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/)) | only the DLLs are extracted from the wheel into `%LOCALAPPDATA%\Rupor\cuda`; needed only for recognition on an NVIDIA graphics card |

For AI text cleanup, Rupor contacts external services (for example, OpenRouter) with the user's
own key, if the user turns it on; such requests are governed by the terms of the chosen service.

## LGPL and MPL

### LGPL: pystray

**pystray** 0.19.5 (the engine's tray icon) is distributed under the
**GNU LGPL 3.0 or later** ([LGPL-3.0 text](https://www.gnu.org/licenses/lgpl-3.0.html),
[GPL-3.0 text](https://www.gnu.org/licenses/gpl-3.0.html)). How its terms are met:

* pystray is included in the build **unmodified** as a separate Python package: its modules sit in
  the engine's module archive next to the modules of other packages, and Rupor's code uses only
  pystray's public API;
* pystray's source is available: https://github.com/moses-palmer/pystray (version 0.19.5) and the
  source archive on PyPI (https://pypi.org/project/pystray/0.19.5/);
* **replacement is possible**: Rupor's source code and build scripts (`build.cmd`,
  `packaging/rupor-core.spec`) are open under the MIT license, so the engine can be rebuilt with a
  modified or different version of pystray.

### MPL-2.0: certifi, tqdm, option-ext

`certifi` (the root certificate bundle), `tqdm` (partly) and the `option-ext` crate are
distributed under the [Mozilla Public License 2.0](https://www.mozilla.org/MPL/2.0/). It is a
file-level copyleft: the files of these packages are included in the build unmodified, and their
source is available at the links above.

## How to update this list

Run the commands from the repository root after a build (`build.cmd`).

* **Python.** Modules in the build come from `build/rupor-core/PYZ-00.toc` and the
  `dist/rupor-core/_internal` folder; package, version and license — via
  `importlib.metadata.packages_distributions()` and `importlib.metadata.metadata(<package>)`
  (the `License-Expression` and `License` fields, `License ::` classifiers). Native libraries are
  the contents of `_internal/*.libs`, `_internal/ctranslate2`, `_internal/onnxruntime/capi`.
* **npm.** The `dependencies` tree from `ui/package.json`, including nested dependencies; the
  license is the `license` field in `ui/node_modules/<package>/package.json`.
* **Rust.** `cargo tree -e normal,no-proc-macro --target x86_64-pc-windows-msvc --prefix none
  -f "{p}|{l}"` in `ui/src-tauri`.

Update the English and Russian versions of this file together.
