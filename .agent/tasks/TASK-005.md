# TASK-005 — Agent/Tool Runtime Wrapper and End-to-End Demo

**Status:** CHANGES_REQUESTED  
**Milestone:** M2 — Working AgentContract demo  
**Owner:** Execution agent  
**Work branch:** `task/TASK-005-runtime-wrapper`  
**Main-agent review:** second-round narrow fixes requested

## Objective

Connect the accepted Constraint Ledger, SpecGuard, TraceStore, and EvidenceGate into one synchronous vendor-neutral runtime wrapper.

The runtime must demonstrate the product loop:

```text
proposed action
  -> SpecGuard pre-check
  -> ALLOW/WARN/BLOCK
  -> tool execution only when permitted
  -> ToolCall/ToolResult trace recording
  -> SpecGuard post-check
  -> typed completion claims
  -> EvidenceGate verification
```

This is product/runtime functionality. Do not add development-agent coordination logic.

## Required runtime concepts

Implement under `src/agentcontract/runtime/` at minimum:

- runtime/session object, e.g. `AgentContractRuntime`;
- vendor-neutral `ToolExecutor` protocol/callable abstraction;
- execution result model aggregating:
  - proposed Action;
  - pre-action GuardDecision;
  - whether tool execution occurred;
  - ToolCall / ToolResult provenance;
  - post-action GuardDecision when applicable;
  - trace pointers;
- completion verification result containing ClaimEvaluations;
- deterministic trace/session/event/call identity generation or explicit injectable IDs suitable for tests.

No LLM calls.

## Execution semantics

### Pre-action

1. Normalize/accept an `Action`.
2. Run SpecGuard before the tool.
3. If decision is `BLOCK`:
   - do not call the tool executor;
   - record an observable guard decision/event in the trace;
   - return a blocked execution result.
4. If `WARN` or `ALLOW`:
   - tool execution may proceed;
   - preserve the warning in the returned result/provenance.

### Tool execution and tracing

For executed actions:

1. append a TOOL_CALL TraceEvent before execution;
2. invoke the supplied tool executor exactly once;
3. convert its structured outcome into ToolResult;
4. append TOOL_RESULT with matching call_id and correct parent;
5. ERROR/TIMEOUT/CANCELLED outcomes must remain distinguishable;
6. do not fabricate success when executor raises/fails.

The wrapper must not assume every tool is a shell command.

### Post-action

After a ToolResult:

- build/accept ActionObservation from structured executor outcome;
- run SpecGuard post-action validation;
- return the post decision with exact trace provenance;
- post-action BLOCK means a violation was observed after execution; it cannot retroactively claim the tool did not execute.

### Completion verification

Provide an API equivalent to:

```python
evaluations = runtime.verify_claims(claims)
```

using the runtime's TraceStore and EvidenceGate.

Claims must follow TASK-004 deterministic rules. Do not extract claims from prose in TASK-005.

## Tool executor contract

Keep it small and explicit. A tool executor should return a structured outcome sufficient to construct:

- status: SUCCESS / ERROR / TIMEOUT / CANCELLED;
- output;
- error;
- exit_code;
- duration/metadata when present;
- optional observed changed/accessed paths or action category for post-action validation.

If executor raises an exception, runtime must convert it to an ERROR ToolResult and preserve a safe error string; it must still append the result event.

## End-to-end demo/tests

Create deterministic demo/tests proving the full loop.

Required scenarios:

1. **Pre-action hard block**
   - hard DENY constraint forbids a write/tool/action;
   - runtime returns BLOCK;
   - executor invocation count remains zero;
   - guard decision is traceable.

2. **Allowed successful execution**
   - pre-check ALLOW;
   - exactly one ToolCall and one correlated ToolResult;
   - result SUCCESS;
   - post-check ALLOW;
   - TOOL_SUCCEEDED / COMMAND_EXITED_ZERO claim verifies when appropriately scoped.

3. **Warning does not silently become block**
   - SOFT violation -> WARN;
   - tool executes exactly once;
   - warning retained.

4. **Executor exception/failure**
   - exception becomes ERROR ToolResult;
   - result event is recorded;
   - success claim becomes CONTRADICTED.

5. **Post-action violation**
   - proposed action passes pre-check;
   - observed changed/accessed path violates a hard constraint;
   - tool did execute;
   - post decision BLOCK;
   - provenance points to actual observed execution.

6. **Unsupported completion claim**
   - GENERIC or under-evidenced claim remains UNVERIFIED.

7. **Trace integrity**
   - sequence/event/call parent identities remain valid across multiple runtime executions.

