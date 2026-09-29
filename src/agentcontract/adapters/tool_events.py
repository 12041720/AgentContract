"""External tool event adapters and normalization protocols."""

from collections.abc import Mapping, Sequence
import json
from typing import Any, Protocol, runtime_checkable

from agentcontract.adapters.exceptions import AdapterValidationError
from agentcontract.common.immutable import FrozenDict
from agentcontract.guard.models import Action, ActionKind, ActionObservation
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.trace.exceptions import TraceValidationError
from agentcontract.trace.models import (
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TracePointer,
)


@runtime_checkable
class ExternalToolCallRecord(Protocol):
    """Protocol representing an external tool call invocation."""

    call_id: str
    tool_name: str
    arguments: Mapping[str, Any]


@runtime_checkable
class ExternalToolResultRecord(Protocol):
    """Protocol representing an external tool execution result."""

    call_id: str
    output: Any


def _validate_path_sequence(paths: Any, field_name: str) -> tuple[str, ...]:
    """Strictly validate that paths is an ordered sequence (list or tuple) of non-empty strings.

    Rejects sets, frozensets, non-sequences, bare strings, and elements that are not instances of str
    (such as int, bool, dict, list, float, or custom objects). Coercion via str() is forbidden.
    """
    if paths is None:
        return ()
    if isinstance(paths, (set, frozenset)):
        raise AdapterValidationError(f"{field_name} must be an ordered sequence (list or tuple), not a set/frozenset.")
    if not isinstance(paths, (list, tuple)):
        raise AdapterValidationError(
            f"{field_name} must be an ordered list or tuple of strings, got {type(paths).__name__}."
        )

    result: list[str] = []
    for idx, item in enumerate(paths):
        if not isinstance(item, str):
            raise AdapterValidationError(
                f"{field_name} items must be strings; item at index {idx} has invalid type '{type(item).__name__}'."
            )
        s = item.strip()
        if not s:
            raise AdapterValidationError(f"{field_name} item at index {idx} cannot be empty or blank.")
        if s not in result:
            result.append(s)
    return tuple(result)


