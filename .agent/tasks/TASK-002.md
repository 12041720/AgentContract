# TASK-002 — Unified Trace and Provenance Model

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-002-trace-model`  
**Main-agent review:** pending

## Objective

Implement a vendor-neutral, append-oriented trace domain for AgentContract.

TASK-002 establishes the durable execution record that later SpecGuard and EvidenceGate will consume. It must normalize the important facts of an agent run without depending on OpenAI, Anthropic, LangGraph, MCP, or OpenTelemetry packages.

The trace layer answers:

- what happened?
- in what order?
- who/what produced the event?
- which tool call/result pairs belong together?
- which event can later be cited as provenance/evidence?
- can the trace be serialized and reconstructed without losing identity or structure?

## Required reading

Before implementation:

1. `AGENTS.md`
2. `.agent/STATE.md`
3. `docs/ARCHITECTURE.md`
4. `.agent/tasks/TASK-001.md`
5. this file

## Scope

Implement under `src/agentcontract/trace/` plus tests.

### Required identifiers

Define typed aliases or lightweight value types for at least:

- `TraceId`
- `SessionId`
- `EventId`
- `ToolCallId`

Use the repository's development baseline: the user's installed local **Python 3.12.9**. Python 3.12 syntax is allowed. Do not install another Python version just to broaden compatibility.

### Required enums

Names may vary if the semantics remain clear.

#### Actor kind

At minimum distinguish:

- `USER`
- `AGENT`
- `TOOL`
- `SYSTEM`
- `GUARD`
- `ENVIRONMENT`

#### Event kind

At minimum support normalized events equivalent to:

- user message / instruction;
- agent message / reasoning-visible output;
- proposed tool call;
- tool result;
- guard/policy decision;
- artifact/state observation;
- error.

Do not model private chain-of-thought. Only observable agent messages/actions/results belong in the trace.

#### Tool result status

At minimum:

- `SUCCESS`
- `ERROR`
- `TIMEOUT`
- `CANCELLED`

### Required durable models

At minimum implement immutable/serializable models equivalent to:

#### TracePointer

A compact provenance reference that can be stored by future constraints/evidence.

Expected semantics:

```text
trace_id
event_id
(optional session_id)
```

It must be sufficient to point back to the exact event that originated or supports some later domain object.

#### ToolCall

Expected fields include:

- stable `call_id`;
- tool name;
- immutable structured arguments.

#### ToolResult

Expected fields include:

- matching `call_id`;
- result status;
- immutable structured output/metadata where applicable;
- optional error information;
- optional exit code / duration when available.

Do not assume every tool is a shell command.

#### TraceEvent

Expected fields include:

- `event_id`;
- `trace_id`;
- `session_id`;
- monotonically ordered `sequence` within a trace;
- UTC timestamp;
- actor kind;
- event kind;
- optional parent event ID;
- immutable attributes/metadata;
- typed payload or a clearly discriminated payload representation.

A trace event must not collapse a tool call and a tool result into one indistinguishable blob.

### TraceLog / TraceStore

Implement an in-memory append-oriented container with operations equivalent to:

- append an event;
- retrieve by event ID;
- list events in deterministic sequence order;
- filter/query by trace ID, session ID, event kind, and actor kind;
- create a `TracePointer`;
- serialize/deserialize complete trace state.

Exact class/method names are executor design freedom.

## Required invariants

The implementation must enforce:

1. Event IDs are unique within the store.
2. Sequence numbers are non-negative and strictly increasing within a given trace.
3. Appending a duplicate sequence for the same trace fails explicitly.
4. Event timestamps must be timezone-aware; normalize or reject naive timestamps explicitly.
5. A `TOOL_RESULT` must reference a known prior tool call in the same trace.
6. A tool result's `call_id` must match the referenced tool call.
7. The same `ToolCallId` may not be reused for multiple tool-call events in the same trace.
8. Parent-event references, when supplied, must refer to an already-known event in the same trace.
9. Durable payload/metadata state must not be externally mutable through ordinary Python container operations.
10. Serialization round-trip preserves IDs, ordering, event kinds, actor kinds, payloads, and pointers.
11. Unknown/unstructured tool outputs may be represented, but must remain explicitly distinguishable from an error/timeout result.
12. The trace layer must not infer success merely from the presence of an agent message.

## Cross-package design rule

TASK-001 introduced an immutable `FrozenDict` implementation under the constraints package.

Do **not** duplicate another subtly different immutable mapping.

You may choose one of these approaches:

- reuse the existing immutable type temporarily; or
- perform a small, API-preserving refactor moving the generic immutable primitive into a neutral shared module (preferred if clean), while re-exporting it from the old import path so TASK-001 public imports/tests continue to work.

If refactoring, preserve backwards compatibility and prove TASK-001 tests still pass.

## Out of scope

Do **not** implement in TASK-002:

- OpenTelemetry SDK/exporters;
- Codex/Claude/OpenHands adapters;
- SpecGuard constraint evaluation;
- requirement extraction;
- claims/evidence scoring;
- LLM calls;
- database persistence;
- FastAPI/CLI;
- workflow execution/retry logic.

TASK-008 owns external tracing adapters.

## Expected files

A reasonable shape is:

```text
src/agentcontract/
├── trace/
│   ├── __init__.py
│   ├── models.py
│   └── store.py
└── ... optional neutral shared immutable module if justified

