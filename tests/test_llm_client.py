"""Tests for llm_client.py and pawpal_logging.py. No API key or network needed: the SDK is stubbed."""

import json
import logging
from types import SimpleNamespace as NS

import anthropic
import httpx2
import pytest

from llm_client import ClaudeClient, FakeLLM, LLMError
from pawpal_logging import setup_logging

# --- Helpers -------------------------------------------------------------------------


class StubMessages:
    """Stands in for client.messages: records the request and returns (or raises) a set result."""

    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def make_response(*blocks, stop="end_turn"):
    """Build an object shaped like an SDK Message with the given content blocks."""
    return NS(content=list(blocks), stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5))


def text(t):
    return NS(type="text", text=t)


def thinking():
    return NS(type="thinking", thinking="")


def client_with(response=None, error=None):
    """Return a ClaudeClient wired to a stub, plus the stub so tests can inspect the request."""
    stub = StubMessages(response, error)
    return ClaudeClient(model="claude-test", effort="low", sdk_client=NS(messages=stub)), stub


# --- ClaudeClient --------------------------------------------------------------------


def test_complete_returns_text_and_skips_thinking_blocks():
    client, _ = client_with(make_response(thinking(), text('{"ok": true}')))
    assert client.complete("sys", "hi") == '{"ok": true}'


def test_complete_sends_schema_as_structured_output():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    client, stub = client_with(make_response(text("{}")))
    client.complete("sys", "hi", schema=schema)
    assert stub.kwargs["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert stub.kwargs["model"] == "claude-test"
    assert stub.kwargs["system"] == "sys"
    assert stub.kwargs["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_without_schema_sends_no_format():
    client, stub = client_with(make_response(text("hello")))
    client.complete("sys", "hi")
    assert "format" not in stub.kwargs["output_config"]


@pytest.mark.parametrize(
    "response, message",
    [
        (make_response(text("partial"), stop="refusal"), "declined"),
        (make_response(text("partial"), stop="max_tokens"), "cut off"),
        (make_response(thinking()), "empty reply"),
    ],
)
def test_complete_raises_llm_error_for_unusable_replies(response, message):
    client, _ = client_with(response)
    with pytest.raises(LLMError, match=message):
        client.complete("sys", "hi")


def test_connection_failure_becomes_friendly_llm_error():
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com"))
    client, _ = client_with(error=error)
    with pytest.raises(LLMError, match="internet connection"):
        client.complete("sys", "hi")


def test_model_and_effort_come_from_environment(monkeypatch):
    monkeypatch.setenv("PAWPAL_MODEL", "claude-from-env")
    monkeypatch.setenv("PAWPAL_EFFORT", "medium")
    client = ClaudeClient(sdk_client=NS(messages=StubMessages()))
    assert (client.model, client.effort) == ("claude-from-env", "medium")


# --- FakeLLM -------------------------------------------------------------------------


def test_fake_llm_returns_replies_in_order_and_records_calls():
    fake = FakeLLM(["first", {"tasks": []}])
    assert fake.complete("sys", "a") == "first"
    assert json.loads(fake.complete("sys", "b", schema={"x": 1})) == {"tasks": []}
    assert [c["prompt"] for c in fake.calls] == ["a", "b"]
    assert fake.calls[1]["schema"] == {"x": 1}


def test_fake_llm_raises_scripted_errors_and_runs_out():
    fake = FakeLLM([LLMError("boom")])
    with pytest.raises(LLMError, match="boom"):
        fake.complete("sys", "a")
    with pytest.raises(LLMError, match="no scripted replies"):
        fake.complete("sys", "b")


# --- Logging -------------------------------------------------------------------------


def test_setup_logging_writes_to_file_and_is_safe_to_call_twice(tmp_path):
    log_file = tmp_path / "logs" / "test.log"
    logger = logging.getLogger("pawpal")
    before = list(logger.handlers)
    try:
        setup_logging(log_file=log_file)
        setup_logging(log_file=log_file)  # Streamlit reruns: must not add a second handler
        added = [h for h in logger.handlers if h not in before]
        assert len(added) == 1
        logging.getLogger("pawpal.test").info("hello log")
        added[0].flush()
        assert "pawpal.test: hello log" in log_file.read_text(encoding="utf-8")
    finally:
        for h in [h for h in logger.handlers if h not in before]:
            logger.removeHandler(h)
            h.close()
