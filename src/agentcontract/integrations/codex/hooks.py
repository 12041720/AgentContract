"""Lifecycle hook execution handlers for Codex integration."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

from agentcontract.adapters.openai import OpenAICompatibleExtractionClient
from agentcontract.common.immutable import FrozenDict
from agentcontract.evidence.gate import EvidenceGate
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.guard.engine import SpecGuard
from agentcontract.integrations.codex.adapter import CodexHookAdapter
from agentcontract.integrations.codex.models import (
    CodexHookEnvelope,
    CodexHookEvent,
    HookDecision,
    PostToolUsePayload,
    PreToolUseOutput,
    PreToolUsePayload,
    SessionStartPayload,
    StopPayload,
    UserPromptSubmitPayload,
)
from agentcontract.integrations.codex.state import CodexSessionStore
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    TraceEvent,
)


def _get_extraction_client() -> StructuredExtractionClient | None:
    """Instantiate extraction client if API key is configured."""
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAICompatibleExtractionClient()
        except Exception:
            return None
    return None


def handle_session_start(
    payload: SessionStartPayload,
    store: CodexSessionStore,
) -> tuple[int, dict[str, Any]]:
    """Handle SessionStart hook event."""
    trace_id, ledger, trace_store, meta = store.get_or_create_session(payload.session_id)
    store.save_session(payload.session_id, ledger, trace_store, meta)
    return 0, {}


def handle_user_prompt_submit(
    payload: UserPromptSubmitPayload,
    store: CodexSessionStore,
    client: StructuredExtractionClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Handle UserPromptSubmit hook event: extract requirements into ConstraintLedger."""
    trace_id, ledger, trace_store, meta = store.get_or_create_session(payload.session_id)

    # 1. Record user message event into trace
    events = trace_store.list_events(trace_id)
    seq = events[-1].sequence + 1 if events else 0

    user_event = TraceEvent(
        event_id=f"evt_prompt_{seq}_{abs(hash(payload.prompt)) % 1000000:06d}",
        trace_id=trace_id,
        session_id=payload.session_id,
        sequence=seq,
        timestamp=datetime.now(timezone.utc),
        actor=ActorKind.USER,
        event_kind=EventKind.USER_MESSAGE,
        payload={"prompt": payload.prompt},
    )
    trace_store.append(user_event)

    # 2. Deduplicate prompt requirement extraction
    processed = meta.setdefault("processed_prompts", [])
    if payload.prompt not in processed:
        extraction_client = client or _get_extraction_client()
        constraints = CodexHookAdapter.extract_prompt_constraints(
            payload.prompt, client=extraction_client
        )
        for c in constraints:
            # Check if an identical constraint already exists in ledger
            exists = False
            for active_c in ledger.list_active():
                if active_c.description == c.description and active_c.scope == c.scope:
                    exists = True
                    break
            if not exists and c.id not in ledger:
                try:
                    ledger.add(c)
                except Exception:
                    pass
        processed.append(payload.prompt)

    store.save_session(payload.session_id, ledger, trace_store, meta)

    active_count = len(ledger.list_active())
    resp = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"AgentContract: {active_count} active constraint(s) registered.",
        }
    }
    return 0, resp


