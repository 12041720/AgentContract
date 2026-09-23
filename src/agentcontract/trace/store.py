"""In-memory append-oriented trace store with strict identity and sequence integrity."""

from collections.abc import Iterable, Iterator, Mapping
import json
from typing import Any
from agentcontract.trace.exceptions import (
    DuplicateEventError,
    EventNotFoundError,
    InvalidSequenceError,
    ParentEventError,
    ToolCorrelationError,
    TraceValidationError,
)
from agentcontract.trace.models import (
    ActorKind,
    EventId,
    EventKind,
    SessionId,
    ToolCall,
    ToolCallId,
    ToolResult,
    TraceEvent,
    TraceId,
    TracePointer,
)


class TraceStore:
    """An append-oriented in-memory container for trace events.

    Enforces:
    - Unique event IDs across the entire store.
    - Strictly monotonic non-negative sequences per trace ID.
    - Valid parent event references within the same trace.
    - Tool call and tool result correlation and unique call_id usage within a trace.
    - Timezone-aware timestamps and immutable durable payloads.
    """

    def __init__(self, events: Iterable[TraceEvent] | None = None) -> None:
        self._events: list[TraceEvent] = []
        self._events_by_id: dict[EventId, TraceEvent] = {}
        self._events_by_trace: dict[TraceId, list[TraceEvent]] = {}
        self._last_sequence_by_trace: dict[TraceId, int] = {}
        self._tool_calls_by_trace: dict[TraceId, dict[ToolCallId, TraceEvent]] = {}
        self._tool_results_by_trace: dict[TraceId, dict[ToolCallId, TraceEvent]] = {}

        if events is not None:
            for event in events:
                self.append(event)

    def append(self, event: TraceEvent) -> TraceEvent:
        """Append an event to the trace store after validating all invariants."""
        if not isinstance(event, TraceEvent):
            raise TraceValidationError(f"Expected TraceEvent instance, got {type(event)}")

        # Invariant 1: Event IDs are unique within the store
        if event.event_id in self._events_by_id:
            raise DuplicateEventError(
                f"Event with id '{event.event_id}' already exists in store."
            )

        # Invariant 2 & 3: Sequence numbers are non-negative and strictly increasing within a given trace
        if event.sequence < 0:
            raise InvalidSequenceError(
                f"Sequence must be non-negative, got {event.sequence} for event '{event.event_id}'."
            )

        if event.trace_id in self._last_sequence_by_trace:
            last_seq = self._last_sequence_by_trace[event.trace_id]
            if event.sequence <= last_seq:
                raise InvalidSequenceError(
                    f"Sequence {event.sequence} is not strictly greater than previous "
                    f"sequence {last_seq} for trace '{event.trace_id}'."
                )

        # Invariant 4: Timestamps must be timezone-aware
        if event.timestamp.tzinfo is None or event.timestamp.tzinfo.utcoffset(event.timestamp) is None:
            raise TraceValidationError(
                f"Event '{event.event_id}' timestamp must be timezone-aware."
            )

        # Invariant 8: Parent-event references must refer to an already-known event in the same trace
        if event.parent_id is not None:
            if event.parent_id not in self._events_by_id:
                raise ParentEventError(
                    f"Parent event '{event.parent_id}' does not exist in store."
                )
            parent_event = self._events_by_id[event.parent_id]
            if parent_event.trace_id != event.trace_id:
                raise ParentEventError(
                    f"Parent event '{event.parent_id}' belongs to trace '{parent_event.trace_id}', "
                    f"but event '{event.event_id}' belongs to trace '{event.trace_id}'."
                )

        # Invariant 5, 6, 7: Tool call / tool result correlation
        if event.event_kind == EventKind.TOOL_CALL:
            tc = event.tool_call
            if tc is None:
                raise ToolCorrelationError(
                    f"TOOL_CALL event '{event.event_id}' is missing a valid ToolCall payload."
                )
            trace_calls = self._tool_calls_by_trace.setdefault(event.trace_id, {})
            if tc.call_id in trace_calls:
                raise ToolCorrelationError(
                    f"Duplicate ToolCallId '{tc.call_id}' already declared in trace '{event.trace_id}'."
                )
            trace_calls[tc.call_id] = event

        elif event.event_kind == EventKind.TOOL_RESULT:
            tr = event.tool_result
            if tr is None:
                raise ToolCorrelationError(
                    f"TOOL_RESULT event '{event.event_id}' is missing a valid ToolResult payload."
                )
            trace_calls = self._tool_calls_by_trace.get(event.trace_id, {})
            if tr.call_id not in trace_calls:
                # Check if it was issued in another trace for clearer error reporting
                other_trace_id = None
                for other_tid, calls in self._tool_calls_by_trace.items():
                    if other_tid != event.trace_id and tr.call_id in calls:
                        other_trace_id = other_tid
                        break
                if other_trace_id:
                    raise ToolCorrelationError(
                        f"ToolResult call_id '{tr.call_id}' belongs to trace '{other_trace_id}', "
                        f"not the current trace '{event.trace_id}'."
                    )
                raise ToolCorrelationError(
                    f"ToolResult call_id '{tr.call_id}' does not match any prior ToolCall in trace '{event.trace_id}'."
                )

            trace_results = self._tool_results_by_trace.setdefault(event.trace_id, {})
            if tr.call_id in trace_results:
                raise ToolCorrelationError(
                    f"ToolResult for call_id '{tr.call_id}' has already been recorded in trace '{event.trace_id}'."
                )
            trace_results[tr.call_id] = event

        # Commit event to store indices
        self._events.append(event)
        self._events_by_id[event.event_id] = event
        self._events_by_trace.setdefault(event.trace_id, []).append(event)
        self._last_sequence_by_trace[event.trace_id] = event.sequence
        return event

    def get(self, event_id: EventId) -> TraceEvent:
        """Retrieve an event by event_id or raise EventNotFoundError."""
        if event_id not in self._events_by_id:
            raise EventNotFoundError(f"Event with id '{event_id}' not found in store.")
        return self._events_by_id[event_id]

    def get_optional(self, event_id: EventId) -> TraceEvent | None:
        """Retrieve an event by event_id or return None if not found."""
        return self._events_by_id.get(event_id)

    def list_events(self, trace_id: TraceId | None = None) -> tuple[TraceEvent, ...]:
        """Return events in deterministic order.

        If trace_id is specified, returns events in strictly monotonic sequence order for that trace.
        Otherwise, returns all events in store append order.
        """
        if trace_id is not None:
            return tuple(self._events_by_trace.get(trace_id, []))
        return tuple(self._events)

    def filter(
        self,
        trace_id: TraceId | None = None,
        session_id: SessionId | None = None,
        event_kind: EventKind | None = None,
        actor: ActorKind | None = None,
    ) -> tuple[TraceEvent, ...]:
        """Filter events deterministically by trace, session, event kind, or actor."""
        candidates = self._events_by_trace.get(trace_id, []) if trace_id is not None else self._events
        results = [
            e
            for e in candidates
            if (session_id is None or e.session_id == session_id)
            and (event_kind is None or e.event_kind == event_kind)
            and (actor is None or e.actor == actor)
        ]
        return tuple(results)

    def create_pointer(self, event_id: EventId) -> TracePointer:
        """Create a compact TracePointer pointing to the given event."""
        event = self.get(event_id)
        return event.to_pointer()

    def resolve_pointer(self, pointer: TracePointer) -> TraceEvent:
        """Resolve a TracePointer to its referenced TraceEvent, verifying identity consistency."""
        event = self.get(pointer.event_id)
        if event.trace_id != pointer.trace_id:
            raise TraceValidationError(
                f"Pointer trace_id '{pointer.trace_id}' does not match event trace_id '{event.trace_id}'."
            )
        if pointer.session_id is not None and event.session_id != pointer.session_id:
            raise TraceValidationError(
                f"Pointer session_id '{pointer.session_id}' does not match event session_id '{event.session_id}'."
            )
        return event

    def get_tool_call(self, trace_id: TraceId, call_id: ToolCallId) -> ToolCall:
        """Retrieve the ToolCall corresponding to call_id in the given trace."""
        trace_calls = self._tool_calls_by_trace.get(trace_id, {})
        if call_id not in trace_calls:
            raise ToolCorrelationError(
                f"No ToolCall with call_id '{call_id}' found in trace '{trace_id}'."
            )
        tc = trace_calls[call_id].tool_call
        assert tc is not None
        return tc

    def get_tool_result(self, trace_id: TraceId, call_id: ToolCallId) -> ToolResult:
        """Retrieve the ToolResult corresponding to call_id in the given trace."""
        trace_results = self._tool_results_by_trace.get(trace_id, {})
        if call_id not in trace_results:
            raise ToolCorrelationError(
                f"No ToolResult with call_id '{call_id}' found in trace '{trace_id}'."
            )
        tr = trace_results[call_id].tool_result
        assert tr is not None
        return tr

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete trace store state into a dictionary."""
        return {
            "events": [event.model_dump(mode="json") for event in self._events]
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TraceStore":
        """Reconstruct a TraceStore from serialized dictionary data, validating all invariants."""
        raw_events = data.get("events", [])
        store = cls()
        for raw in raw_events:
            event = raw if isinstance(raw, TraceEvent) else TraceEvent.model_validate(raw)
            store.append(event)
        return store

    def to_json(self, **kwargs: Any) -> str:
        """Serialize the complete store to a JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, json_str: str) -> "TraceStore":
        """Reconstruct a TraceStore from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def __len__(self) -> int:
        return len(self._events)

    def __contains__(self, event_id: object) -> bool:
        return event_id in self._events_by_id

    def __iter__(self) -> Iterator[TraceEvent]:
        return iter(self._events)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TraceStore):
            return self._events == other._events
        return False
