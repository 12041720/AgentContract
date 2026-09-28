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
Do not start TASK-009 until this section says ACCEPTED.
