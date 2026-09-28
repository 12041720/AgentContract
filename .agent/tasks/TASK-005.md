# TASK-005 — Agent/Tool Runtime Wrapper and End-to-End Demo

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M2 — Working AgentContract demo  
**Owner:** Execution agent  
**Work branch:** `task/TASK-005-runtime-wrapper`  
**Main-agent review:** pending

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
  - Post-action effects (`changed_paths`, `accessed_paths`, output) are converted to `ActionObservation` and validated by `SpecGuard.evaluate_post_action`; post-action `BLOCK` is recorded in trace and attached to result with exact trace provenance pointing to the executed `TOOL_RESULT`.
  - `verify_claims(claims)` validates typed claims using the runtime's `TraceStore` and `EvidenceGate`.
- **Top-Level Exports (`src/agentcontract/__init__.py`):**
  - Exported all runtime primitives: `AgentContractRuntime`, `RuntimeExecutionResult`, `VerificationResult`, `ToolExecutionOutcome`, `ToolExecutor`, `IdGenerator`, `AgentContractRuntimeError`, `RuntimeValidationError`, `ToolExecutionError`.

**Files changed:**  
- `src/agentcontract/runtime/__init__.py` (runtime package initialization and public exports)
- `src/agentcontract/runtime/exceptions.py` (runtime exception hierarchy)
- `src/agentcontract/runtime/models.py` (ToolExecutionOutcome, RuntimeExecutionResult, VerificationResult, ToolExecutor, IdGenerator)
- `src/agentcontract/runtime/session.py` (AgentContractRuntime implementation)
- `src/agentcontract/__init__.py` (exported runtime primitives at top level)
- `tests/runtime/__init__.py` (test package init)
- `tests/runtime/test_models.py` (models unit tests, container immutability, serialization round-trip)
- `tests/runtime/test_runtime.py` (full E2E integration tests for all 8 scenarios and edge cases)
- `.agent/tasks/TASK-005.md` (updated acceptance criteria checklist and Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **154 passed in 0.92s** (100% pass across all milestone suites: 35 constraints + 41 trace + 26 guard + 31 evidence + 21 runtime tests).
- All 8 required scenarios verified:
  1. Pre-action hard block (executor invocation count = 0, traceable guard event)
  2. Allowed successful execution (correlated ToolCall/ToolResult, success claims verified)
  3. Warning retained without blocking (tool executes once, warning preserved)
  4. Executor failure/exception recorded as ERROR ToolResult (success claim contradicted)
  5. Post-action violation detected by SpecGuard (tool executed, post-block decision with trace provenance)
  6. Unsupported completion claims remain UNVERIFIED
  7. Trace integrity across multiple executions (strictly increasing sequence, parent linkages)
  8. JSON serialization round-trip of execution and verification results

**Known limitations:**  
- Runtime operates in-memory against local TraceStore; distributed queues and remote telemetry are intentionally out of scope for v0.1.
- Natural language claim extraction and prose entailment are reserved for TASK-006.

**Commit/PR:**  
- Branch: `task/TASK-005-runtime-wrapper`
- Commit SHA: `4e028fe` (`4e028fea1d451368c340d86a67448fe97eb1df80`)

**Questions/blockers:**  
- None. All acceptance criteria satisfied and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** PENDING

**Next instruction:**  
Do not start TASK-006 until this section says ACCEPTED.
