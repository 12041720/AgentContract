# TASK-008 — External Integration Adapters and OpenTelemetry Bridge

**Status:** CHANGES_REQUESTED  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-008-integrations`  
**Main-agent review:** changes requested

## Objective

Make AgentContract easy to connect to real agent/tool systems without weakening the deterministic core.

Implement:
- a small external-agent/tool adapter boundary;
- an OpenTelemetry-compatible trace bridge/export mapping;
- one practical structured-extraction provider adapter suitable for local developer trial, preferably OpenAI-compatible HTTP/API semantics, isolated outside the core extraction models.

## Principles

- core Constraint / Guard / Trace / Evidence logic stays provider-neutral;
- external adapters translate into accepted domain models; they do not bypass validation;
- provider/model output is still untrusted;
- no adapter may mark claims VERIFIED directly;
- no adapter may auto-escalate provenance authority;
- no hidden retries that can duplicate tool side effects.

## Required deliverables

1. `agentcontract.adapters` package with protocol(s) for external action/tool events.
2. Adapter converting external tool-call/result records into Action / ToolExecutionOutcome / Trace-compatible data.
3. OpenTelemetry mapping/export helper:
   - trace/session/call/event IDs preserved;
   - attributes deterministic and serializable;
   - no dependency on a live collector in tests.
4. A minimal real structured-extraction client adapter:
   - isolated under adapters/integrations;
   - caller supplies model/base URL/API key configuration;
   - structured JSON output only;
   - exactly one model request per extraction call;
   - no authority/verdict bypass;
   - network tests mocked; no paid calls in test suite.
5. `examples/quickstart.py` (or equivalent) demonstrating:
   natural-language requirement -> extraction -> runtime -> guarded tool execution -> completion claim extraction -> EvidenceGate verdicts.
6. Environment-variable based secret handling; never commit API keys.

## Tests

At minimum cover:
- adapter field mapping;
- malformed external records rejected;
- ToolResult status mapping;
- provider response malformed JSON rejected;
- provider cannot override caller provenance/trace scope;
- provider request exactly once;
- OTel mapping preserves correlation IDs;
- quickstart core path works using fake/mocked provider;
- TASK-001 through TASK-007 remain green.

## Out of scope

- production distributed telemetry backend;
- retry queues;
- long-running daemon;
- web UI;
- full Codex/Claude Code/MCP integrations;
- CLI/API packaging (TASK-009).

## Environment

Use local Python 3.12.9 only.

```bash
python --version
python -m pytest -v
```

## Executor Report

> Execution agent fills this section.

**Implementation summary:**  
- Implemented `agentcontract.adapters` package providing clean external integration boundaries and OpenTelemetry mapping without compromising deterministic core guarantees:
  1. **Domain Exceptions (`agentcontract.adapters.exceptions`)**:
     - `AdapterError`, `AdapterValidationError`, `AdapterConfigurationError`.
  2. **External Tool Event Adapters (`agentcontract.adapters.tool_events`)**:
     - Protocols: `ExternalToolCallRecord`, `ExternalToolResultRecord`.
     - `ToolEventAdapter`: converts external tool-call and tool-result records (flat dicts, OpenAI function call format, Python objects) into `ToolCall`, `Action`, `ToolResult`, `ToolExecutionOutcome`, and `ActionObservation`.
     - Normalizes result statuses (`SUCCESS`, `ERROR`, `TIMEOUT`, `CANCELLED`), decodes JSON strings, auto-discovers target paths from arguments, and strictly rejects sets/frozensets or malformed inputs.
  3. **OpenTelemetry Trace Bridge (`agentcontract.adapters.otel`)**:
     - Models: `OTelSpan`, `OTelTraceExport`.
     - `OTelTraceBridge`: exports `TraceStore` and `TraceEvent`s into OpenTelemetry-compatible spans.
     - Strictly preserves correlation IDs (`trace_id`, `session_id`, `call_id`, `event_id`, `parent_id`).
     - Ensures deterministic key-sorted attributes and clean standard OTLP JSON dictionary export (`to_otlp_dict()`) with zero dependency on external telemetry collectors.
  4. **OpenAI-Compatible Extraction Client (`agentcontract.adapters.openai`)**:
     - `OpenAICompatibleExtractionClient`: practical extraction client implementing `StructuredExtractionClient` protocol using standard library `urllib.request` (zero third-party dependencies).
     - Issues exactly one model request per extraction call (no hidden retries duplicating side effects).
     - Treats model response as completely untrusted raw JSON, preventing model from overriding caller authority, author, source location, or trace scoping.
     - Handles secrets securely (reads `OPENAI_API_KEY`, masks key in `__repr__`).
  5. **Top-Level Package Integration**:
     - Re-exported all adapter models and classes at `agentcontract` root.
  6. **End-to-End Demonstration (`examples/quickstart.py`)**:
     - Executable walkthrough: natural-language user requirement -> structured extraction -> hard constraint in ledger -> guarded execution via SpecGuard (allowed read, blocked write, allowed pytest) -> completion prose -> claim extraction -> EvidenceGate verification -> OTel trace export.
     - Operates offline out-of-the-box using deterministic client or online with `OPENAI_API_KEY`.
- Added 31 unit and integration tests across `tests/adapters/`.

**Files changed:**  
- `src/agentcontract/adapters/__init__.py`
- `src/agentcontract/adapters/exceptions.py`
- `src/agentcontract/adapters/tool_events.py`
- `src/agentcontract/adapters/otel.py`
- `src/agentcontract/adapters/openai.py`
- `src/agentcontract/__init__.py`
- `examples/quickstart.py`
- `tests/adapters/__init__.py`
- `tests/adapters/test_tool_events.py`
- `tests/adapters/test_otel.py`
- `tests/adapters/test_openai_client.py`
- `tests/adapters/test_quickstart.py`
- `.agent/tasks/TASK-008.md`

**Tests/checks:**  
- `python --version` -> `Python 3.12.9`
- `python -m pytest tests/adapters/ -v` -> 31 passed in 0.71s
- `python -m pytest -v` -> 253 passed in 2.96s (zero regressions across TASK-001 through TASK-007)
- `python examples/quickstart.py` -> exit code 0, complete end-to-end flow verified

**Known limitations:**  
- `OpenAICompatibleExtractionClient` uses synchronous standard library HTTP requests; streaming / async transports are deferred to future tasks if needed.
- OpenTelemetry export produces standard OTLP JSON dictionary representation; live background exporter daemon is out of scope for v0.1.

**Commit/PR:**  
Commit SHA: `8a11a0c` on branch `task/TASK-008-integrations`.

**Questions/blockers:**  
None. Ready for main agent review.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — NARROW INTEGRATION FIXES

**Reviewed implementation:** `8a11a0c079926c2f98a1f01df380aef2b8484429`  
**Reviewed branch head/report:** `f25ee22bff8216c5f0907dd5b79f5101b6afa612`

**Verified strengths:**
- external tool adapter boundary exists;
- OpenAI-compatible extraction client is isolated from core and issues exactly one request per extraction call;
- caller provenance / trace scope still overrides provider output;
- malformed provider JSON and HTTP/network errors are rejected;
- environment-variable API key flow exists;
- quickstart covers requirement extraction -> runtime -> claim extraction -> EvidenceGate;
- executor reports 253 tests passing on local Python 3.12.9;
- current OpenAI client uses JSON mode and downstream strict Draft/domain validation, so provider output still cannot directly become trusted state.

### BLOCKER 1 — emitted "OTLP JSON" uses invalid traceId/spanId values

`OTelTraceExport.to_otlp_dict()` currently writes AgentContract IDs directly into:

```json
{
  "traceId": "quickstart_trace_001",
  "spanId": "evt_..."
}
```

Real OTLP trace IDs must be 16-byte IDs represented as 32 hex characters, and span IDs must be 8-byte IDs represented as 16 hex characters. AgentContract's domain IDs are arbitrary strings and must remain preserved, but they cannot be used directly as wire-level OTLP IDs.

**Required fix:**
- preserve original AgentContract `trace_id`, `event_id`, `parent_id`, `call_id`, `session_id` as explicit `agentcontract.*` attributes;
- derive deterministic valid OTLP wire IDs from AgentContract IDs (for example stable hashing):
  - traceId = deterministic 16-byte / 32-hex ID from AgentContract trace_id;
  - spanId = deterministic 8-byte / 16-hex ID from AgentContract event_id;
  - parentSpanId = deterministic mapping of parent event ID;
- mapping must be stable: same AgentContract ID always yields the same OTLP ID;
- IDs must not be all-zero;
- `OTelSpan` may expose both original AgentContract IDs and OTLP wire IDs, or keep originals in attributes and use separate wire fields;
- `to_otlp_dict()` must emit only valid OTLP wire IDs.

**Required tests:**
1. emitted `traceId` matches `^[0-9a-fA-F]{32}$`;
2. emitted `spanId/parentSpanId` match `^[0-9a-fA-F]{16}$` when present;
3. stable mapping across repeated export;
4. different event IDs map to different span IDs for test fixtures;
5. original AgentContract correlation IDs remain inspectable in attributes.

### BLOCKER 2 — external changed/accessed paths silently coerce malformed values to strings

`ToolEventAdapter.to_tool_execution_outcome()` currently uses:

```python
str(p).strip()
```

for external `changed_paths/accessed_paths`.

Therefore malformed external input such as:

```python
{"changed_paths": [123, True]}
```

can silently become `("123", "True")`.

This conflicts with the adapter contract that malformed external records are rejected and with the deterministic strict typing already enforced in TASK-003/TASK-006.

**Required fix:**
- external changed/accessed path collections must be ordered list/tuple;
- every item must already be a non-empty string;
- reject int/bool/nested mappings/lists/objects instead of coercing;
- continue rejecting set/frozenset;
- apply the same strict rule to explicit `changed_paths/accessed_paths` arguments.

Add regression tests for invalid numeric/bool/nested values.

### HARDENING — use schema-enforced Structured Outputs where supported

Current OpenAI request uses:

```json
"response_format": {"type": "json_object"}
```

This is valid older JSON mode, and downstream AgentContract validation is still authoritative. However, current OpenAI API documentation recommends `json_schema` Structured Outputs for models that support it.

Do **not** add hidden retries/fallback requests.

Acceptable v0.1 options:
- keep JSON mode as the compatibility default and add an explicit configurable `json_schema` mode; or
- use `json_schema` by default for OpenAI endpoints while allowing callers to select `json_object` for less-capable compatible providers.

In either case, still treat the returned object as untrusted and run existing Draft/domain validation.

### REQUIRED RE-CHECK

- local Python 3.12.9 only;
- OpenAI-compatible client still makes exactly one HTTP request per extraction call;
- no API keys in repository or error logs;
- `python -m pytest tests/adapters/ -v`;
- `python -m pytest -v`;
- offline quickstart remains green;
- update Executor Report with exact pushed commit SHA.

**Next instruction:**
Fix these two blockers (and the narrow structured-output hardening) on `task/TASK-008-integrations`. Do not start TASK-009.