8. **Serialization**
   - public runtime result models round-trip through JSON where they are intended to be durable.

## Runtime ownership

A runtime instance should own or receive:

- ConstraintLedger;
- SpecGuard;
- TraceStore;
- EvidenceGate;
- trace_id/session_id.

Allow dependency injection for tests. Do not introduce database/network persistence.

## Out of scope

Do not implement:

- autonomous planning/agent loop;
- LLM requirement extraction;
- LLM claim extraction;
- Codex/Claude/OpenHands adapters;
- MCP middleware;
- OpenTelemetry exporters;
- retries/queues/distributed execution;
- CLI/FastAPI;
- benchmark metrics;
- production sandboxing.

## Acceptance criteria

- [x] synchronous vendor-neutral runtime wrapper exists;
- [x] BLOCK prevents executor invocation;
- [x] WARN allows execution and remains visible;
- [x] executed calls produce correlated ToolCall/ToolResult trace events;
- [x] executor exceptions become ERROR evidence rather than disappearing;
- [x] post-action observations are checked by SpecGuard;
- [x] runtime can verify typed claims through EvidenceGate;
- [x] no success is inferred from agent text;
- [x] full E2E tests cover block/allow/warn/failure/post-violation/claim verification;
- [x] TASK-001 through TASK-004 tests remain green;
- [x] no LLM/network/vendor dependency;
- [x] local Python 3.12.9 only.

## Environment

```bash
python --version
python -m pytest -v
```

Do not install another Python interpreter for compatibility testing.

## Executor Report

> Execution agent fills this section.

**Implementation summary:**  
- **Environment Baseline:** Developed and tested exclusively on the user's installed local **Python 3.12.9** baseline (`python --version` -> `Python 3.12.9`).
- **Core Runtime Architecture (`src/agentcontract/runtime/`):**
  - `AgentContractRuntime` (`session.py`): Vendor-neutral synchronous runtime wrapper coordinating the full product contract lifecycle:
    `Action -> SpecGuard pre-check -> ALLOW/WARN/BLOCK -> Tool execution only when permitted -> ToolCall + ToolResult trace -> SpecGuard post-check -> EvidenceGate verify claims`.
  - `ToolExecutionOutcome` (`models.py`): Structured executor outcome supporting status (`SUCCESS`, `ERROR`, `TIMEOUT`, `CANCELLED`), output, error, exit_code, duration_ms, metadata, changed_paths, accessed_paths, action_kind, target_type, and tool_name. Rejects unordered `set`/`frozenset` inputs for paths and freezes output/metadata.
  - `ToolExecutor` (`models.py`): `@runtime_checkable` callable protocol supporting flexible executor signatures (`(action, tool_call)`, `(action)`, `(tool_call)`, `()`).
  - `RuntimeExecutionResult` (`models.py`): Immutable, durable result aggregating proposed `Action`, pre-action `GuardDecision`, `executed` flag, correlated `ToolCall` and `ToolResult`, post-action `GuardDecision`, and trace pointers (`pre_guard_event_pointer`, `tool_call_event_pointer`, `tool_result_event_pointer`, `post_guard_event_pointer`), with convenience properties `is_blocked`, `is_post_blocked`, `is_warned`, `is_allowed`, `is_success`, `trace_pointers`.
  - `VerificationResult` (`models.py`): Immutable container for `ClaimEvaluation` sequences from `verify_claims()`, supporting iteration, length, indexing, JSON round-trip, and properties `all_verified`, `has_contradictions`, `has_unverified`, `by_claim_id`, and `get()`.
  - `IdGenerator` (`models.py`): Configurable identifier generator supporting deterministic mode for reproducible testing or unique UUID-based identifiers.
  - `AgentContractRuntimeError`, `RuntimeValidationError`, `ToolExecutionError` (`exceptions.py`): Domain-specific exception hierarchy without shadowing Python's standard `RuntimeError`.
