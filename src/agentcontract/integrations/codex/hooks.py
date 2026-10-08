"""Lifecycle hook execution handlers for Codex integration."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

if sys.platform == "win32":
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agentcontract.adapters.openai import OpenAICompatibleExtractionClient
from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.models import ConstraintStrength
from agentcontract.evidence.gate import EvidenceGate
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.guard.engine import SpecGuard
from agentcontract.guard.models import Action, ActionKind
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
from agentcontract.integrations.codex.state import (
    CodexSessionStore,
    CorruptedLedgerError,
    CorruptedSessionStateError,
)
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    TraceEvent,
)


def _get_extraction_client() -> StructuredExtractionClient | None:
    """Instantiate extraction client if API key is configured."""
    try:
        from agentcontract.common.config import load_config
        load_config(search_parents=True)
    except Exception:
        pass

    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAICompatibleExtractionClient()
        except Exception as err:
            sys.stderr.write(f"[AgentContract WARNING] Failed to initialize extraction client: {err}\n")
            return None
    return None


def handle_session_start(
    payload: SessionStartPayload,
    store: CodexSessionStore,
) -> tuple[int, dict[str, Any]]:
    """Handle SessionStart hook event."""
    with store.session_transaction(payload.session_id) as tx:
        pass
    return 0, {}


def handle_user_prompt_submit(
    payload: UserPromptSubmitPayload,
    store: CodexSessionStore,
    client: StructuredExtractionClient | None = None,
) -> tuple[int, dict[str, Any]]:
    """Handle UserPromptSubmit hook event: extract requirements into ConstraintLedger."""
    with store.session_transaction(payload.session_id) as tx:
        # 1. Record user message event into trace
        events = tx.trace_store.list_events(tx.trace_id)
        seq = events[-1].sequence + 1 if events else 0

        user_event = TraceEvent(
            event_id=f"evt_prompt_{seq}_{abs(hash(payload.prompt)) % 1000000:06d}",
            trace_id=tx.trace_id,
            session_id=payload.session_id,
            sequence=seq,
            timestamp=datetime.now(timezone.utc),
            actor=ActorKind.USER,
            event_kind=EventKind.USER_MESSAGE,
            payload={"prompt": payload.prompt},
        )
        tx.trace_store.append(user_event)

        # 2. Deduplicate prompt requirement extraction
        processed = tx.meta.setdefault("processed_prompts", [])
        if payload.prompt not in processed:
            extraction_client = client or _get_extraction_client()
            constraints = CodexHookAdapter.extract_prompt_constraints(
                payload.prompt, client=extraction_client
            )
            for c in constraints:
                # Check if an identical constraint already exists in ledger
                exists = False
                for active_c in tx.ledger.list_active():
                    if active_c.description == c.description and active_c.scope == c.scope:
                        exists = True
                        break
                if not exists and c.id not in tx.ledger:
                    try:
                        tx.ledger.add(c)
                    except Exception:
                        pass
            processed.append(payload.prompt)

        active_count = len(tx.ledger.list_active())

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
    """Handle PreToolUse hook event: enforce constraints via SpecGuard and opaque Bash policy."""
    try:
        with store.session_transaction(payload.session_id) as tx:
            # 1. Normalize payload to Action
            action = CodexHookAdapter.to_action(payload)

            # 2. Check for active HARD filesystem constraints
            active_hard_fs = [
                c for c in tx.ledger.list_active()
                if c.strength == ConstraintStrength.HARD and (
                    (c.scope and c.scope.target_type in ("filesystem", "file", "dir", "folder"))
                    or (c.scope and c.scope.paths)
                )
            ]

            # 3. Check opaque/destructive command fail-closed policy
            is_opaque = bool(action.context.get("is_opaque"))
            if is_opaque and active_hard_fs:
                opaque_reason = action.context.get("opaque_reason") or "opaque shell command"
                block_reason = (
                    f"BLOCK: Opaque/destructive shell command rejected under active HARD filesystem constraints "
                    f"(fail-closed policy: cannot statically guarantee protected paths are not modified). "
                    f"Reason: {opaque_reason}. Command: {action.operation!r}"
                )
                events = tx.trace_store.list_events(tx.trace_id)
                seq = events[-1].sequence + 1 if events else 0
                guard_event = TraceEvent(
                    event_id=f"evt_guard_{seq}_{abs(hash(str(payload.tool_input))) % 1000000:06d}",
                    trace_id=tx.trace_id,
                    session_id=payload.session_id,
                    sequence=seq,
                    timestamp=datetime.now(timezone.utc),
                    actor=ActorKind.GUARD,
                    event_kind=EventKind.GUARD_DECISION,
                    payload={
                        "decision": "BLOCK",
                        "reason": block_reason,
                        "action": action.model_dump(mode="json"),
                    },
                    metadata=FrozenDict({
                        "tool_name": payload.tool_name,
                        "verdict": "BLOCK",
                        "policy": "opaque_bash_fail_closed",
                    }),
                )
                tx.trace_store.append(guard_event)

                output = PreToolUseOutput(
                    permissionDecision=HookDecision.DENY,
                    permissionDecisionReason=block_reason,
                )
                sys.stderr.write(f"\n[AgentContract SpecGuard] BLOCKED: {block_reason}\n")
                return 0, output.to_hook_response_dict()

            # 4. Standard SpecGuard evaluation
            guard = SpecGuard(ledger=tx.ledger)
            decision = guard.evaluate(action)

            # If action has fine-grained patch operations, evaluate each (path, kind) independently
            patch_ops = action.context.get("patch_operations")
            if patch_ops and not decision.is_blocked:
                for p_path, p_kind in patch_ops:
                    sub_action = Action(
                        action_kind=ActionKind(p_kind),
                        tool_name=payload.tool_name,
                        target_path=p_path,
                        paths=(p_path,),
                        target_type="filesystem",
                        operation="apply_patch",
                        payload=payload.tool_input,
                        context=FrozenDict({
                            "call_id": payload.tool_use_id or "sub_call",
                            "session_id": payload.session_id,
                            "sub_path": p_path,
                        }),
                    )
                    sub_dec = guard.evaluate(sub_action)
                    if sub_dec.is_blocked:
                        decision = sub_dec
                        break

            # 5. Record guard decision in trace
            events = tx.trace_store.list_events(tx.trace_id)
            seq = events[-1].sequence + 1 if events else 0

            guard_event = TraceEvent(
                event_id=f"evt_guard_{seq}_{abs(hash(str(payload.tool_input))) % 1000000:06d}",
                trace_id=tx.trace_id,
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
            tx.trace_store.append(guard_event)

            # 6. Enforce Decision
            if decision.is_blocked:
                reason = f"BLOCK: Action violates constraint. {decision.reason}"
                output = PreToolUseOutput(
                    permissionDecision=HookDecision.DENY,
                    permissionDecisionReason=reason,
                )
                sys.stderr.write(f"\n[AgentContract SpecGuard] BLOCKED: {decision.reason}\n")
                return 0, output.to_hook_response_dict()

            output = PreToolUseOutput(permissionDecision=HookDecision.ALLOW)
            return 0, output.to_hook_response_dict()

    except CorruptedSessionStateError as exc:
        block_reason = (
            f"BLOCK: Persisted constraint state is corrupted or unreadable: fail-closed safety block. "
            f"Error: {exc}"
        )
        sys.stderr.write(f"\n[AgentContract SpecGuard] BLOCKED: {block_reason}\n")
        output = PreToolUseOutput(
            permissionDecision=HookDecision.DENY,
            permissionDecisionReason=block_reason,
        )
        return 0, output.to_hook_response_dict()


def handle_post_tool_use(
    payload: PostToolUsePayload,
    store: CodexSessionStore,
) -> tuple[int, dict[str, Any]]:
    """Handle PostToolUse hook event: record execution outcome into trace store."""
    with store.session_transaction(payload.session_id) as tx:
        tool_call = CodexHookAdapter.to_tool_call(payload)
        tool_result = CodexHookAdapter.to_tool_result(payload)

        # Check if ToolCall was already recorded; if not, record it
        call_id = tool_call.call_id
        call_already_recorded = False
        try:
            tx.trace_store.get_tool_call(tx.trace_id, call_id)
            call_already_recorded = True
        except Exception:
            call_already_recorded = False

        events = tx.trace_store.list_events(tx.trace_id)
        seq = events[-1].sequence + 1 if events else 0

        call_event_id: str | None = None
        if not call_already_recorded:
            call_event_id = f"evt_call_{seq}_{abs(hash(call_id)) % 1000000:06d}"
            call_event = TraceEvent(
                event_id=call_event_id,
                trace_id=tx.trace_id,
                session_id=payload.session_id,
                sequence=seq,
                timestamp=datetime.now(timezone.utc),
                actor=ActorKind.AGENT,
                event_kind=EventKind.TOOL_CALL,
                payload=tool_call,
                metadata=FrozenDict({"tool_name": payload.tool_name}),
            )
            tx.trace_store.append(call_event)
            seq += 1
        else:
            existing_call_event = tx.trace_store.list_events(tx.trace_id)
            for ev in existing_call_event:
                if ev.event_kind == EventKind.TOOL_CALL and ev.tool_call and ev.tool_call.call_id == call_id:
                    call_event_id = ev.event_id
                    break

        # Record ToolResult
        result_event = TraceEvent(
            event_id=f"evt_res_{seq}_{abs(hash(call_id)) % 1000000:06d}",
            trace_id=tx.trace_id,
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
        tx.trace_store.append(result_event)

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
                    # 1. Check task_complete event
                    if obj.get("type") == "task_complete" and obj.get("last_agent_message"):
                        msg = str(obj["last_agent_message"]).strip()
                        if msg:
                            last_assistant = msg
                            continue
                    # 2. Check item_completed with AgentMessage
                    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                    if payload.get("type") == "item_completed":
                        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
                        if item.get("type") == "AgentMessage" and isinstance(item.get("content"), list):
                            texts = []
                            for block in item["content"]:
                                if isinstance(block, dict) and block.get("type") == "Text" and "text" in block:
                                    texts.append(block["text"])
                            if texts:
                                last_assistant = "\n".join(texts).strip()
                                continue
                    # 3. Check assistant role message
                    if obj.get("role") == "assistant" or obj.get("type") == "assistant":
                        content = obj.get("content") or obj.get("message")
                        if isinstance(content, str) and content.strip():
                            last_assistant = content.strip()
                        elif isinstance(content, list):
                            texts = []
                            for block in content:
                                if isinstance(block, str):
                                    texts.append(block)
                                elif isinstance(block, dict) and "text" in block and isinstance(block["text"], str):
                                    texts.append(block["text"])
                            if texts:
                                last_assistant = "\n".join(texts).strip()
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
    prose = payload.last_assistant_message or _read_last_message_from_transcript(payload.transcript_path)
    if not prose or not prose.strip():
        return 0, {}

    with store.session_transaction(payload.session_id) as tx:
        extraction_client = client or _get_extraction_client()
        claims = CodexHookAdapter.extract_completion_claims(
            prose,
            trace_id=tx.trace_id,
            client=extraction_client,
            session_id=payload.session_id,
        )

        if not claims:
            return 0, {}

        gate = EvidenceGate()
        evaluations = gate.evaluate_many(claims, tx.trace_store)
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
        tx.evidence = evidence_dict

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

    try:
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
    except CorruptedSessionStateError as exc:
        sys.stderr.write(f"[AgentContract] Corrupted session state error: {exc}\n")
        if "pre_tool" in event_str or event_str == "pretooluse":
            output = PreToolUseOutput(
                permissionDecision=HookDecision.DENY,
                permissionDecisionReason=f"BLOCK: Corrupted session state: {exc}",
            )
            return 0, output.to_hook_response_dict()
        return 0, {}

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
