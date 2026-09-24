# TASK-002 — Unified Trace and Provenance Model

**Status:** ACCEPTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-002-trace-model`  
**Main-agent review:** accepted and integrated

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
- **Environment & Baseline Alignment:** Development and testing executed exclusively on the user's installed local **Python 3.12.9** baseline (`python --version` -> `Python 3.12.9`). uv-managed Python check confirmed no 3.11 managed interpreters present (`uv python list --managed-python`).
- **Resolved Blocker 1 (ToolResult Parent Provenance Integrity):**
  - Updated `src/agentcontract/trace/store.py` to enforce unambiguous provenance for `TOOL_RESULT` events:
    - `parent_id` remains optional, but when supplied on a `TOOL_RESULT` it **must point to the `TOOL_CALL` event whose `call_id` matches `tool_result.call_id`**.
    - If `parent_id` points to a different tool call, `ToolCorrelationError` is raised.
    - If `parent_id` points to a non-`TOOL_CALL` event (e.g. `USER_MESSAGE` or `AGENT_MESSAGE`), `ParentEventError` is raised.
    - If `parent_id` is omitted (`None`), it is accepted and correlated by `call_id`.
  - Covered with 4 dedicated regression tests in `tests/trace/test_store.py`.
- **Resolved Blocker 2 / Round 2 Fix (Narrow Durable Value Domain & JSON Semantic Round-Trip):**
  - Enforced a strictly defined, JSON-compatible durable value domain:
    - Supported: `None | bool | int | finite float | str | mapping | list | tuple`.
    - Normalization: `mapping -> FrozenDict`, `list/tuple -> tuple`.
    - Prohibited / rejected: `set`, `frozenset`, `bytes`, `bytearray`, `NaN`, `Infinity`, `-Infinity`, and arbitrary custom objects.
    - Rejection raises `TraceValidationError` (wrapped in `pydantic.ValidationError`).
  - Added float finiteness validation via `math.isfinite()` on all float inputs.
  - Aligned `TraceEvent.payload` type annotation (`ToolCall | ToolResult | TraceDurableValue`), input normalization, and serializer to strictly match the declared durable value domain.
  - Exported `TraceDurableValue` in `src/agentcontract/trace/__init__.py` and top-level `src/agentcontract/__init__.py`.
  - Preserved Invariant 10: All supported types round-trip through JSON with exact semantic equality (`rebuilt.output == tr.output` and `rebuilt.payload == event.payload`) without type loss or weakened assertions.
  - Added regression test suites in `tests/trace/test_models.py` covering:
    - `test_unsupported_mutable_and_custom_types_rejected_in_output`: tests `bytearray`, `bytes`, `set`, `frozenset`, `NaN`, `inf`, `-inf`, `object()`, `CustomObject()`, and nested variants.
    - `test_accepted_output_domain_json_round_trip`: tests exact semantic equality on JSON round-trip for scalars, lists, tuples, and nested dictionaries.
    - `test_trace_event_durable_payload_domain_and_round_trip`: tests all accepted durable types as `TraceEvent.payload` with exact semantic equality after JSON round-trip.
    - `test_trace_event_payload_unsupported_types_rejected`: tests rejection of non-durable payloads in `TraceEvent`.
    - `test_tool_call_arguments_unsupported_types_rejected`: tests rejection of non-finite floats, sets, bytes in `ToolCall.arguments`.
- **Non-blocking Cleanups:**
  - Added validation in `TracePointer` ensuring `session_id`, when supplied, rejects empty or blank whitespace strings.
  - Cleaned unused imports in `src/agentcontract/constraints/models.py`.

**Files changed:**  
- `src/agentcontract/common/__init__.py` (shared immutable exports)
- `src/agentcontract/common/immutable.py` (neutral shared `FrozenDict`, `_freeze_value`)
- `src/agentcontract/constraints/models.py` (cleaned unused imports; re-exports from common)
- `src/agentcontract/trace/__init__.py` (public trace domain exports, including `TraceDurableValue`)
- `src/agentcontract/trace/exceptions.py` (typed domain exceptions)
- `src/agentcontract/trace/models.py` (`TraceDurableValue`, `_freeze_trace_value`, models, enums, serializers)
- `src/agentcontract/trace/store.py` (`TraceStore` append container with parent correlation checks)
- `src/agentcontract/__init__.py` (top-level package re-exports)
- `tests/trace/test_models.py` (20 tests covering models, immutability, blocker 2 domain tests, serialization, exact round-trips)
- `tests/trace/test_store.py` (21 tests covering store scenarios 1-15, blocker 1 provenance tests, container ops)
- `.agent/tasks/TASK-002.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **74 passed in 0.49s** (100% pass rate: 33 constraint tests + 41 trace tests).

**Known limitations:**  
- In-memory append-only storage for v0.1 (database persistence via SQLite/PostgreSQL is deferred to later milestones).
- External framework/telemetry adapters (OpenTelemetry, LangGraph, etc.) are deferred to TASK-008 per scope boundaries.

**Commit/PR:**  
- Branch: `task/TASK-002-trace-model`
- Commit SHA: `7518701` (code), follow-up report commit

**Questions/blockers:**  
- None. The durable value domain has been narrowed and unified, float finiteness is enforced, sets and non-finite floats are rejected with `TraceValidationError`, `TraceEvent.payload` is aligned, and all accepted values round-trip with exact semantic equality on Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** ACCEPTED

**Final implementation reviewed:** `7518701badfd7db18a9994f6eab21987f1282b1d`  
**Integrated to main:** `2c71b2509dc82a95a2c3ce298602811f549ac1ff`

**Acceptance summary:**
- Unified actor/event/tool trace models are vendor-neutral and immutable.
- Event identity, sequence ordering, parent references, and tool call/result correlation are enforced.
- TOOL_RESULT parent provenance cannot contradict `call_id`.
- Durable trace values use one explicit JSON-safe immutable domain; unsupported mutable/custom values, sets, binary values, NaN, and infinities are rejected.
- TracePointer, deterministic filtering, serialization/deserialization, and exact semantic round-trips are implemented.
- TASK-001 compatibility is preserved through the shared immutable primitive.
- Executor reports **74 tests passed** on local Python 3.12.9.

**Next instruction:**
TASK-002 is complete. Proceed only with TASK-003 referenced by `.agent/STATE.md`.

