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
- 40 unit and integration tests across `tests/adapters/`.

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
- `python -m pytest tests/adapters/ -v` -> 40 passed in 0.43s
- `python -m pytest -v` -> 262 passed in 1.05s (zero regressions across TASK-001 through TASK-008)
- `python examples/quickstart.py` -> exit code 0, complete end-to-end flow verified offline

**Known limitations:**  
- `OpenAICompatibleExtractionClient` uses synchronous standard library HTTP requests; streaming / async transports are deferred to future tasks if needed.
- OpenTelemetry export produces standard OTLP JSON dictionary representation; live background exporter daemon is out of scope for v0.1.

**Commit/PR:**  
Commit SHA: `0a148bb` (implementation) on branch `task/TASK-008-integrations`.

**Questions/blockers:**  
None. Blocker 1 (OTLP wire IDs), Blocker 2 (strict external path typing), and Hardening (Structured Outputs json_schema mode) are fully resolved with regression tests. Ready for main agent review.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — FINAL API COMPATIBILITY FIX

**Reviewed implementation:** `0a148bb2a9c40142fce59cab1462d3e7047f9e03`

**Previous blockers verified fixed:**
- OTLP wire IDs are now deterministic valid 32-hex trace IDs / 16-hex span IDs while original AgentContract IDs remain preserved in attributes;
- external changed/accessed/action path inputs now reject malformed non-string values instead of coercing;
- OpenAI-compatible adapter supports explicit `json_schema` and `json_object` modes with exactly one request and no hidden retry;
- executor reports 262 tests passing on local Python 3.12.9.

### FINAL BLOCKER — current extraction schemas are not OpenAI strict Structured Outputs compatible

The adapter now defaults to:

```python
response_format_mode="json_schema"
strict=True
```

but the schemas produced by `get_requirement_extraction_schema()` and `get_claim_extraction_schema()` are not valid strict Structured Outputs schemas.

Current examples:

```python
# Constraint item:
properties = {
    "name": ...,
    "description": ...,
    "strength": ...,
    "rule_effect": ...,
    "scope": ...,
    "compliance_scope": ...,
}
required = ["name", "description", "strength", "rule_effect", "scope"]
```

and claim items define many optional properties but only require:

```python
["claim_type", "description"]
```

OpenAI strict Structured Outputs requires all object properties to be required; optional values should be represented as nullable fields. Every object must also set `additionalProperties: false`.

Additionally, `scope.selectors` is currently:

```python
{"type": "object"}
```

which is not a closed strict object schema.

This means mock tests pass but a real OpenAI API request in the default `json_schema` mode can fail before model execution.

**Required fix:**

Choose one of these clean approaches:

### Preferred
Add provider-specific strict-schema conversion/builders for the OpenAI adapter while leaving core extraction schemas/domain models provider-neutral.

For every object sent under `strict=True`:
- `additionalProperties: false`;
- every declared property appears in `required`;
- optional semantic values use nullable types, e.g. `["string", "null"]`;
- optional arrays/objects are represented in a strict-compatible way;
- do not include unconstrained/free-form object fields such as `selectors` unless represented with a supported closed schema.

For requirement extraction, fields not needed from the provider (e.g. spoof/audit-only authority fields) should preferably be omitted from the provider schema rather than invited as model output.

For claim extraction, optional claim selectors may be emitted as required-but-nullable fields.

### Alternative
Make `json_object` the compatibility default and require explicit opt-in to `json_schema` only when a strict-compatible schema builder is supplied.

However, if `examples/quickstart.py` is meant to demonstrate current OpenAI Structured Outputs, the preferred approach is better.

**Required tests:**
1. recursively assert every object in the actual schema sent in `json_schema` mode has `additionalProperties is False`;
2. recursively assert each object's `required` contains every key in `properties`;
3. optional semantic fields are nullable instead of omitted from `required`;
4. generated requirement schema and claim schema pass the strict-schema validator;
5. captured HTTP request contains the strict-compatible transformed schema;
6. exactly one HTTP request remains true;
7. offline quickstart remains green.

**Also update quickstart:**
- allow `OPENAI_BASE_URL` and `OPENAI_RESPONSE_FORMAT` environment variables in addition to `OPENAI_MODEL`;
- default `OPENAI_RESPONSE_FORMAT=json_schema` only after the schema is strict-compatible;
- users of less-capable OpenAI-compatible endpoints can set `json_object`.

**Required re-check:**
- local Python 3.12.9;
- `python -m pytest tests/adapters/ -v`;
- `python -m pytest -v`;
- `python examples/quickstart.py`;
- update Executor Report with exact pushed commit SHA.

**Next instruction:**
Apply this final API-compatibility fix on `task/TASK-008-integrations`. Do not start TASK-009.

