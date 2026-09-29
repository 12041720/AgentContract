# TASK-008 — External Integration Adapters and OpenTelemetry Bridge

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-008-integrations`  
**Main-agent review:** pending

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

**Verdict:** PENDING

**Next instruction:**  
Do not start TASK-009 until this section says ACCEPTED.
