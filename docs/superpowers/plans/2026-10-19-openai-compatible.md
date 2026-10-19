# OpenAI-compatible provider implementation plan

**Goal:** Add one configurable Chat Completions endpoint for dictation and commands.

**Architecture:** Extend the existing settings, Credential Manager and AI dispatch contracts. Keep endpoint-specific options as a validated JSON object; protect model, messages, stream and credentials from overrides. Persist estimated-cost provenance with each usage record, without recalculating historical charges when tariffs change.

**Tech stack:** Python, SQLite, React, TypeScript.

- [x] Add failing Python tests for settings validation, request shape, optional authentication, command dispatch, cache-aware manual pricing, server cost precedence, malformed responses and usage provenance.
- [x] Extend config/credential/API contracts with `openai_compatible`, URL, model, JSON options and nullable USD-per-million input/output/cache-read tariffs.
- [x] Implement a separate Chat Completions adapter using existing HTTP deadlines/error handling and a shared response parser with OpenRouter; distinguish API-reported and estimated costs. Unknown cost remains null. Missing cache tariff falls back to input tariff.
- [x] Add SQLite migration and carry estimated provenance through engine/API/statistics.
- [x] Add RU/EN settings fields, JSON editor with validation feedback, optional key management, command selection and estimated/unknown cost labels. Reuse the same settings component when only commands use this provider. Update mock defaults and documentation.
- [x] Run tests for affected modules, TypeScript build and localization checks; review diff and resolve findings.

Acceptance: custom endpoint works for cleanup and commands without changing existing provider defaults; invalid settings are atomic; credentials never appear in JSON settings; reserved JSON properties are rejected; estimated costs remain labeled after restart/settings changes; no tariff means unknown rather than free.

## Review fixes (2026-10-19)

Scope: fix the three reviewed defects without committing or introducing a frontend test runner.

- [x] Reproduce tariff changes during cleanup/command HTTP in parameterized pytest tests; capture all three prices before sending the request.
- [x] Reproduce JSON draft loss with a rejected mock save; keep a separate local draft, clearing it only after a successful save of that draft.
- [x] Reproduce the Anthropic placeholder in the compatible key form; add a neutral RU/EN placeholder while retaining existing provider examples.
- [x] Verify Python regressions, UI build/i18n, browser failure/retry/inflight-edit scenarios and existing key placeholders; review the final diff.

Verification: 456 affected Python tests passed, including four new regression cases (cleanup/command, tariffs changed/cleared while HTTP is pending). The two Windows Credential Manager system tests were deselected because the preceding review established sandbox access denial. Strict mypy for ai.py, the UI production build and check:i18n passed. Browser checks on the isolated mock backend verified failed-save draft retention, successful retry, edits during a pending save, clearing JSON to `{}`, clean-editor synchronization, the command-only form and all three providers' key placeholders in RU/EN. Independent review found no actionable issues in the fixes. No real provider calls, user credentials or commits.

## Original implementation verification

- 452 tests passed across test_api, test_api_usage_rules_vocab, test_routing, test_i18n, test_openai_compatible, test_ai, test_storage, test_storage_vocab_usage and test_credman (excluding its two system tests).
- Protocol tests used an import-only faster_whisper substitute whose WhisperModel raises if constructed; the existing fake Recognizer/Recorder fixtures exercise the actual Engine and WebSocket server. Speech recognition itself was not tested. The full unrelated Python suite was not run.
- The two existing Credential Manager system tests passed separately outside the sandbox, using only synthetic temporary Rupor/test-* entries.
- A real local HTTP server verified cleanup and command requests without external providers.
- UI production build, TypeScript and check:i18n passed. Strict mypy passed for ai.py, config.py and storage.py; checking engine/API additionally was limited by missing unrelated certifi/httpx dependencies.
- Independent review found two issues (Engine's optional-key gate and secret redaction after truncation). Both were reproduced with failing tests, fixed and re-reviewed without further findings.
- No real DeepSeek calls. Visual browser validation was unavailable: Chrome MCP profile was occupied and the in-app browser could not reach local Vite.
