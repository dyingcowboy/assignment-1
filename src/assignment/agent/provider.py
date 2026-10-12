"""Translate harness request options for the official DeepSeek endpoint."""

from __future__ import annotations

from functools import wraps
import os
from typing import Any

from openai import OpenAI


def configure_provider(client: OpenAI) -> None:
    """Adapt requests at the client boundary, preserving harness logging."""

    if client.base_url.host != "api.deepseek.com":
        return

    effort = os.environ.get("DEEPSEEK_REASONING_EFFORT", "low")
    if effort not in {"none", "low", "high", "max"}:
        raise ValueError("DEEPSEEK_REASONING_EFFORT must be none, low, high, or max.")

    # A 4K cap can be exhausted by reasoning before an action is emitted.
    # Keep effort low by default and give actions room to finish. This is an
    # output ceiling, not a target; short actions consume only what they use.
    try:
        action_max_tokens = int(os.environ.get("DEEPSEEK_MAX_TOKENS", "8192"))
    except ValueError as exc:
        raise ValueError("DEEPSEEK_MAX_TOKENS must be an integer.") from exc
    if not 1 <= action_max_tokens <= 393_216:
        raise ValueError("DEEPSEEK_MAX_TOKENS must be between 1 and 393216.")

    original_create = client.chat.completions.create

    @wraps(original_create)
    def create(**kwargs: Any) -> Any:
        # DeepSeek uses max_tokens for both action and summary budgets.
        if "max_completion_tokens" in kwargs:
            budget = kwargs.pop("max_completion_tokens")
            kwargs.setdefault("max_tokens", budget)

        # Summaries should spend their budget on working memory. Forced tool
        # recovery also needs non-thinking mode: DeepSeek's thinking mode
        # rejects forced tool_choice on the Chat Completions endpoint.
        tool_choice = kwargs.get("tool_choice")
        force_tool = tool_choice == "required" or isinstance(tool_choice, dict)
        request_effort = effort if kwargs.get("tools") and not force_tool else "none"
        if kwargs.get("tools") and not force_tool:
            kwargs["max_tokens"] = action_max_tokens
        kwargs["reasoning_effort"] = request_effort
        if kwargs.get("tools") and request_effort != "none":
            # Non-thinking recovery responses have no reasoning_content. When
            # returning to thinking mode, DeepSeek requires that field on all
            # assistant messages, including those without tool calls. An empty
            # string represents no reasoning; keep real reasoning verbatim.
            # Copy only the affected messages so logged history stays intact.
            kwargs["messages"] = [
                {**message, "reasoning_content": ""}
                if message.get("role") == "assistant"
                and message.get("reasoning_content") is None
                else message
                for message in kwargs["messages"]
            ]
        kwargs["extra_body"] = {
            **(kwargs.get("extra_body") or {}),
            "thinking": {
                "type": "disabled" if request_effort == "none" else "enabled"
            },
        }
        return original_create(**kwargs)

    client.chat.completions.create = create
