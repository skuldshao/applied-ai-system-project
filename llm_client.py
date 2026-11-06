"""LLM access for PawPal+: a real Claude client and a scripted fake one.

ClaudeClient calls the Claude API. FakeLLM returns replies written in advance, so tests run
without an API key, a network connection, or any cost. Both have the same complete() method,
so the planner never needs to know which one it was given.

Run `python llm_client.py` to check that your API key in .env works.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

import anthropic
from dotenv import load_dotenv

logger = logging.getLogger("pawpal.llm")

# .env sits next to this file, so the key loads no matter which folder the app is started from.
ENV_FILE = Path(__file__).parent / ".env"
DEFAULT_MODEL = "claude-haiku-5-5"
# "low" keeps replies fast; turning a short request into a few tasks doesn't need deep thinking.
DEFAULT_EFFORT = "low"
# A ceiling, not a target: the model stops when it's done. Kept high so thinking never truncates it.
MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """Any failure talking to the model. The message is safe to show to the user."""


class LLMClient(Protocol):
    """What the planner needs from a model: one prompt in, one reply out."""

    model: str

    def complete(self, system: str, prompt: str, schema: Optional[Dict[str, Any]] = None) -> str:
        """Return the model's reply text. With a JSON schema, the reply is JSON matching it."""
        ...


class ClaudeClient:
    """Calls Claude through the official Anthropic SDK.

    The API key comes from ANTHROPIC_API_KEY (loaded from .env). The model and effort can be
    changed with PAWPAL_MODEL and PAWPAL_EFFORT without touching the code.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        sdk_client: Optional[anthropic.Anthropic] = None,
    ) -> None:
        """Set up the client.

        Args:
            model: Model ID. Defaults to PAWPAL_MODEL, then claude-haiku-5-5.
            effort: "low", "medium", "high", ... Defaults to PAWPAL_EFFORT, then "low".
            sdk_client: An Anthropic client to use instead of building one; tests pass a stub.

        Raises:
            LLMError: If no API key is configured.
        """
        load_dotenv(ENV_FILE)
        self.model = model or os.getenv("PAWPAL_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.getenv("PAWPAL_EFFORT", DEFAULT_EFFORT)
        if sdk_client is not None:
            self._client = sdk_client
        else:
            try:
                self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
            except anthropic.AnthropicError as err:
                raise LLMError(
                    "No Claude API key found. Copy .env.example to .env and set ANTHROPIC_API_KEY."
                ) from err

    def complete(self, system: str, prompt: str, schema: Optional[Dict[str, Any]] = None) -> str:
        """Send one request and return the reply text.

        Each call is a single, fresh request. The planner puts everything the model needs
        (including an earlier draft to fix) into the prompt, so no conversation history is kept.

        Args:
            system: Instructions for the model.
            prompt: The user's request plus any context.
            schema: Optional JSON schema. When given, the API guarantees the reply is valid JSON
                that matches it (structured outputs).

        Returns:
            The reply text (a JSON string when schema is given).

        Raises:
            LLMError: On any API failure, a refusal, or a cut-off or empty reply.
        """
        output_config: Dict[str, Any] = {"effort": self.effort}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}

        started = time.perf_counter()
        # Most specific errors first: each gets a message the user can act on.
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
            )
        except anthropic.AuthenticationError as err:
            logger.error("API key rejected (401)")
            raise LLMError("The API key was rejected. Check ANTHROPIC_API_KEY in .env.") from err
        except anthropic.RateLimitError as err:
            logger.warning("Rate limited (429)")
            raise LLMError("Too many requests right now. Wait a moment and try again.") from err
        except anthropic.APIStatusError as err:
            logger.error("API error %s: %s", err.status_code, err.message)
            raise LLMError(f"The Claude API returned an error ({err.status_code}).") from err
        except anthropic.APIConnectionError as err:
            logger.error("Connection failed: %s", err)
            raise LLMError("Couldn't reach the Claude API. Check your internet connection.") from err

        logger.info(
            "model=%s stop=%s tokens_in=%s tokens_out=%s seconds=%.1f",
            self.model,
            response.stop_reason,
            response.usage.input_tokens,
            response.usage.output_tokens,
            time.perf_counter() - started,
        )
        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request.")
        if response.stop_reason == "max_tokens":
            raise LLMError("The model's reply was cut off before it finished.")
        # The reply can also hold thinking blocks; only the text blocks are the answer.
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise LLMError("The model returned an empty reply.")
        return text


class FakeLLM:
    """A stand-in for ClaudeClient that returns scripted replies, for tests.

    Each call to complete() returns the next reply in the list. A dict is returned as JSON,
    and an Exception is raised instead of returned, to test error handling. Every call is
    recorded in .calls so tests can check what the planner sent.
    """

    model = "fake-llm"

    def __init__(self, replies: List[Union[str, Dict[str, Any], Exception]]) -> None:
        """Store the replies to hand out, in order."""
        self.replies = list(replies)
        self.calls: List[Dict[str, Any]] = []

    def complete(self, system: str, prompt: str, schema: Optional[Dict[str, Any]] = None) -> str:
        """Record the call and return (or raise) the next scripted reply.

        Raises:
            LLMError: If every scripted reply has already been used.
        """
        self.calls.append({"system": system, "prompt": prompt, "schema": schema})
        if not self.replies:
            raise LLMError("FakeLLM has no scripted replies left.")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply)


if __name__ == "__main__":
    # Setup check: python llm_client.py
    from pawpal_logging import setup_logging

    setup_logging()
    try:
        client = ClaudeClient()
        reply = client.complete("Reply in five words or fewer.", "Say that PawPal+ is connected.")
        print(f"✅ {client.model} replied: {reply}")
    except LLMError as err:
        print(f"❌ {err}")
        raise SystemExit(1)
