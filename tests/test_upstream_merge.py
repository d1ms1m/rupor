"""Compatibility with settings and schema versions shipped by both repositories."""
import json
import sqlite3
from pathlib import Path

import pytest

from rupor import config
from rupor.storage import Storage, _MIGRATIONS, SCHEMA_VERSION


@pytest.mark.parametrize("variant", ["fork", "upstream"])
def test_upgrade_both_v4_schemas_preserves_usage(tmp_path: Path, variant: str) -> None:
    path = tmp_path / "old.db"
    # Construct the actual historical layouts, independently of the new migrations.
    with sqlite3.connect(path) as conn:
        for migration in _MIGRATIONS[:3]:
            for step in migration:
                assert isinstance(step, str)
                conn.execute(step)
        if variant == "fork":
            conn.execute("ALTER TABLE ai_usage ADD COLUMN cost_estimated INTEGER NOT NULL DEFAULT 0")
            conn.execute("INSERT INTO ai_usage(ts, kind, cost_usd, cost_estimated) "
                         "VALUES(1, 'cleanup', 0.75, 1)")
        else:
            conn.execute("ALTER TABLE ai_usage ADD COLUMN key_id TEXT")
            conn.execute("CREATE INDEX ai_usage_key ON ai_usage(key_id, ts)")
            conn.execute("INSERT INTO ai_usage(ts, kind, cost_usd, key_id) "
                         "VALUES(1, 'cleanup', 0.75, 'existing-key')")
        conn.execute("PRAGMA user_version = 4")

    for _ in range(2):  # Reopening must not add duplicate columns or lose provenance.
        with Storage(path) as st:
            totals = st.ai_usage_stats()["total"]
            assert totals["cost_usd"] == 0.75
            assert totals["calls"] == 1
            assert totals.get("estimated_cost_calls", 0) == (1 if variant == "fork" else 0)
            assert st.ai_key_spend("existing-key")["cost_usd"] == (0.75 if variant == "upstream" else 0)
    with Storage(path) as st:
        st.add_ai_usage({"kind": "command", "cost_usd": 0.1,
                         "cost_estimated": True, "key_id": "new-key"})
        assert st.ai_key_spend("new-key")["cost_usd"] == 0.1
        assert st.ai_usage_stats()["total"]["estimated_cost_calls"] == (2 if variant == "fork" else 1)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_old_custom_provider_settings_survive_key_chain_migration(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "settings_path", lambda: path)
    old = config.to_dict(config.Settings())
    old.pop("ai_keys")
    old.update(ai_provider="openai_compatible", command_provider="openai_compatible",
               openai_base_url="https://example.test/v1", openai_model="custom-model",
               openai_extra_json='{"temperature":0.2}', openai_input_price=1.5,
               openai_output_price=3, openai_cached_input_price=0)
    path.write_text(json.dumps(old), encoding="utf-8")
    for _ in range(2):
        loaded = config.load()
        for key, value in old.items():
            assert getattr(loaded, key) == value, key
        assert [entry["provider"] for entry in loaded.ai_keys] == ["openrouter", "anthropic"]


@pytest.mark.parametrize("cleanup,command,first", [
    ("openai_compatible", "anthropic", "anthropic"),
    ("anthropic", "openai_compatible", "anthropic"),
])
def test_mixed_custom_and_cloud_settings_preserve_selected_provider(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        cleanup: str, command: str, first: str) -> None:
    path = tmp_path / "settings.json"
    monkeypatch.setattr(config, "settings_path", lambda: path)
    old = config.to_dict(config.Settings())
    old.pop("ai_keys")
    old.update(ai_provider=cleanup, command_provider=command)
    path.write_text(json.dumps(old), encoding="utf-8")
    for _ in range(2):
        loaded = config.load()
        assert loaded.ai_provider == ("openai_compatible" if cleanup == "openai_compatible" else "keys")
        assert loaded.command_provider == ("openai_compatible" if command == "openai_compatible" else "keys")
        assert loaded.ai_keys[0]["provider"] == first
