"""Configurable Chat Completions contract, without external network calls."""
import json
import sqlite3
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

from rupor import ai, config, credman
from rupor.storage import Storage
from test_ai import RAW, Recorder, http_error, rec, settings  # noqa: F401


def compatible(**kw: Any) -> config.Settings:
    return settings(**{"ai_provider": "openai_compatible", "command_provider": "openai_compatible",
                       "openai_model": "custom-model", "openai_base_url": "https://example.test/v1", **kw})


def test_request_and_optional_key(rec: Recorder) -> None:
    res = ai.cleanup(RAW, "normal", compatible(
        openai_base_url="http://localhost:8080/v1/",
        openai_extra_json='{"thinking":{"type":"disabled"},"temperature":0.2}'), [])
    call = rec.calls[0]
    assert call["url"] == "http://localhost:8080/v1/chat/completions"
    assert "authorization" not in call["headers"]
    assert call["body"]["model"] == "custom-model"
    assert call["body"]["thinking"] == {"type": "disabled"}
    assert call["body"]["temperature"] == 0.2
    assert call["body"]["stream"] is False
    assert call["local"] is True
    assert "usage" not in call["body"] and "provider" not in call["body"]
    assert res.provider == "openai_compatible"
    assert res.cost_estimated is False


def test_command_uses_same_endpoint(rec: Recorder) -> None:
    ai.command("Translate", "Hello", compatible(), api_key="test-key")
    assert rec.calls[0]["headers"]["authorization"] == "Bearer test-key"
    assert ai.provider_model(compatible(), command=True) == ("openai_compatible", "custom-model")


@pytest.mark.parametrize("extra", ['[]', '{', '{"model":"x"}', '{"messages":[]}',
                                  '{"stream":true}', '{"api_key":"secret"}',
                                  '{"x":NaN}', '{"x":Infinity}'])
def test_invalid_json_patch_is_atomic(extra: str) -> None:
    s = config.Settings()
    with pytest.raises(ValueError):
        config.apply_patch(s, {"ai_provider": "openai_compatible", "openai_extra_json": extra})
    assert s.ai_provider == "openrouter"


@pytest.mark.parametrize("url", ["ftp://host", "http://", "https://user:pass@host", "https://host/v1?key=x"])
def test_invalid_endpoint(url: str) -> None:
    with pytest.raises(ValueError):
        config.apply_patch(config.Settings(), {"openai_base_url": url})


def test_settings_accept_provider_and_nullable_tariffs() -> None:
    s = config.Settings()
    config.apply_patch(s, {"ai_provider": "openai_compatible", "command_provider": "openai_compatible",
                          "openai_input_price": 0, "openai_output_price": None})
    assert s.openai_input_price == 0 and s.openai_output_price is None


@pytest.mark.parametrize("price", [-1, True, float("inf"), float("nan"), "2"])
def test_invalid_tariff(price: Any) -> None:
    with pytest.raises(ValueError):
        config.apply_patch(config.Settings(), {"openai_input_price": price})


