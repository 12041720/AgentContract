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

- [ ] synchronous vendor-neutral runtime wrapper exists;
- [ ] BLOCK prevents executor invocation;
- [ ] WARN allows execution and remains visible;
- [ ] executed calls produce correlated ToolCall/ToolResult trace events;
- [ ] executor exceptions become ERROR evidence rather than disappearing;
- [ ] post-action observations are checked by SpecGuard;
- [ ] runtime can verify typed claims through EvidenceGate;
- [ ] no success is inferred from agent text;
- [ ] full E2E tests cover block/allow/warn/failure/post-violation/claim verification;
- [ ] TASK-001 through TASK-004 tests remain green;
- [ ] no LLM/network/vendor dependency;
- [ ] local Python 3.12.9 only.

## Environment

```bash
python --version
python -m pytest -v
```

Do not install another Python interpreter for compatibility testing.

## Executor Report

> Execution agent fills this section.

**Implementation summary:**  
TBD

**Files changed:**  
TBD

**Tests/checks:**  
TBD

**Known limitations:**  
TBD

**Commit/PR:**  
TBD

**Questions/blockers:**  
TBD

## Main Agent Review

> Main agent only.

**Verdict:** PENDING

**Next instruction:**  
Do not start TASK-006 until this section says ACCEPTED.
