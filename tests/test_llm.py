"""The optional Claude position classifier: off by default, closed label set, never breaks the pipeline.
Runs the real Anthropic SDK against a fake HTTP transport (no network, no API key needed)."""
import json

import anthropic
import httpx2
import pytest

from app.content import llm
from app.settings import reset_settings_cache


@pytest.fixture
def fake_claude(monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    reset_settings_cache()
    llm.classify_baseball_position.cache_clear()
    state = {"requests": [], "reply": {"group": "LHP"}, "stop_reason": "end_turn"}

    def handler(req: httpx2.Request) -> httpx2.Response:
        state["requests"].append(req)
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(state["reply"])}],
            "stop_reason": state["stop_reason"], "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        })

    real = anthropic.Anthropic

    def factory(**kw):
        return real(**kw, max_retries=0,
                    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))

    monkeypatch.setattr(anthropic, "Anthropic", factory)
    yield state
    llm.classify_baseball_position.cache_clear()


def test_disabled_by_default_makes_no_call():
    llm.classify_baseball_position.cache_clear()
    assert llm.classify_baseball_position("Southpaw hurler") is None


def test_structured_request_and_answer(fake_claude):
    assert llm.classify_baseball_position("Southpaw hurler") == "LHP"
    req = fake_claude["requests"][0]
    body = json.loads(req.content)
    assert body["model"] == "claude-opus-5"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in req.headers["anthropic-beta"]


def test_unknown_and_refusal_mean_none(fake_claude):
    fake_claude["reply"] = {"group": "UNKNOWN"}
    assert llm.classify_baseball_position("Team manager") is None
    fake_claude["stop_reason"] = "refusal"
    fake_claude["reply"] = {"group": "C"}
    assert llm.classify_baseball_position("Something else") is None


def test_label_outside_closed_set_is_discarded(fake_claude):
    fake_claude["reply"] = {"group": "QB"}
    assert llm.classify_baseball_position("Quarterback") is None
