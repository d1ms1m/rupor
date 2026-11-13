"""Run the real NSIS credential cleanup against an isolated synthetic namespace."""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from rupor import credman

ROOT = Path(__file__).resolve().parent.parent


def test_nsis_removes_all_provider_keys_only_when_requested(tmp_path: Path) -> None:
    compiler = os.environ.get("RUPOR_MAKENSIS") or shutil.which("makensis")
    if not compiler:
        candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "tauri/NSIS/makensis.exe",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "tauri/NSIS/Bin/makensis.exe"]
        compiler = next((str(p) for p in candidates if p.is_file()), None)
    if os.name != "nt" or not compiler:
        pytest.skip("Windows Credential Manager and NSIS compiler required")

    prefix = f"Rupor/test-uninstall-{uuid.uuid4().hex}/"
    targets = [prefix + name for name in ("openrouter", "anthropic", "openai_compatible",
                                         "openrouter/second", "anthropic/third", "future-provider")]
    outside = prefix.rstrip("/") + "-outside"
    exe = tmp_path / "cleanup.exe"
    script = tmp_path / "cleanup.nsi"
    script.write_text(f'''Unicode true
RequestExecutionLevel user
SilentInstall silent
OutFile "{exe}"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "{ROOT / 'ui/src-tauri/windows/hooks.nsh'}"
Var DeleteAppDataCheckboxState
Var UpdateMode
Section
  StrCpy $DeleteAppDataCheckboxState 0
  StrCpy $UpdateMode 0
  ${{GetParameters}} $R0
  ${{If}} $R0 == "delete"
    StrCpy $DeleteAppDataCheckboxState 1
  ${{ElseIf}} $R0 == "update"
    StrCpy $DeleteAppDataCheckboxState 1
    StrCpy $UpdateMode 1
  ${{EndIf}}
  !insertmacro RUPOR_REMOVE_CREDENTIALS "{prefix}*"
SectionEnd
''', encoding="utf-8-sig")
    result = subprocess.run([compiler, "-V2", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        for target in [*targets, outside]:
            credman.write(target, "synthetic-release-test")
        for mode in ("keep", "update", "delete", "delete"):
            run = subprocess.run([str(exe), mode], timeout=30)
            assert run.returncode == 0
            for target in targets:
                assert (credman.read(target) is None) == (mode == "delete"), target
            assert credman.read(outside) == "synthetic-release-test"
    finally:
        for target in [*targets, outside]:
            credman.delete(target)
