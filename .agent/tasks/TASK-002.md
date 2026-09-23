# TASK-002 — Unified Trace and Provenance Model

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-002-trace-model`  
**Main-agent review:** changes requested

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
- **Environment & Baseline Alignment:** Development and testing executed exclusively on the user's installed local **Python 3.12.9** baseline (`python --version` -> `Python 3.12.9`).
- **Resolved Blocker 1 (ToolResult Parent Provenance Integrity):**
  - Updated `src/agentcontract/trace/store.py` to enforce unambiguous provenance for `TOOL_RESULT` events:
    - `parent_id` remains optional, but when supplied on a `TOOL_RESULT` it **must point to the `TOOL_CALL` event whose `call_id` matches `tool_result.call_id`**.
    - If `parent_id` points to a different tool call, `ToolCorrelationError` is raised.
    - If `parent_id` points to a non-`TOOL_CALL` event (e.g. `USER_MESSAGE` or `AGENT_MESSAGE`), `ParentEventError` is raised.
    - If `parent_id` is omitted (`None`), it is accepted and correlated by `call_id`.
  - Added 4 dedicated regression tests in `tests/trace/test_store.py`: `test_tool_result_matching_parent_accepted`, `test_tool_result_parent_pointing_to_different_tool_call_rejected`, `test_tool_result_parent_pointing_to_non_tool_call_event_rejected`, and `test_tool_result_without_parent_accepted`.
- **Resolved Blocker 2 (ToolResult Output Durable Immutability & Serialization):**
  - Defined `_freeze_trace_value()` in `src/agentcontract/trace/models.py` to enforce a strict durable trace value domain: JSON-compatible scalars (`None`, `bool`, `int`, `float`, `str`) and recursively frozen containers (`FrozenDict`, `tuple`, `frozenset`).
  - Unsupported mutable types (`bytearray`, `bytes`), arbitrary custom objects, or nested unsupported values are explicitly rejected with `TraceValidationError`.
  - Enforced `_freeze_trace_value` on `ToolResult.output`, `ToolResult.metadata`, `ToolCall.arguments`, `TraceEvent.metadata`, and `TraceEvent.payload`.
  - Configured deterministic JSON serialization (`_serialize_output`, `_serialize_payload`) ensuring stable round-trip reconstruction.
  - Added dedicated regression tests in `tests/trace/test_models.py`: `test_unsupported_mutable_and_custom_types_rejected_in_output` and `test_accepted_output_domain_json_round_trip`.
- **Non-blocking Cleanups:**
  - Added validation in `TracePointer` ensuring `session_id`, when supplied, rejects empty or blank whitespace strings.
  - Removed unused imports (`Iterable`, `Iterator`, `Mapping`, `GetCoreSchemaHandler`, `core_schema`) from `src/agentcontract/constraints/models.py`.

**Files changed:**  
- `src/agentcontract/common/__init__.py` (shared immutable exports)
- `src/agentcontract/common/immutable.py` (neutral shared `FrozenDict`, `_freeze_value`)
- `src/agentcontract/constraints/models.py` (cleaned unused imports; re-exports from common)
- `src/agentcontract/trace/__init__.py` (public trace domain exports)
- `src/agentcontract/trace/exceptions.py` (typed domain exceptions)
- `src/agentcontract/trace/models.py` (`_freeze_trace_value`, models, enums, serializers)
- `src/agentcontract/trace/store.py` (`TraceStore` append container with parent correlation checks)
- `src/agentcontract/__init__.py` (top-level package re-exports)
- `tests/trace/test_models.py` (17 tests covering models, immutability, blocker 2 domain tests, serialization)
- `tests/trace/test_store.py` (21 tests covering store scenarios 1-15, blocker 1 provenance tests, container ops)
- `.agent/tasks/TASK-002.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **71 passed in 0.62s** (100% pass rate: 33 constraint tests + 38 trace tests).

**Known limitations:**  
- In-memory append-only storage for v0.1 (database persistence via SQLite/PostgreSQL is deferred to later milestones).
- External framework/telemetry adapters (OpenTelemetry, LangGraph, etc.) are deferred to TASK-008 per scope boundaries.

