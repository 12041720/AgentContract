"""Vendor-neutral Agent/Tool runtime wrapper coordinating constraints, tracing, and evidence."""

from collections.abc import Iterable, Mapping, Sequence
import inspect
import time
from typing import Any, Callable

from agentcontract.common.immutable import FrozenDict
from agentcontract.constraints.ledger import ConstraintLedger
from agentcontract.constraints.models import Constraint
from agentcontract.evidence.gate import EvidenceGate
from agentcontract.evidence.models import Claim
from agentcontract.guard.engine import SpecGuard
from agentcontract.guard.models import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
)
from agentcontract.runtime.exceptions import (
    RuntimeValidationError,
    ToolExecutionError,
)
from agentcontract.runtime.models import (
    IdGenerator,
    RuntimeExecutionResult,
    ToolExecutionOutcome,
    ToolExecutor,
    VerificationResult,
)
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    TracePointer,
    _freeze_trace_value,
)
from agentcontract.trace.store import TraceStore


class AgentContractRuntime:
    """Vendor-neutral synchronous runtime wrapper executing the contract lifecycle:

    Action
      -> SpecGuard pre-check
      -> ALLOW/WARN/BLOCK
      -> Tool execution only when permitted
      -> ToolCall / ToolResult trace recording
      -> SpecGuard post-check
      -> EvidenceGate verification of completion claims
    """

    def __init__(
        self,
        ledger: ConstraintLedger | None = None,
        guard: SpecGuard | None = None,
        trace_store: TraceStore | None = None,
        evidence_gate: EvidenceGate | None = None,
        trace_id: str | None = None,
        session_id: str | None = None,
        id_generator: IdGenerator | Callable[[str], str] | None = None,
        record_all_guard_decisions: bool = False,
    ) -> None:
        self._ledger = ledger if ledger is not None else ConstraintLedger()
        self._guard = guard if guard is not None else SpecGuard(ledger=self._ledger)
        self._trace_store = trace_store if trace_store is not None else TraceStore()
        self._evidence_gate = evidence_gate if evidence_gate is not None else EvidenceGate()

        # Identifier management
        if id_generator is None:
            self._id_gen = IdGenerator()
        elif isinstance(id_generator, IdGenerator):
            self._id_gen = id_generator
        elif callable(id_generator):
            # Adapt generic callable to IdGenerator interface
            fn = id_generator

            class _CallableAdapter:
                def new_id(self, category: str = "id") -> str:
                    return fn(category)

                def new_event_id(self) -> str:
                    return fn("evt")

                def new_call_id(self) -> str:
                    return fn("call")

                def new_trace_id(self) -> str:
                    return fn("trace")

                def new_session_id(self) -> str:
                    return fn("session")

            self._id_gen = _CallableAdapter()  # type: ignore[assignment]
        else:
            raise RuntimeValidationError(f"Invalid id_generator type: {type(id_generator).__name__}")

        self._trace_id = trace_id.strip() if (trace_id and trace_id.strip()) else self._id_gen.new_trace_id()
        self._session_id = session_id.strip() if (session_id and session_id.strip()) else None
        self._record_all_guard_decisions = record_all_guard_decisions

    @property
    def ledger(self) -> ConstraintLedger:
        """Active constraint ledger."""
        return self._ledger

    @property
    def guard(self) -> SpecGuard:
        """Validation engine instance."""
        return self._guard

    @property
    def trace_store(self) -> TraceStore:
        """Trace store recording execution history."""
        return self._trace_store

    @property
    def evidence_gate(self) -> EvidenceGate:
        """Evidence verification gate."""
        return self._evidence_gate

    @property
    def trace_id(self) -> str:
        """Current trace identifier."""
        return self._trace_id

    @property
    def session_id(self) -> str | None:
        """Optional session identifier."""
        return self._session_id

    def add_constraint(self, constraint: Constraint) -> Constraint:
        """Register a constraint in the runtime's ledger."""
        return self._ledger.add(constraint)

    def add_constraints(self, constraints: Iterable[Constraint]) -> tuple[Constraint, ...]:
        """Register multiple constraints in the runtime's ledger."""
        added = []
        for c in constraints:
            added.append(self._ledger.add(c))
        return tuple(added)

    def _next_sequence(self) -> int:
        """Deterministically determine the next monotonic sequence number for the current trace."""
        events = self._trace_store.list_events(self._trace_id)
        if not events:
            return 0
        return events[-1].sequence + 1

    def execute(
        self,
        action: Action | None = None,
        executor: ToolExecutor | Callable[..., Any] | None = None,
        *,
        tool_name: str | None = None,
        action_kind: ActionKind = ActionKind.GENERIC,
        payload: Any = None,
        target_path: str | None = None,
        paths: Sequence[str] = (),
        call_id: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> RuntimeExecutionResult:
        """Execute the product lifecycle for a proposed agent action.

        1. SpecGuard pre-check.
        2. If BLOCK: executor is NOT invoked; guard decision recorded in trace; returns blocked result.
        3. If WARN or ALLOW: tool executor is invoked exactly once; ToolCall and ToolResult appended.
        4. SpecGuard post-check on observed execution effects.
        5. Returns structured RuntimeExecutionResult with full provenance.
        """
        # 1. Normalize Action
        if action is None:
            if tool_name is None and not paths and target_path is None and payload is None:
                raise RuntimeValidationError(
                    "Either an Action instance or action parameters (tool_name, payload, paths, etc.) must be provided."
                )
            action = Action(
                tool_name=tool_name,
                action_kind=action_kind,
                payload=payload,
                target_path=target_path,
                paths=tuple(paths),
                context=FrozenDict(context or {}),
            )

        if executor is None:
            raise RuntimeValidationError("Tool executor must be provided.")

        # 2. Pre-action validation with SpecGuard
        pre_decision = self._guard.evaluate(
            action=action,
            ledger=self._ledger,
            trace_pointer=action.trace_pointer,
        )

        # 3. Handle BLOCK: do not invoke executor
        if pre_decision.is_blocked:
            parent_id = (
                action.trace_pointer.event_id
                if (
                    action.trace_pointer
                    and action.trace_pointer.trace_id == self._trace_id
                    and action.trace_pointer.event_id in self._trace_store
                )
                else None
            )
            guard_event = TraceEvent(
                event_id=self._id_gen.new_event_id(),
                trace_id=self._trace_id,
                session_id=self._session_id,
                sequence=self._next_sequence(),
                actor=ActorKind.GUARD,
                event_kind=EventKind.GUARD_DECISION,
                parent_id=parent_id,
                payload=_freeze_trace_value(pre_decision.model_dump(mode="json")),
                metadata=FrozenDict({"phase": "pre_action", "decision": DecisionKind.BLOCK.value}),
            )
            self._trace_store.append(guard_event)

            return RuntimeExecutionResult(
                action=action,
                pre_decision=pre_decision,
                executed=False,
                tool_call=None,
                tool_result=None,
                post_decision=None,
                pre_guard_event_pointer=guard_event.to_pointer(),
                tool_call_event_pointer=None,
                tool_result_event_pointer=None,
                post_guard_event_pointer=None,
            )

        # Optional pre-action guard event if record_all_guard_decisions is True
        pre_guard_pointer: TracePointer | None = None
        if self._record_all_guard_decisions:
            parent_id = (
                action.trace_pointer.event_id
                if (
                    action.trace_pointer
                    and action.trace_pointer.trace_id == self._trace_id
                    and action.trace_pointer.event_id in self._trace_store
                )
                else None
            )
            pre_guard_event = TraceEvent(
                event_id=self._id_gen.new_event_id(),
                trace_id=self._trace_id,
                session_id=self._session_id,
                sequence=self._next_sequence(),
                actor=ActorKind.GUARD,
                event_kind=EventKind.GUARD_DECISION,
                parent_id=parent_id,
                payload=_freeze_trace_value(pre_decision.model_dump(mode="json")),
                metadata=FrozenDict({"phase": "pre_action", "decision": pre_decision.decision.value}),
            )
            self._trace_store.append(pre_guard_event)
            pre_guard_pointer = pre_guard_event.to_pointer()

        # 4. Prepare ToolCall
        cid = (
            call_id
            or (str(action.context.get("call_id")) if "call_id" in action.context else None)
            or self._id_gen.new_call_id()
        )
        if isinstance(action.payload, Mapping):
            tc_args = dict(action.payload)
        elif action.payload is not None:
            tc_args = {"payload": action.payload}
        else:
            tc_args = {}

        derived_tool_name = action.tool_name or action.operation or action.action_kind.value.lower()
        tool_call = ToolCall(
            call_id=str(cid),
            tool_name=derived_tool_name,
            arguments=FrozenDict(tc_args),
        )

        call_parent_id = (
            pre_guard_pointer.event_id
            if pre_guard_pointer is not None
            else (
                action.trace_pointer.event_id
                if (
                    action.trace_pointer
                    and action.trace_pointer.trace_id == self._trace_id
                    and action.trace_pointer.event_id in self._trace_store
                )
                else None
            )
        )
        call_event = TraceEvent(
            event_id=self._id_gen.new_event_id(),
            trace_id=self._trace_id,
            session_id=self._session_id,
            sequence=self._next_sequence(),
            actor=ActorKind.AGENT,
            event_kind=EventKind.TOOL_CALL,
            parent_id=call_parent_id,
            payload=tool_call,
            metadata=action.context,
        )
        self._trace_store.append(call_event)

        # 5. Invoke tool executor EXACTLY ONCE
        start_time = time.perf_counter()
        try:
            raw_outcome = self._invoke_executor(executor, action, tool_call)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            outcome = self._normalize_outcome(raw_outcome, default_duration_ms=duration_ms, action=action)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_str = f"{type(exc).__name__}: {str(exc)}" if str(exc) else type(exc).__name__
            outcome = ToolExecutionOutcome(
                status=ToolResultStatus.ERROR,
                error=err_str,
                output=None,
                duration_ms=duration_ms,
            )

        # 6. Append TOOL_RESULT
        tool_result = ToolResult(
            call_id=tool_call.call_id,
            status=outcome.status,
            output=outcome.output,
            error=outcome.error,
            exit_code=outcome.exit_code,
            duration_ms=outcome.duration_ms,
            metadata=outcome.metadata,
        )
        result_event = TraceEvent(
            event_id=self._id_gen.new_event_id(),
            trace_id=self._trace_id,
            session_id=self._session_id,
            sequence=self._next_sequence(),
            actor=ActorKind.TOOL,
            event_kind=EventKind.TOOL_RESULT,
            parent_id=call_event.event_id,
            payload=tool_result,
            metadata=outcome.metadata,
        )
        self._trace_store.append(result_event)

        # 7. Post-action SpecGuard validation
        obs = ActionObservation.from_tool_result(
            tool_result=tool_result,
            changed_paths=outcome.changed_paths,
            accessed_paths=outcome.accessed_paths,
            tool_name=outcome.tool_name or action.tool_name,
            action_kind=outcome.action_kind or action.action_kind,
            trace_pointer=result_event.to_pointer(),
            context=outcome.metadata,
        )
        post_decision = self._guard.evaluate_post_action(
            action=action,
            observation=obs,
            ledger=self._ledger,
            trace_pointer=result_event.to_pointer(),
        )

        post_guard_pointer: TracePointer | None = None
        if post_decision.is_blocked or self._record_all_guard_decisions:
            post_guard_event = TraceEvent(
                event_id=self._id_gen.new_event_id(),
                trace_id=self._trace_id,
                session_id=self._session_id,
                sequence=self._next_sequence(),
                actor=ActorKind.GUARD,
                event_kind=EventKind.GUARD_DECISION,
                parent_id=result_event.event_id,
                payload=_freeze_trace_value(post_decision.model_dump(mode="json")),
                metadata=FrozenDict({"phase": "post_action", "decision": post_decision.decision.value}),
            )
            self._trace_store.append(post_guard_event)
            post_guard_pointer = post_guard_event.to_pointer()

        return RuntimeExecutionResult(
            action=action,
            pre_decision=pre_decision,
            executed=True,
            tool_call=tool_call,
            tool_result=tool_result,
            post_decision=post_decision,
            pre_guard_event_pointer=pre_guard_pointer,
            tool_call_event_pointer=call_event.to_pointer(),
            tool_result_event_pointer=result_event.to_pointer(),
            post_guard_event_pointer=post_guard_pointer,
        )

    def verify_claims(
        self,
        claims: Iterable[Claim] | Claim,
    ) -> VerificationResult:
        """Verify one or more completion claims against the runtime's TraceStore using EvidenceGate."""
        if isinstance(claims, Claim):
            claims_seq = [claims]
        else:
            claims_seq = list(claims)
        evaluations = self._evidence_gate.evaluate_many(claims_seq, self._trace_store)
        return VerificationResult(evaluations=evaluations)

    @staticmethod
    def _invoke_executor(executor: Any, action: Action, tool_call: ToolCall) -> Any:
        """Invoke tool executor handling flexible parameter signatures."""
        if not callable(executor):
            raise ToolExecutionError(f"Executor '{executor}' is not callable.")
        try:
            sig = inspect.signature(executor)
            params = list(sig.parameters.values())
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            if has_varargs or len(params) >= 2:
                return executor(action, tool_call)
            elif len(params) == 1:
                p_name = params[0].name.lower()
                if "call" in p_name:
                    return executor(tool_call)
                return executor(action)
            else:
                return executor()
        except (ValueError, TypeError):
            try:
                return executor(action, tool_call)
            except TypeError:
                try:
                    return executor(action)
                except TypeError:
                    return executor()

    @staticmethod
    def _normalize_outcome(
        raw: Any,
        default_duration_ms: float | None = None,
        action: Action | None = None,
    ) -> ToolExecutionOutcome:
        """Normalize raw return value of a tool executor into ToolExecutionOutcome."""
        if isinstance(raw, ToolExecutionOutcome):
            if raw.duration_ms is None and default_duration_ms is not None:
                return raw.model_copy(update={"duration_ms": default_duration_ms})
            return raw

        if isinstance(raw, ToolResult):
            return ToolExecutionOutcome(
                status=raw.status,
                output=raw.output,
                error=raw.error,
                exit_code=raw.exit_code,
                duration_ms=raw.duration_ms or default_duration_ms,
                metadata=raw.metadata,
            )

        if isinstance(raw, Mapping):
            status_raw = raw.get("status", ToolResultStatus.SUCCESS)
            if isinstance(status_raw, str):
                try:
                    status = ToolResultStatus(status_raw)
                except ValueError:
                    status = ToolResultStatus.ERROR
            else:
                status = status_raw

            exit_code = raw.get("exit_code")
            error = raw.get("error")
            if exit_code is not None and exit_code != 0 and "status" not in raw:
                status = ToolResultStatus.ERROR
            if error and "status" not in raw:
                status = ToolResultStatus.ERROR

            if "output" in raw:
                output = raw["output"]
            else:
                control_keys = {
                    "status",
                    "error",
                    "exit_code",
                    "duration_ms",
                    "metadata",
                    "changed_paths",
                    "accessed_paths",
                    "action_kind",
                    "target_type",
                    "tool_name",
                }
                remaining = {k: v for k, v in raw.items() if k not in control_keys}
                output = remaining if remaining else None

            return ToolExecutionOutcome(
                status=status,
                output=output,
                error=error,
                exit_code=exit_code,
                duration_ms=raw.get("duration_ms", default_duration_ms),
                metadata=raw.get("metadata", {}),
                changed_paths=raw.get("changed_paths", ()),
                accessed_paths=raw.get("accessed_paths", ()),
                action_kind=raw.get("action_kind"),
                target_type=raw.get("target_type"),
                tool_name=raw.get("tool_name"),
            )


        if isinstance(raw, int) and action is not None and action.action_kind == ActionKind.COMMAND_EXEC:
            status = ToolResultStatus.SUCCESS if raw == 0 else ToolResultStatus.ERROR
            return ToolExecutionOutcome(
                status=status,
                output=str(raw),
                exit_code=raw,
                duration_ms=default_duration_ms,
            )

        return ToolExecutionOutcome(
            status=ToolResultStatus.SUCCESS,
            output=raw,
            duration_ms=default_duration_ms,
        )
