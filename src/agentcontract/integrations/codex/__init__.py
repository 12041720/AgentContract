"""Codex integration package for AgentContract lifecycle hooks."""

from agentcontract.integrations.codex.adapter import CodexHookAdapter
from agentcontract.integrations.codex.models import (
    CodexHookEnvelope,
    CodexHookEvent,
    PostToolUsePayload,
    PreToolUsePayload,
    SessionStartPayload,
    StopPayload,
    UserPromptSubmitPayload,
)
from agentcontract.integrations.codex.state import CodexSessionStore


def __getattr__(name: str):
    if name in {
        "handle_post_tool_use",
        "handle_pre_tool_use",
        "handle_session_start",
        "handle_stop",
        "handle_user_prompt_submit",
        "run_hook",
    }:
        import agentcontract.integrations.codex.hooks as _hooks
        return getattr(_hooks, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "CodexHookAdapter",
    "CodexHookEnvelope",
    "CodexHookEvent",
    "CodexSessionStore",
    "PostToolUsePayload",
    "PreToolUsePayload",
    "SessionStartPayload",
    "StopPayload",
    "UserPromptSubmitPayload",
    "handle_post_tool_use",
    "handle_pre_tool_use",
    "handle_session_start",
    "handle_stop",
    "handle_user_prompt_submit",
    "run_hook",
]