def handle_pre_tool_use(
    payload: PreToolUsePayload,
    store: CodexSessionStore,
) -> tuple[int, dict[str, Any]]:
    """Handle PreToolUse hook event: enforce constraints via SpecGuard."""
    trace_id, ledger, trace_store, meta = store.get_or_create_session(payload.session_id)

    # 1. Normalize payload to Action
    action = CodexHookAdapter.to_action(payload)

    # 2. Evaluate through SpecGuard
    guard = SpecGuard(ledger=ledger)
    decision = guard.evaluate(action)

    # 3. Record guard decision in trace
    events = trace_store.list_events(trace_id)
    seq = events[-1].sequence + 1 if events else 0

    guard_event = TraceEvent(
        event_id=f"evt_guard_{seq}_{abs(hash(str(payload.tool_input))) % 1000000:06d}",
        trace_id=trace_id,
        session_id=payload.session_id,
        sequence=seq,
        timestamp=datetime.now(timezone.utc),
        actor=ActorKind.GUARD,
        event_kind=EventKind.GUARD_DECISION,
        payload=decision.model_dump(mode="json"),
        metadata=FrozenDict({
            "tool_name": payload.tool_name,
            "verdict": decision.decision.value,
        }),
    )
    trace_store.append(guard_event)
    store.save_session(payload.session_id, ledger, trace_store, meta)

    # 4. Enforce Decision
    if decision.is_blocked:
        reason = f"BLOCK: Action violates constraint. {decision.reason}"
        output = PreToolUseOutput(
            permissionDecision=HookDecision.DENY,
            permissionDecisionReason=reason,
        )
        sys.stderr.write(f"\n[AgentContract SpecGuard] BLOCKED: {decision.reason}\n")
        return 2, output.to_hook_response_dict()

    output = PreToolUseOutput(permissionDecision=HookDecision.ALLOW)
    return 0, output.to_hook_response_dict()


def handle_post_tool_use(
    payload: PostToolUsePayload,
    store: CodexSessionStore,
) -> tuple[int, dict[str, Any]]:
    """Handle PostToolUse hook event: record execution outcome into trace store."""
    trace_id, ledger, trace_store, meta = store.get_or_create_session(payload.session_id)

    tool_call = CodexHookAdapter.to_tool_call(payload)
    tool_result = CodexHookAdapter.to_tool_result(payload)

    # Check if ToolCall was already recorded; if not, record it
    call_id = tool_call.call_id
    call_already_recorded = False
    try:
        trace_store.get_tool_call(trace_id, call_id)
        call_already_recorded = True
    except Exception:
        call_already_recorded = False

    events = trace_store.list_events(trace_id)
    seq = events[-1].sequence + 1 if events else 0

    call_event_id: str | None = None
    if not call_already_recorded:
        call_event_id = f"evt_call_{seq}_{abs(hash(call_id)) % 1000000:06d}"
        call_event = TraceEvent(
            event_id=call_event_id,
            trace_id=trace_id,
            session_id=payload.session_id,
            sequence=seq,
            timestamp=datetime.now(timezone.utc),
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            payload=tool_call,
            metadata=FrozenDict({"tool_name": payload.tool_name}),
        )
        trace_store.append(call_event)
        seq += 1
    else:
        existing_call_event = trace_store.list_events(trace_id)
        for ev in existing_call_event:
            if ev.event_kind == EventKind.TOOL_CALL and ev.tool_call and ev.tool_call.call_id == call_id:
                call_event_id = ev.event_id
                break

    # Record ToolResult
    result_event = TraceEvent(
        event_id=f"evt_res_{seq}_{abs(hash(call_id)) % 1000000:06d}",
        trace_id=trace_id,
        session_id=payload.session_id,
        sequence=seq,
        timestamp=datetime.now(timezone.utc),
        actor=ActorKind.TOOL,
        event_kind=EventKind.TOOL_RESULT,
        parent_id=call_event_id,
        payload=tool_result,
        metadata=FrozenDict({
            "tool_name": payload.tool_name,
            "status": tool_result.status.value,
        }),
    )
    trace_store.append(result_event)

    store.save_session(payload.session_id, ledger, trace_store, meta)
    return 0, {"hookSpecificOutput": {"hookEventName": "PostToolUse"}}


def _read_last_message_from_transcript(transcript_path: str | None) -> str | None:
    """Read last assistant message from transcript file if available."""
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.is_file():
        return None

    last_assistant: str | None = None
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("role") == "assistant" or obj.get("type") == "assistant":
                        content = obj.get("content") or obj.get("message")
                        if isinstance(content, str) and content.strip():
                            last_assistant = content.strip()
                except Exception:
                    continue
    except Exception:
        pass
    return last_assistant