- **Execution & Safety Semantics Enforced:**
  - `BLOCK` strictly prevents tool executor invocation (invocation count = 0), records an observable `GUARD_DECISION` trace event in `TraceStore`, and returns a blocked result.
  - `WARN` permits execution, invokes executor exactly once, and retains the warning in `pre_decision`.
  - Tool execution for permitted actions invokes the executor exactly once, appending `TOOL_CALL` trace event before invocation and correlated `TOOL_RESULT` trace event with matching `call_id` and parent linkage.
  - Executor exceptions are caught, sanitized into safe error strings, and recorded as `ERROR` `ToolResult` trace events without fabricating success.
  - **Round 2 Fix — Exactly-Once Invocation:** In `session.py`, executor arguments are pre-resolved and pre-bound via `inspect.signature(...).bind(...)` *before* calling the executor. The executor is invoked strictly once with no retry loop; an internal `TypeError` raised by the executor body is never caught as a signature-selection signal and is recorded as one `ERROR` `ToolResult`. Unsupported signatures fail before invocation (`call_count == 0`).
  - **Round 2 Fix — Post-Action `target_type`:** Extended `ActionObservation.from_tool_result()` to accept `target_type`, and passed `outcome.target_type or action.target_type` in `session.py` so that post-action constraints on `target_type` evaluate the actual observed target type.
  - **Round 3 Fix — Accurate `executed` Flag:** In `session.py`, `executed` distinguishes whether the executor function body actually ran from whether pre-invocation binding failed. When argument binding/validation fails before invocation, `executed=False`, `call_count=0`, and `post_decision=None` while recording `TOOL_CALL` and `TOOL_RESULT` (with `ERROR` status) in trace for provenance. When the executor body actually runs and raises an exception (or succeeds), `executed=True` and post-action validation proceeds.
  - **Round 3 Fix — Strict Unordered-Set Rejection in Constructors:** Updated `ToolExecutionOutcome.success()`, `ToolExecutionOutcome.from_tool_result()`, and `ActionObservation.from_tool_result()` to pass caller values through directly to model construction without calling `tuple(...)`. Passing `set` or `frozenset` to `success(changed_paths={...})` or `from_tool_result(..., changed_paths={...})` immediately raises `RuntimeValidationError` / `GuardValidationError`.
  - Post-action effects (`changed_paths`, `accessed_paths`, output, `target_type`) are converted to `ActionObservation` and validated by `SpecGuard.evaluate_post_action`; post-action `BLOCK` is recorded in trace and attached to result with exact trace provenance pointing to the executed `TOOL_RESULT`.
  - `verify_claims(claims)` validates typed claims using the runtime's `TraceStore` and `EvidenceGate`.
- **Top-Level Exports (`src/agentcontract/__init__.py`):**
  - Exported all runtime primitives: `AgentContractRuntime`, `RuntimeExecutionResult`, `VerificationResult`, `ToolExecutionOutcome`, `ToolExecutor`, `IdGenerator`, `AgentContractRuntimeError`, `RuntimeValidationError`, `ToolExecutionError`.