@pytest.mark.parametrize("server_cost,expected,estimated", [(None, 0.00096, True), (0.2, 0.2, False), (0, 0, False)])
def test_cache_aware_pricing_and_server_precedence(rec: Recorder, server_cost: float | None,
                                                 expected: float, estimated: bool) -> None:
    rec.reply = lambda req: {"choices": [{"message": {"content": "Done"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 60,
                  "prompt_tokens_details": {"cached_tokens": 100}, "cost": server_cost}}
    res = ai.cleanup(RAW, "normal", compatible(openai_input_price=2, openai_output_price=5,
                                              openai_cached_input_price=0.6), [])
    assert res.cost_usd == pytest.approx(expected)
    assert res.cost_estimated is estimated


@pytest.mark.parametrize("command", [False, True])
@pytest.mark.parametrize("prices", [(100, 200, 50), (None, None, None)])
def test_inflight_request_keeps_original_tariffs(rec: Recorder, command: bool,
                                                prices: tuple[float | None, ...]) -> None:
    s = compatible(openai_input_price=1, openai_output_price=2, openai_cached_input_price=0.5)

    def reply(req: Any) -> dict[str, Any]:
        # Settings can change while HTTP is pending; this response is still for the old model.
        config.apply_patch(s, {"openai_base_url": "https://other.test/v1", "openai_model": "other-model",
                              **dict(zip(("openai_input_price", "openai_output_price",
                                          "openai_cached_input_price"), prices))})
        return {"choices": [{"message": {"content": "Done."}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 1000,
                          "prompt_tokens_details": {"cached_tokens": 200}}}

    rec.reply = reply
    result = (ai.command("Translate", "Text", s) if command else ai.cleanup(RAW, "normal", s, []))
    assert rec.calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert rec.calls[0]["body"]["model"] == result.model == "custom-model"
    assert result.cost_usd == pytest.approx(0.0029)
    assert result.cost_estimated


@pytest.mark.parametrize("usage", [{}, {"prompt_tokens": 4}, {"prompt_tokens": True, "completion_tokens": 2}])
def test_missing_or_invalid_usage_is_unknown(rec: Recorder, usage: dict[str, Any]) -> None:
    rec.reply = lambda req: {"choices": [{"message": {"content": "Done"}}], "usage": usage}
    r = ai.cleanup(RAW, "normal", compatible(openai_input_price=2, openai_output_price=5), [])
    assert r.cost_usd is None and r.cost_estimated is False


@pytest.mark.parametrize("reply", [{}, {"choices": []}, {"choices": [{"message": {"content": ""}}]},
    {"choices": [{"message": {"content": None}}]},
    {"choices": [{"message": {"content": "cut"}, "finish_reason": "length"}]}])
def test_bad_response(rec: Recorder, reply: dict[str, Any]) -> None:
    rec.reply = lambda req: reply
    with pytest.raises(ai.AIError):
        ai.cleanup(RAW, "normal", compatible(), [])


def test_estimate_provenance_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "usage.db"
    with Storage(path) as st:
        st.add_ai_usage({"kind": "cleanup", "cost_usd": 0.25, "cost_estimated": True})
    with Storage(path) as st:
        stats = st.ai_usage_stats()
        assert stats["total"]["estimated_cost_calls"] == 1
        assert stats["today"]["estimated_cost_calls"] == 1
        assert stats["total"]["cost_usd"] == 0.25


@pytest.mark.parametrize("kind", ["http", "network"])
def test_custom_key_redacted_before_error_truncation(rec: Recorder, kind: str) -> None:
    key = "custom" + "sensitive" * 40
    error = (http_error(400, {"error": {"message": "echo: " + key}}) if kind == "http"
             else urllib.error.URLError("echo: " + key))
    rec.reply = lambda req: error
    with pytest.raises(ai.AIError) as caught:
        ai.cleanup(RAW, "normal", compatible(), [], api_key=key)
    assert "sensitive" not in str(caught.value)


def test_cache_falls_back_to_input_price(rec: Recorder) -> None:
    rec.reply = lambda req: {"choices": [{"message": {"content": "Done"}}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 60, "prompt_cache_hit_tokens": 100}}
    res = ai.cleanup(RAW, "normal", compatible(openai_input_price=2, openai_output_price=5), [])
    assert res.cost_estimated and res.cost_usd == pytest.approx(0.0011)


def test_no_tariffs_is_unknown_even_with_tokens(rec: Recorder) -> None:
    rec.reply = lambda req: {"choices": [{"message": {"content": "Done"}}],
                            "usage": {"prompt_tokens": 400, "completion_tokens": 60}}
    res = ai.cleanup(RAW, "normal", compatible(), [])
    assert res.cost_usd is None and not res.cost_estimated


def test_upgrade_v3_preserves_old_costs(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with Storage(path) as st:
        st.add_ai_usage({"kind": "command", "cost_usd": 0.75})
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE ai_usage DROP COLUMN cost_estimated")
        conn.execute("PRAGMA user_version = 3")
    with Storage(path) as st:
        assert st.ai_usage_stats()["total"]["cost_usd"] == 0.75
        assert st.ai_usage_stats()["total"].get("estimated_cost_calls", 0) == 0
        st.add_ai_usage({"kind": "test", "cost_usd": 0.1, "cost_estimated": True})
        assert st.ai_usage_stats()["total"]["estimated_cost_calls"] == 1


def test_local_http_cleanup_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, dict[str, Any], str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body, self.headers.get("Authorization")))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"model": "local-model", "choices": [
                {"message": {"content": "Ready."}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}}).encode())

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(credman, "read", lambda target: None)
    s = compatible(openai_base_url=f"http://127.0.0.1:{server.server_port}/v1",
                   openai_input_price=2, openai_output_price=5)
    try:
        for result in (ai.cleanup(RAW, "normal", s, []), ai.command("Translate", "Text", s)):
            assert result.text == "Ready." and result.cost_estimated
            assert result.cost_usd == pytest.approx(0.00025)
        assert len(requests) == 2
        assert all(path == "/v1/chat/completions" and auth is None for path, body, auth in requests)
        assert all(body["model"] == "custom-model" and body["stream"] is False for path, body, auth in requests)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_settings_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "settings_path", lambda: tmp_path / "settings.json")
    s = config.Settings()
    config.apply_patch(s, {"ai_provider": "openai_compatible", "command_provider": "openai_compatible",
        "openai_base_url": "https://api.deepseek.com/", "openai_model": "deepseek-flash",
        "openai_extra_json": '{"thinking":{"type":"disabled"}}',
        "openai_input_price": 1.5, "openai_output_price": 3, "openai_cached_input_price": 0})
    config.save(s)
    assert config.to_dict(config.load()) == config.to_dict(s)
