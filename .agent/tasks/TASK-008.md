# TASK-008 — External Integration Adapters and OpenTelemetry Bridge

**Status:** ACCEPTED  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-008-integrations`  
**Main-agent review:** accepted and integrated

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
     - Normalizes result statuses (`SUCCESS`, `ERROR`, `TIMEOUT`, `CANCELLED`), decodes JSON strings, auto-discovers target paths from arguments.
     - **Strict Path Typing**: `changed_paths`, `accessed_paths`, and `paths` strictly accept ordered `list` or `tuple` of non-empty strings. Bare strings, sets, frozensets, and non-sequence containers are rejected. Elements must be instances of `str`; non-string types (`int`, `bool`, `dict`, `list`, `float`, custom objects) are rejected with `AdapterValidationError` instead of coercing via `str()`.
  3. **OpenTelemetry Trace Bridge (`agentcontract.adapters.otel`)**:
     - Models: `OTelSpan`, `OTelTraceExport`.
     - `OTelTraceBridge`: exports `TraceStore` and `TraceEvent`s into OpenTelemetry-compatible spans.
     - Strictly preserves correlation IDs (`trace_id`, `session_id`, `call_id`, `event_id`, `parent_id`) in `OTelSpan` properties and explicit `agentcontract.*` attributes.
     - **OTLP Wire IDs**: Implemented deterministic, stable mappings `to_otlp_trace_id` (32 hex characters) and `to_otlp_span_id` (16 hex characters) with non-zero guarantee and lowercase normalization.
     - `to_otlp_dict()` emits standard 32-hex `traceId`, 16-hex `spanId`, and 16-hex / `""` `parentSpanId`.
  4. **OpenAI-Compatible Extraction Client (`agentcontract.adapters.openai`)**:
     - `OpenAICompatibleExtractionClient`: practical extraction client implementing `StructuredExtractionClient` protocol using standard library `urllib.request` (zero third-party dependencies).
     - **Zero Hidden Retries**: issues exactly one model request per extraction call; errors raise immediately without duplicate side effects.
     - **Structured Outputs**: configurable `response_format_mode`: supports `"json_schema"` (OpenAI Structured Outputs, default) and `"json_object"` (JSON Mode for compatible providers). Validates format mode on init.
     - Downstream AgentContract Draft and domain validation remains authoritative; model output is treated as untrusted raw JSON.
     - Handles secrets securely (reads `OPENAI_API_KEY`, masks key in `__repr__`).
  5. **Top-Level Package Integration**:
     - Re-exported all adapter models and helper functions (`to_otlp_trace_id`, `to_otlp_span_id`) at `agentcontract` root.
  6. **End-to-End Demonstration (`examples/quickstart.py`)**:
     - Executable walkthrough: natural-language user requirement -> structured extraction -> hard constraint in ledger -> guarded execution via SpecGuard (allowed read, blocked write, allowed pytest) -> completion prose -> claim extraction -> EvidenceGate verification -> OTel trace export.
     - Operates offline out-of-the-box using deterministic client or online with `OPENAI_API_KEY`.
- Added 46 unit and integration tests across `tests/adapters/`.
  7. **Strict Structured Outputs API Compatibility**:
     - Added `to_strict_json_schema`: recursively converts schemas into OpenAI strict Structured Outputs compatible schemas (`additionalProperties: false`, all property keys in `required`, unrestricted objects omitted, optional semantic fields made nullable).
     - Added provider strict schema builders: `get_openai_requirement_extraction_schema()` and `get_openai_claim_extraction_schema()`.
     - Added recursive validator `validate_strict_json_schema`.
     - `OpenAICompatibleExtractionClient` automatically applies `to_strict_json_schema` in `json_schema` mode and supports `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_RESPONSE_FORMAT` env vars.
     - Quickstart supports `OPENAI_MODEL`, `OPENAI_BASE_URL`, and `OPENAI_RESPONSE_FORMAT` (default `json_schema`, compatible `json_object`).

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
- `python -m pytest tests/adapters/ -v` -> 46 passed in 0.49s
- `python -m pytest -v` -> 268 passed in 1.39s (zero regressions across TASK-001 through TASK-008)
- `python examples/quickstart.py` -> exit code 0, complete end-to-end flow verified offline

**Known limitations:**  
- `OpenAICompatibleExtractionClient` uses synchronous standard library HTTP requests; streaming / async transports are deferred to future tasks if needed.
- OpenTelemetry export produces standard OTLP JSON dictionary representation; live background exporter daemon is out of scope for v0.1.

**Commit/PR:**  
Commit SHA: `47fd8ff` (implementation) on branch `task/TASK-008-integrations`.

**Questions/blockers:**  
None. All review blockers (OTLP wire IDs, strict external path typing, strict Structured Outputs schemas) are fully resolved with recursive validation tests. Ready for main agent review.

## Main Agent Review

> Main agent only.

**Verdict:** ACCEPTED

**Final implementation reviewed:** `47fd8ffa4a7bfa9f27cb69e01dce6d6ff0583934`  
**Final branch head/report:** `38754fd47442306aa88d8282431208f35285fae3`  
**Integrated to main:** `0469bf7a0204eba56aaa2fe44d65edfb63b8b4ac`

**Acceptance summary:**
- external tool-event adapter boundary is implemented with strict validation;
- OpenAI-compatible extraction client supports exactly-once requests with no hidden retry;
- caller provenance and trace/session authority remain enforced;
- strict Structured Outputs schemas are recursively closed and all properties required;
- optional semantic fields are nullable;
- JSON mode remains available for compatible providers;
- valid deterministic OTLP wire IDs are emitted while original AgentContract IDs remain preserved;
- offline quickstart demonstrates the full natural-language extraction -> guard -> trace -> claim verification flow;
- executor reports **268 tests passed** on local Python 3.12.9.

**Next instruction:**
TASK-008 is complete. Proceed only with TASK-009 referenced by `.agent/STATE.md`.