**Files changed:**  
- `src/agentcontract/guard/models.py` (avoided premature `tuple()` conversion in `ActionObservation.from_tool_result()` and `Action.from_trace_event()`)
- `src/agentcontract/runtime/__init__.py` (runtime package initialization and public exports)
- `src/agentcontract/runtime/exceptions.py` (runtime exception hierarchy)
- `src/agentcontract/runtime/models.py` (avoided premature `tuple()` conversion in `ToolExecutionOutcome.success()` and `from_tool_result()`)
- `src/agentcontract/runtime/session.py` (accurate `executed` flag tracking on binding failure vs body execution, wrapping action creation)
- `src/agentcontract/__init__.py` (exported runtime primitives at top level)
- `tests/runtime/__init__.py` (test package init)
- `tests/guard/test_models.py` (regression tests for `ActionObservation.from_tool_result()` rejecting sets/frozensets)
- `tests/runtime/test_models.py` (regression tests for `ToolExecutionOutcome.success()` and `from_tool_result()` rejecting sets/frozensets)
- `tests/runtime/test_runtime.py` (regression tests for `executed=False` on pre-binding failure vs `executed=True` on function body exception, and execute() path set rejection)
- `.agent/tasks/TASK-005.md` (updated acceptance criteria checklist and Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **158 passed in 1.01s** (100% pass across all milestone suites: 35 constraints + 41 trace + 27 guard + 31 evidence + 24 runtime tests).
- All 8 required scenarios verified:
  1. Pre-action hard block (executor invocation count = 0, traceable guard event)
  2. Allowed successful execution (correlated ToolCall/ToolResult, success claims verified)
  3. Warning retained without blocking (tool executes once, warning preserved)
  4. Executor failure/exception recorded as ERROR ToolResult (success claim contradicted)
  5. Post-action violation detected by SpecGuard (tool executed, post-block decision with trace provenance)
  6. Unsupported completion claims remain UNVERIFIED
  7. Trace integrity across multiple executions (strictly increasing sequence, parent linkages)
  8. JSON serialization round-trip of execution and verification results
- Round 2 & Round 3 regression tests verified:
  - `test_executor_internal_type_error_invoked_exactly_once`: counter equals 1, single `ERROR` `ToolResult` recorded.
  - `test_unsupported_signature_fails_before_execution`: counter equals 0, `res.executed is False`, `res.post_decision is None`, fails prior to invocation.
  - `test_executor_executed_flag_distinguishes_signature_failure_from_body_exception`: explicitly validates `executed=False` on signature binding failure vs `executed=True` on function body exception.
  - `test_tool_execution_outcome_rejects_unordered_sets`: verifies `success()` and `from_tool_result()` reject `set` and `frozenset` with `RuntimeValidationError`.
  - `test_unordered_sets_rejected_in_models`: verifies `ActionObservation.from_tool_result()` rejects `set` and `frozenset` with `ValidationError`.
  - `test_runtime_validation_errors`: verifies `runtime.execute(paths={"/a", "/b"})` rejects unordered sets with `RuntimeValidationError`.
  - `test_post_action_target_type_violation_blocks`: pre-action ALLOW, observed forbidden `target_type` triggers post-action BLOCK.
  - `test_flexible_executor_signatures_and_return_types`: explicitly asserts `isinstance(tc, ToolCall)` and `isinstance(act, Action)`.

**Known limitations:**  
- Runtime operates in-memory against local TraceStore; distributed queues and remote telemetry are intentionally out of scope for v0.1.
- Natural language claim extraction and prose entailment are reserved for TASK-006.

**Commit/PR:**  
- Branch: `task/TASK-005-runtime-wrapper`
- Implementation Commit SHA: `4e028fe6f98d9e6bdb57239128033031150e755e`
- Round 2 Fix Commit SHA: `77281cfaba5ca6256cfd97d9c28f7e613958ac4c`
- Round 3 Fix Commit SHA: `4f9946b074445aa2f68671f83899b7f40e718647`

**Questions/blockers:**  
- None. All review blockers resolved and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — ROUND 2 (NARROW FINAL FIXES)

**Reviewed implementation:** `77281cfaba5ca6256cfd97d9c28f7e613958ac4c`  
**Reviewed branch head/report:** `6f1d71683ee8c940e9ed95e0500c6a300ab2ae58`

**Round-1 blockers verified fixed:**
- executor internal `TypeError` no longer triggers retries;
- argument binding is resolved before invocation;
- one-argument ToolCall/Action executors are type-checked in tests;
- actual `target_type` is propagated into post-action ActionObservation;
- post-action target_type violations can now BLOCK;
- executor reports 157 tests passing on local Python 3.12.9.

### BLOCKER 1 — RuntimeExecutionResult.executed is incorrect when invocation never occurred

The new unsupported-signature regression test says:

```text
fails before execution
executor must NEVER be called
call_count == 0
```

but then asserts:

```python
res.executed is True
```

TASK-005 defines `executed` as whether tool execution actually occurred. If argument binding fails before executor invocation, this must be false.

**Required fix:**
- distinguish "tool call event was emitted / invocation was attempted to be prepared" from "executor body actually ran";
- if signature/binding validation fails before invoking executor:
  - `executed=False`;
  - executor call_count remains 0;
  - still record appropriate trace/error provenance if desired, but do not claim execution occurred;
- if executor body starts and then raises, `executed=True`.

Add/update tests for both cases.

### BLOCKER 2 — convenience constructors bypass unordered-set rejection

The model validator correctly rejects unordered `set/frozenset` for `changed_paths` / `accessed_paths`, but convenience constructors do this first:

```python
changed_paths=tuple(changed_paths)
accessed_paths=tuple(accessed_paths)
```

Therefore:

```python
ToolExecutionOutcome.success(changed_paths={"b", "a"})
```

silently accepts an unordered set and turns arbitrary iteration order into durable tuple order, bypassing the validator.

`from_tool_result()` has the same issue.

**Required fix:**
- pass caller values through unchanged so field validators enforce ordered-sequence policy, or explicitly reject set/frozenset before conversion;
- add regression tests for `success()` and `from_tool_result()` with set/frozenset inputs.

### REPORT ACCURACY

Executor Report again contains an incorrect full round-2 SHA:

```text
77281cf874744799839446d7904b7e8824128507
```

The actual remote implementation commit is:

```text
77281cfaba5ca6256cfd97d9c28f7e613958ac4c
```

Update the report with the actual pushed SHA.

**Required re-check:**
- local Python 3.12.9 only;
- `python --version`;
- `python -m pytest -v`;
- TASK-001 through TASK-004 suites remain green.

**Next instruction:**
Apply these two narrow fixes on `task/TASK-005-runtime-wrapper`. Do not start TASK-006.

