# Changelog

All notable changes to Rupor are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.1] — 2026-10-14

### Added

- **The indicator no longer disappears.** It is put back on top every time another window is
  activated and when recording starts (a full-screen RDP window used to cover it), returns to
  the primary monitor if a display change leaves it off-screen, reloads itself if its WebView2
  page crashes or keeps hanging (the whole shell restarts if the browser process dies; GPU
  process restarts are left to WebView2), and re-renders after an error instead of staying an
  empty transparent window. Errors are written to `ui.log`. New tray item *Bring back the
  indicator* does all of that by hand and remembers the default position.
- **Similar spellings: one dictionary term is enough.** Spellings that sound like a term are
  fixed without listing variants — Latin or Cyrillic, joined or split, with Russian case endings:
  "Zenobowser", «Xena браузер», «в зенно браузере» → ZennoBrowser. On by default; switch:
  Dictionary → *Recognize similar spellings* (`dict_fuzzy`). Real words are never replaced:
  the Windows spell checker (Russian and English) tells a misrecognition («кубернетис»,
  "Xenoposter") from a word that merely sounds like a term («курсор», «редис», "cloud"). Terms
  made of two ordinary words and very short terms still need a variant; words you often
  dictate yourself count as real words; without the Windows spelling dictionaries only exact
  variants work; paths, addresses and file names are left alone. Words it would replace are
  also kept out of the recognition hint and the AI's term list. The build self-check now
  covers the spell checker.
- **See how the dictionary fills up.** Dictionary → *Recently added* lists the words learned
  from your corrections: what was added, when, and whether Rupor added it or you confirmed it,
  with an Undo button on each row (`dict_learn_journal`). In *Add automatically* mode every
  correction that passes the filters is now added right away with an Undo notification, which
  stays for 12 seconds; doubtful ones used to be only suggested, and the question was easy to
  miss. *Ask first* still asks.

### Fixed

- **AI cleanup works with "thinking" models.** Requests to OpenRouter now turn reasoning off,
  so models such as DeepSeek V4.1 Flash no longer spend the answer budget on thinking and
  return nothing. On 20 Russian test dictations DeepSeek V4.1 Flash was more accurate than
  Claude Haiku 4.5 (WER 2.4 % vs 4.0 %), about twice as fast and ~15× cheaper.
- **No more garbage from recognition.** When Whisper is unsure it falls back to guessing and
  could produce CJK characters, random letter sets ("jpuy, jpac") or subtitle phrases
  («ДИНАМИЧНАЯ МУЗЫКА»), which were inserted as is and even became "frequent words" that
  poisoned the next hints. Such output is now recognised again without the hint and without
  guessing; if it is still garbage, nothing is inserted (*No speech detected*).

- Shortcuts for *Paste last* / *Copy last* that include Alt or Win (for example Win+Alt+V) no
  longer open the window menu or the Start menu when the keys are released.

- **The dictionary has the last word.** AI cleanup could put back a misrecognition that is in
  the dictionary as a variant ("Xenoposter" instead of "Zennoposter"). The AI's reply now goes
  through the dictionary again: in both AI modes and in the *Check cleanup* button.
- A misrecognition that reached the history before it was added to the dictionary no longer
  reinforces itself. Words the dictionary would replace are left out of the recognition hint
  and of the AI's term list, and the text before the cursor used as a hint is corrected by the
  dictionary first.

## [0.4.0] — 2026-09-27

### Added

- **English interface.** Every screen, the setup wizard, the indicator, the tray menu and all
  messages from the engine (notifications, errors, settings validation) are available in
  English. In English the app is called **Rupor**.
- **Interface language switch**: Settings → General → Language — *System* (default), *Русский*,
  *English*. *System* follows the Windows display language (Russian for ru/be/uk/kk, English
  otherwise). The language changes on the fly, without a restart; the setup wizard now starts
  with this choice.
- **Dictation language** setting: *Auto* (default), *Русский*, *English*. In *Auto* each phrase
  is recognized in the interface language unless the model is confident it's the other one
  (`en_threshold` is now the threshold for the second language). A fixed language skips
  detection.
- **English AI cleanup.** English dictation is cleaned up by an English prompt with the same
  rules: filler words (*um, uh, like, you know, basically*), self-corrections (*no wait*,
  *scratch that*), punctuation, numbers, terms and lists; questions in the text are never
  answered. Styles have English instructions. Command mode uses the interface language.
  Benchmark on 12 English cases: 1.1% WER against 25% for the raw text, no fillers left
  ([docs/BENCH.md](docs/BENCH.md)).
- Dates, times, numbers, currency and plurals are formatted for the selected language.
- The installer asks for its language (English or Russian); the setup wizard, the uninstaller
  and the Installed apps entry use the name in that language.
- `?lang=en|ru` for the interface demo mode; English demo data.

### Changed

- The dictionary learns more carefully from English text: capitalizing a common English word
  (Monday, January) is not learned, plain names are only suggested; rare English words are kept
  as weak hints. Word frequencies are rebuilt from history once after the update.
- Setting names in error messages match the names in Settings.

### Notes

- To keep the install path and autostart of existing installations, the install folder,
  shortcuts and the name built into `rupor.exe` stay "Рупор".

## [0.3.0] — 2026-09-27

First public release.

- Voice dictation into any window: hold Ctrl+Win and speak, or double-press for hands-free mode;
  recording can also be started with the mouse.
- Local speech recognition on the GPU (faster-whisper `large-v3-turbo`, CUDA) with a CPU
  fallback; no internet needed after the first-run download.
- Text is pasted via the clipboard or typed as keystrokes; keystrokes work in RDP sessions,
  RemoteApp, Citrix and virtual machine consoles even with the clipboard disabled.
- Broadcast to RDP: one phrase goes to several selected remote sessions.
- Optional AI cleanup through your own OpenRouter, Anthropic or Ollama account, with styles
  (Standard, Business, Chat message, Code / prompt); the raw text is inserted if the AI fails.
- Command mode: select text and tell the AI what to do with it.
- Dictionary of terms and spelling variants that learns from your corrections, frequent words
  and window context as recognition hints, snippets.
- App and window title rules for the insert method and AI style.
- History with search and a draft tab, dictation stats, lowering other apps' audio while
  recording.
- Tray icon, start with Windows, light and dark themes, first-run wizard; a per-user NSIS
  installer without administrator rights.

[0.4.1]: https://github.com/listapad2024/rupor/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/listapad2024/rupor/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/listapad2024/rupor/releases/tag/v0.3.0