tests/
└── trace/
    ├── test_models.py
    └── test_store.py
```

The executor may choose a different narrow split.

## Acceptance criteria

Main-agent review requires:

- [ ] runs correctly on the user's local Python 3.12.9 environment;
- [ ] Pydantic durable models;
- [ ] normalized actor/event/status enums;
- [ ] typed ToolCall and ToolResult representation;
- [ ] append/query/retrieve trace container;
- [ ] explicit sequence and identity validation;
- [ ] tool-call/result correlation validation;
- [ ] parent-event integrity checks;
- [ ] deep immutability/defensive isolation;
- [ ] TracePointer provenance reference;
- [ ] complete JSON/dict round-trip tests;
- [ ] TASK-001 tests still pass unchanged;
- [ ] no vendor SDK/network/LLM dependency;
- [ ] concise type hints/docstrings;
- [ ] full `pytest` suite passes on the user's local Python 3.12.9 interpreter.

## Suggested test scenarios

At minimum cover scenarios equivalent to:

1. user instruction → agent message → tool call → tool result;
2. two traces interleaved in one store retain independent monotonic sequences;
3. duplicate event ID rejection;
4. duplicate/decreasing sequence rejection within one trace;
5. same sequence allowed in different trace IDs;
6. duplicate ToolCallId rejection within a trace;
7. tool result with unknown call ID rejection;
8. tool result belonging to another trace rejection;
9. mismatched parent trace/event rejection;
10. timezone-naive timestamp handling is explicit and tested;
11. timeout result remains distinct from success and error;
12. external argument/output dict mutation cannot alter stored history;
13. TracePointer survives serialization round-trip and resolves to the same event;
14. filtering by actor/event/session/trace is deterministic;
15. complete store JSON round-trip preserves semantic equality/order.

## Required checks

Before implementation/testing, remove the Python 3.11 interpreter that was downloaded by uv solely for the previous compatibility check. First inspect uv-managed interpreters and then uninstall 3.11 if present:

```bash
uv python list --managed-python
uv python uninstall 3.11
```

Do **not** uninstall the user's system Python 3.12.9. The uv command above targets uv-managed Python installations. uv documents `uv python uninstall <TARGETS>` for removing managed Python versions. If no uv-managed 3.11 remains, record that and continue.

Then run only the local development interpreter checks:

```bash
python --version
python -m pytest
```

Expected development interpreter: **Python 3.12.9**. Do not download or run an additional Python version merely for compatibility testing.

Report the local Python version and test result.

## Executor Report

> Execution agent: fill this section only after implementation.

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

**Findings:**  
Pending implementation.

**Next instruction:**  
Do not start TASK-003 until this section says ACCEPTED.