def handle_stop(
    payload: StopPayload,
    store: CodexSessionStore,
    client: StructuredExtractionClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Handle Stop hook event: verify agent completion claims against trace evidence."""
    trace_id, ledger, trace_store, meta = store.get_or_create_session(payload.session_id)

    prose = payload.last_assistant_message or _read_last_message_from_transcript(payload.transcript_path)
    if not prose or not prose.strip():
        return 0, {}

    extraction_client = client or _get_extraction_client()
    claims = CodexHookAdapter.extract_completion_claims(
        prose, trace_id=trace_id, client=extraction_client
    )

    if not claims:
        return 0, {}

    gate = EvidenceGate()
    evaluations = gate.evaluate_many(claims, trace_store)
    total_claims = len(evaluations)
    verified_count = sum(1 for ev in evaluations if ev.verdict.value == "VERIFIED")
    contradicted_count = sum(1 for ev in evaluations if ev.verdict.value == "CONTRADICTED")
    unverified_count = sum(1 for ev in evaluations if ev.verdict.value == "UNVERIFIED")

    lines = [
        "AgentContract EvidenceGate Verification Report:",
        f"- Total Claims Evaluated: {total_claims}",
        f"- Verified: {verified_count}",
        f"- Contradicted: {contradicted_count}",
        f"- Unverified: {unverified_count}",
    ]
    for ev in evaluations:
        status_tag = f"[{ev.verdict.value}]"
        lines.append(f"  * {status_tag} {ev.claim.description} -> {ev.reason}")

    summary_text = "\n".join(lines)
    sys.stderr.write(f"\n{summary_text}\n")

    evidence_dict = {
        "verified_count": verified_count,
        "contradicted_count": contradicted_count,
        "unverified_count": unverified_count,
        "evaluations": [
            {
                "claim_id": ev.claim.claim_id,
                "claim_type": ev.claim.claim_type.value,
                "description": ev.claim.description,
                "verdict": ev.verdict.value,
                "reason": ev.reason,
            }
            for ev in evaluations
        ],
    }
    store.save_session(payload.session_id, ledger, trace_store, meta, evidence=evidence_dict)

    resp = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": summary_text,
        }
    }
    return 0, resp


def run_hook(
    stdin_data: str | None = None,
    event_name: str | None = None,
    session_store: CodexSessionStore | None = None,
    client: StructuredExtractionClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Parse hook input from stdin and dispatch to the appropriate event handler."""
    store = session_store or CodexSessionStore()

    if stdin_data is None:
        try:
            stdin_data = sys.stdin.read()
        except Exception:
            stdin_data = ""

    if not stdin_data or not stdin_data.strip():
        return 0, {}

    try:
        raw_data = json.loads(stdin_data)
    except Exception as err:
        sys.stderr.write(f"AgentContract: Failed to parse hook stdin JSON: {err}\n")
        return 0, {}

    # Identify hook event name
    effective_event = event_name or raw_data.get("hook_event_name") or raw_data.get("hookEventName")
    if not effective_event:
        return 0, {}

    # Normalize event name
    event_str = str(effective_event).replace("-", "_").lower()

    if "session_start" in event_str or event_str == "sessionstart":
        payload = SessionStartPayload.model_validate(raw_data)
        return handle_session_start(payload, store)

    if "user_prompt" in event_str or event_str == "userpromptsubmit":
        payload = UserPromptSubmitPayload.model_validate(raw_data)
        return handle_user_prompt_submit(payload, store, client=client)

    if "pre_tool" in event_str or event_str == "pretooluse":
        payload = PreToolUsePayload.model_validate(raw_data)
        return handle_pre_tool_use(payload, store)

    if "post_tool" in event_str or event_str == "posttooluse":
        payload = PostToolUsePayload.model_validate(raw_data)
        return handle_post_tool_use(payload, store)

    if "stop" in event_str:
        payload = StopPayload.model_validate(raw_data)
        return handle_stop(payload, store, client=client)

    return 0, {}


def main() -> None:
    """CLI entry point for running hooks as separate subprocesses."""
    # Optional event name from first argument (e.g. `python -m agentcontract.integrations.codex.hooks pre-tool-use`)
    arg_event = sys.argv[1] if len(sys.argv) > 1 else None
    exit_code, response = run_hook(event_name=arg_event)
    if response:
        print(json.dumps(response))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