class ToolEventAdapter:
    """Adapter translating external agent/tool records into AgentContract domain models."""

    @classmethod
    def to_tool_call(cls, record: Any) -> ToolCall:
        """Convert an external tool call record into a validated ToolCall model.

        Supported external formats:
        1. ToolCall instance (idempotent validation).
        2. Flat mapping: `{"call_id": "...", "tool_name": "...", "arguments": {...}}`
           or `{"id": "...", "name": "...", "arguments": {...}}`.
        3. OpenAI-style tool call:
           `{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}`.
        4. Python object with `call_id` (or `id`), `tool_name` (or `name`), and `arguments`.

        Args:
            record: External tool call record or mapping.

        Returns:
            Validated immutable ToolCall.

        Raises:
            AdapterValidationError: If record is malformed, missing required fields,
                or arguments cannot be parsed into a mapping.
        """
        if isinstance(record, ToolCall):
            return record

        if record is None:
            raise AdapterValidationError("Tool call record cannot be None.")

        call_id: str | None = None
        tool_name: str | None = None
        raw_args: Any = None

        if isinstance(record, Mapping):
            # Check for OpenAI-style nested function dict
            fn_dict = record.get("function")
            if isinstance(fn_dict, Mapping):
                tool_name = fn_dict.get("name")
                raw_args = fn_dict.get("arguments")
                call_id = record.get("id") or record.get("call_id")
            else:
                call_id = record.get("call_id") or record.get("id")
                tool_name = record.get("tool_name") or record.get("name")
                raw_args = record.get("arguments")
                if raw_args is None:
                    raw_args = record.get("args")
        elif hasattr(record, "call_id") or hasattr(record, "id"):
            call_id = getattr(record, "call_id", None) or getattr(record, "id", None)
            tool_name = getattr(record, "tool_name", None) or getattr(record, "name", None)
            raw_args = getattr(record, "arguments", None) or getattr(record, "args", None)
            if hasattr(record, "function"):
                fn = getattr(record, "function")
                if hasattr(fn, "name"):
                    tool_name = getattr(fn, "name")
                if hasattr(fn, "arguments"):
                    raw_args = getattr(fn, "arguments")
        else:
            raise AdapterValidationError(
                f"Unsupported tool call record type: '{type(record).__name__}'."
            )

        if not call_id or not isinstance(call_id, str) or not call_id.strip():
            raise AdapterValidationError("Tool call record must provide a non-empty string 'call_id' or 'id'.")

        if not tool_name or not isinstance(tool_name, str) or not tool_name.strip():
            raise AdapterValidationError("Tool call record must provide a non-empty string 'tool_name' or 'name'.")

        # Normalize arguments
        parsed_args: Mapping[str, Any]
        if raw_args is None:
            parsed_args = {}
        elif isinstance(raw_args, Mapping):
            parsed_args = raw_args
        elif isinstance(raw_args, str):
            stripped = raw_args.strip()
            if not stripped:
                parsed_args = {}
            else:
                try:
                    loaded = json.loads(stripped)
                except Exception as err:
                    raise AdapterValidationError(
                        f"Failed to parse JSON string arguments for tool '{tool_name}': {err}"
                    ) from err
                if not isinstance(loaded, Mapping):
                    raise AdapterValidationError(
                        f"Tool arguments must decode to a JSON object (mapping), got {type(loaded).__name__}."
                    )
                parsed_args = loaded
        else:
            raise AdapterValidationError(
                f"Tool arguments must be a mapping or JSON string, got {type(raw_args).__name__}."
            )

        try:
            return ToolCall(
                call_id=call_id.strip(),
                tool_name=tool_name.strip(),
                arguments=parsed_args,
            )
        except TraceValidationError as err:
            raise AdapterValidationError(f"Invalid tool call data: {err}") from err

    @classmethod
    def to_action(
        cls,
        record: Any,
        *,
        action_kind: ActionKind | None = None,
        target_path: str | None = None,
        paths: Sequence[str] = (),
        target_type: str | None = None,
        operation: str | None = None,
        context: Mapping[str, Any] | None = None,
        trace_pointer: TracePointer | None = None,
    ) -> Action:
        """Convert an external tool call record into a validated Action for SpecGuard evaluation.

        Args:
            record: External tool call record or mapping.
            action_kind: Optional explicit action kind; inferred if omitted.
            target_path: Optional explicit primary resource path.
            paths: Optional explicit resource paths sequence.
            target_type: Optional target resource category.
            operation: Optional verb or operation name.
            context: Optional contextual metadata for policy evaluation.
            trace_pointer: Optional link to a recorded trace event.

        Returns:
            Validated immutable Action.

        Raises:
            AdapterValidationError: If record is invalid, paths is not an ordered sequence of strings,
                or items are non-strings.
        """
        validated_paths = _validate_path_sequence(paths, "paths")

        tool_call = cls.to_tool_call(record)

        # Infer target_path from arguments if not explicitly supplied
        effective_target_path = target_path
        if effective_target_path is None:
            args = tool_call.arguments
            for key in ("path", "target_path", "file_path", "file", "filepath", "resource_path"):
                val = args.get(key)
                if isinstance(val, str) and val.strip():
                    effective_target_path = val.strip()
                    break

        effective_paths: tuple[str, ...]
        if validated_paths:
            effective_paths = validated_paths
        elif effective_target_path:
            effective_paths = (effective_target_path,)
        else:
            effective_paths = ()

        # Infer action kind if not explicitly supplied
        effective_kind = action_kind
        if effective_kind is None:
            tname = tool_call.tool_name.lower()
            if any(k in tname for k in ("write", "create", "append", "save")):
                effective_kind = ActionKind.FILE_WRITE
            elif any(k in tname for k in ("delete", "remove", "unlink")):
                effective_kind = ActionKind.FILE_DELETE
            elif any(k in tname for k in ("read", "load", "cat", "view")):
                effective_kind = ActionKind.FILE_READ
            elif any(k in tname for k in ("command", "exec", "shell", "bash", "run")):
                effective_kind = ActionKind.COMMAND_EXEC
            else:
                effective_kind = ActionKind.TOOL_CALL

        return Action.from_tool_call(
            tool_call=tool_call,
            action_kind=effective_kind,
            target_path=effective_target_path,
            paths=effective_paths,
            target_type=target_type,
            operation=operation,
            trace_pointer=trace_pointer,
            context=context,
        )

    @classmethod
    def to_tool_result(cls, record: Any) -> ToolResult:
        """Convert an external tool result record into a validated ToolResult model.

        Supported external formats:
        1. ToolResult instance (idempotent validation).
        2. Flat mapping: `{"call_id": "...", "status": "...", "output": ..., "error": ...}`.
        3. OpenAI-style tool message: `{"role": "tool", "tool_call_id": "...", "content": "..."}`.
        4. Python object with `call_id` / `tool_call_id`, `output` / `content`, etc.

        Args:
            record: External tool result record or mapping.

        Returns:
            Validated immutable ToolResult.

        Raises:
            AdapterValidationError: If record is malformed, missing required call_id,
                or contains unknown status values or unsupported durable types.
        """
        if isinstance(record, ToolResult):
            return record

        if record is None:
            raise AdapterValidationError("Tool result record cannot be None.")

        call_id: str | None = None
        raw_status: Any = None
        output: Any = None
        error: str | None = None
        exit_code: int | None = None
        duration_ms: float | None = None
        metadata: Mapping[str, Any] = {}

        if isinstance(record, Mapping):
            call_id = record.get("call_id") or record.get("tool_call_id") or record.get("id")
            raw_status = record.get("status")
            output = record.get("output")
            if output is None and "content" in record:
                output = record.get("content")
            elif output is None and "result" in record:
                output = record.get("result")
            error = record.get("error")
            exit_code = record.get("exit_code")
            duration_ms = record.get("duration_ms")
            meta = record.get("metadata")
            if isinstance(meta, Mapping):
                metadata = meta
        elif hasattr(record, "call_id") or hasattr(record, "tool_call_id") or hasattr(record, "id"):
            call_id = (
                getattr(record, "call_id", None)
                or getattr(record, "tool_call_id", None)
                or getattr(record, "id", None)
            )
            raw_status = getattr(record, "status", None)
            output = getattr(record, "output", None)
            if output is None and hasattr(record, "content"):
                output = getattr(record, "content")
            elif output is None and hasattr(record, "result"):
                output = getattr(record, "result")
            error = getattr(record, "error", None)
            exit_code = getattr(record, "exit_code", None)
            duration_ms = getattr(record, "duration_ms", None)
            meta = getattr(record, "metadata", None)
            if isinstance(meta, Mapping):
                metadata = meta
        else:
            raise AdapterValidationError(
                f"Unsupported tool result record type: '{type(record).__name__}'."
            )

        if not call_id or not isinstance(call_id, str) or not call_id.strip():
            raise AdapterValidationError("Tool result record must provide a non-empty string 'call_id' or 'tool_call_id'.")

        # Status normalization
        status: ToolResultStatus
        if raw_status is None:
            if error and str(error).strip():
                status = ToolResultStatus.ERROR
            elif exit_code is not None and exit_code != 0:
                status = ToolResultStatus.ERROR
            else:
                status = ToolResultStatus.SUCCESS
        elif isinstance(raw_status, ToolResultStatus):
            status = raw_status
        elif isinstance(raw_status, str):
            s_upper = raw_status.strip().upper()
            if s_upper in ("SUCCESS", "OK", "0"):
                status = ToolResultStatus.SUCCESS
            elif s_upper in ("ERROR", "FAILED", "FAILURE", "ERR", "1"):
                status = ToolResultStatus.ERROR
            elif s_upper in ("TIMEOUT", "TIMED_OUT"):
                status = ToolResultStatus.TIMEOUT
            elif s_upper in ("CANCELLED", "CANCELED"):
                status = ToolResultStatus.CANCELLED
            else:
                raise AdapterValidationError(f"Unknown or unsupported tool result status: '{raw_status}'.")
        elif isinstance(raw_status, int):
            status = ToolResultStatus.SUCCESS if raw_status == 0 else ToolResultStatus.ERROR
        else:
            raise AdapterValidationError(f"Invalid status value type: {type(raw_status).__name__}.")

        # If output is a JSON string, attempt decoding to structured mapping/sequence
        normalized_output = output
        if isinstance(output, str):
            stripped_out = output.strip()
            if (stripped_out.startswith("{") and stripped_out.endswith("}")) or (
                stripped_out.startswith("[") and stripped_out.endswith("]")
            ):
                try:
                    normalized_output = json.loads(stripped_out)
                except Exception:
                    normalized_output = output

        try:
            return ToolResult(
                call_id=call_id.strip(),
                status=status,
                output=normalized_output,
                error=str(error).strip() if error else None,
                exit_code=int(exit_code) if exit_code is not None else None,
                duration_ms=float(duration_ms) if duration_ms is not None else None,
                metadata=FrozenDict(metadata),
            )
        except (TraceValidationError, ValueError) as err:
            raise AdapterValidationError(f"Invalid tool result data: {err}") from err

    @classmethod
    def to_tool_execution_outcome(
        cls,
        record: Any,
        *,
        changed_paths: Sequence[str] = (),
        accessed_paths: Sequence[str] = (),
        action_kind: ActionKind | None = None,
        target_type: str | None = None,
        tool_name: str | None = None,
    ) -> ToolExecutionOutcome:
        """Convert an external tool result record into a validated ToolExecutionOutcome model.

        Args:
            record: External tool result record or mapping.
            changed_paths: Resource paths modified during execution.
            accessed_paths: Resource paths read during execution.
            action_kind: Refined action category.
            target_type: Target resource category.
            tool_name: Actual tool name executed.

        Returns:
            Validated immutable ToolExecutionOutcome.

        Raises:
            AdapterValidationError: If record is malformed, path sequences are sets/frozensets,
                or path items are non-strings.
        """
        validated_changed = _validate_path_sequence(changed_paths, "changed_paths")
        validated_accessed = _validate_path_sequence(accessed_paths, "accessed_paths")

        tool_result = cls.to_tool_result(record)

        # Merge path records if present in external mapping
        merged_changed = list(validated_changed)
        merged_accessed = list(validated_accessed)
        if isinstance(record, Mapping):
            ext_changed = record.get("changed_paths")
            if ext_changed is not None:
                record_changed = _validate_path_sequence(ext_changed, "changed_paths in record")
                for p in record_changed:
                    if p not in merged_changed:
                        merged_changed.append(p)

            ext_accessed = record.get("accessed_paths")
            if ext_accessed is not None:
                record_accessed = _validate_path_sequence(ext_accessed, "accessed_paths in record")
                for p in record_accessed:
                    if p not in merged_accessed:
                        merged_accessed.append(p)

        return ToolExecutionOutcome.from_tool_result(
            tool_result,
            changed_paths=tuple(merged_changed),
            accessed_paths=tuple(merged_accessed),
            action_kind=action_kind,
            target_type=target_type,
            tool_name=tool_name,
        )

    @classmethod
    def to_action_observation(
        cls,
        record: Any,
        *,
        changed_paths: Sequence[str] = (),
        accessed_paths: Sequence[str] = (),
        action_kind: ActionKind | None = None,
        target_type: str | None = None,
        tool_name: str | None = None,
        trace_pointer: TracePointer | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> ActionObservation:
        """Convert an external tool result record into an ActionObservation for post-action validation.

        Args:
            record: External tool result record or mapping.
            changed_paths: Resource paths modified during execution.
            accessed_paths: Resource paths read during execution.
            action_kind: Action category.
            target_type: Target resource category.
            tool_name: Actual tool executed.
            trace_pointer: Optional link to result trace event.
            context: Observation context metadata.

        Returns:
            Validated immutable ActionObservation.

        Raises:
            AdapterValidationError: If record is malformed, path sequences are sets/frozensets,
                or path items are non-strings.
        """
        outcome = cls.to_tool_execution_outcome(
            record,
            changed_paths=changed_paths,
            accessed_paths=accessed_paths,
            action_kind=action_kind,
            target_type=target_type,
            tool_name=tool_name,
        )

        return ActionObservation(
            tool_name=outcome.tool_name or tool_name,
            action_kind=outcome.action_kind or action_kind,
            changed_paths=outcome.changed_paths,
            accessed_paths=outcome.accessed_paths,
            target_type=outcome.target_type or target_type,
            output=outcome.output,
            exit_code=outcome.exit_code,
            context=FrozenDict(context or outcome.metadata),
            trace_pointer=trace_pointer,
        )
