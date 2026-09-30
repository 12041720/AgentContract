"""Domain models and schemas for Codex lifecycle hooks."""

from enum import Enum
from typing import Any, Mapping
from pydantic import BaseModel, ConfigDict, Field


class CodexHookEvent(str, Enum):
    """Supported Codex hook event names."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


class CodexHookEnvelope(BaseModel):
    """Common envelope received on stdin by every Codex lifecycle hook."""

    model_config = ConfigDict(extra="allow", frozen=True)

    session_id: str = Field(description="Unique identifier for the agent session.")
    hook_event_name: str = Field(description="Name of the lifecycle hook event.")
    cwd: str | None = Field(default=None, description="Working directory of the agent.")
    transcript_path: str | None = Field(default=None, description="Path to the session transcript JSONL.")


class SessionStartPayload(CodexHookEnvelope):
    """Payload for SessionStart lifecycle event."""

    source: str | None = Field(default=None, description="Session trigger source (e.g. startup, resume).")


class UserPromptSubmitPayload(CodexHookEnvelope):
    """Payload for UserPromptSubmit lifecycle event."""

    prompt: str = Field(description="The user instruction/prompt text submitted.")


class PreToolUsePayload(CodexHookEnvelope):
    """Payload for PreToolUse lifecycle event."""

    tool_name: str = Field(description="Name of the tool the model proposes to call.")
    tool_input: Mapping[str, Any] = Field(default_factory=dict, description="Proposed tool invocation arguments.")
    tool_use_id: str | None = Field(default=None, description="Unique tool call correlation ID.")


class PostToolUsePayload(CodexHookEnvelope):
    """Payload for PostToolUse lifecycle event."""

    tool_name: str = Field(description="Name of the tool that executed.")
    tool_input: Mapping[str, Any] = Field(default_factory=dict, description="Arguments the tool executed with.")
    tool_use_id: str | None = Field(default=None, description="Tool call correlation ID.")
    tool_response: Any = Field(default=None, description="Observed outcome or output of the tool execution.")


class StopPayload(CodexHookEnvelope):
    """Payload for Stop lifecycle event."""

    stop_hook_active: bool | None = Field(default=None, description="Whether the stop hook is active.")
    last_assistant_message: str | None = Field(default=None, description="Final assistant message text if available.")


class HookDecision(str, Enum):
    """Codex hook permission decision."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class PreToolUseOutput(BaseModel):
    """Structured response for PreToolUse hook."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    hookEventName: str = "PreToolUse"
    permissionDecision: HookDecision = HookDecision.ALLOW
    permissionDecisionReason: str | None = None

    def to_hook_response_dict(self) -> dict[str, Any]:
        """Convert into Codex expected hookSpecificOutput envelope."""
        output: dict[str, Any] = {
            "hookEventName": self.hookEventName,
            "permissionDecision": self.permissionDecision.value,
        }
        if self.permissionDecisionReason:
            output["permissionDecisionReason"] = self.permissionDecisionReason
        resp: dict[str, Any] = {
            "hookSpecificOutput": output,
        }
        if self.permissionDecision == HookDecision.DENY:
            resp["decision"] = "block"
            resp["continue"] = False
            resp["reason"] = self.permissionDecisionReason
        else:
            resp["decision"] = "approve"
            resp["continue"] = True
        return resp