**Commit/PR:**  
- Branch: `task/TASK-002-trace-model`
- Commit SHA: `9f60435`

**Questions/blockers:**  
- None. Both Round 1 blockers and non-blocking cleanups have been implemented, tested with regression suites, and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED

**Reviewed implementation:** `431534bd21ab62751a63b47db19d6368c5828a08`

**What is accepted so far:**
- Local Python 3.12.9 baseline is correctly used; the uv-managed Python 3.11 environment was removed as requested.
- The shared immutable primitive was cleanly moved to `agentcontract.common` while preserving TASK-001 compatibility.
- Event/actor/status enums and the ToolCall / ToolResult split are appropriate.
- Per-trace sequence monotonicity, global event-ID uniqueness, parent trace checks, tool-call uniqueness, result uniqueness, filtering, pointer resolution, and round-trip reconstruction are well structured.
- TASK-001 tests remain green according to the executor report; full suite is reported as 64 passed.

### BLOCKER 1 — ToolResult can carry contradictory provenance

The store correlates a TOOL_RESULT to a prior tool call by `ToolResult.call_id`, and independently validates `parent_id` only as “an earlier event in the same trace”.

Therefore this inconsistent event is currently accepted:

```text
event A: TOOL_CALL call_id="call-A"
event B: TOOL_CALL call_id="call-B"

result event:
  parent_id = event A
  ToolResult.call_id = "call-B"
```

Both references are individually valid, but together they disagree about which action produced the result. EvidenceGate will later rely on provenance edges, so the trace layer must not permit contradictory correlation paths.

**Required fix:**
- Define one clear rule for TOOL_RESULT parent semantics.
- Recommended rule: `parent_id` remains optional, but when supplied on a TOOL_RESULT it **must point to the TOOL_CALL event whose `ToolCall.call_id` equals `ToolResult.call_id`**.
- Reject parent references to a different tool call or to a non-tool-call event for TOOL_RESULT.
- Add tests for:
  - matching parent + call_id accepted;
  - parent points to different tool call rejected;
  - parent points to non-TOOL_CALL event rejected.
- If you choose instead to make matching `parent_id` mandatory for TOOL_RESULT, document that decision and update tests consistently.

### BLOCKER 2 — ToolResult.output does not guarantee durable immutability / serialization

`ToolResult.output` is declared as `Any | None`, and `_freeze_value()` only freezes mappings, list/tuple, and set/frozenset.

A built-in mutable value such as `bytearray` is retained by reference:

```python
raw = bytearray(b"abc")
result = ToolResult(
    call_id="c1",
    status=ToolResultStatus.SUCCESS,
    output=raw,
)
raw[0] = ord("z")
# result.output has now changed after the fact
```

Other arbitrary mutable/custom objects can have the same problem, and arbitrary `Any` values also undermine the promise that the durable trace always JSON round-trips.

**Required fix:**
- Define the supported durable trace-value domain explicitly.
- Prefer accepting JSON-like scalar values plus recursively frozen containers (e.g. `None | bool | int | float | str | FrozenDict | tuple[...] | frozenset[...]` if sets are intentionally supported), and reject unsupported arbitrary mutable/custom objects with `TraceValidationError`.
- Alternatively normalize binary/unknown outputs into an explicit immutable representation, but do not silently retain arbitrary mutable object references.
- Ensure all accepted output values serialize and reconstruct predictably.
- Add regression tests at minimum for:
  - `bytearray` or another unsupported mutable built-in being rejected or normalized immutably;
  - nested lists/dicts remaining frozen;
  - accepted output domain JSON round-trip;
  - unsupported custom object rejection.

**Non-blocking cleanup:**
- `TracePointer.session_id` is optional but currently does not reject a blank string. Aligning it with the other identifier validation would improve consistency.
- Some imports left in `constraints/models.py` became unused after moving `FrozenDict`; clean them if convenient, but do not expand scope.

**Required re-check:**
- Use only local Python 3.12.9.
- Run `python --version` and `python -m pytest`.
- Do not reinstall Python 3.11 or any alternate interpreter.
- Update Executor Report with the new commit SHA and exact test result.

**Next instruction:**
Fix these two blockers on `task/TASK-002-trace-model`. Do not start TASK-003.

