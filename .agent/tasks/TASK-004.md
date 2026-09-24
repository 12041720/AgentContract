# TASK-004 — Claims, Evidence Graph, and Deterministic EvidenceGate

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-004-evidence-gate`  
**Main-agent review:** pending

## Objective

Implement the deterministic EvidenceGate core.

Given agent claims such as:

- tests passed;
- build succeeded;
- file was created;
- command completed successfully;
- API remained unchanged;

the system must verify whether actual trace evidence supports, contradicts, or fails to support each claim.

No LLM calls in TASK-004.

## Required concepts

Implement immutable/serializable models equivalent to:

- `Claim`
- `ClaimType`
- `EvidenceRef`
- `EvidenceRelation`
- `ClaimVerdict`: `VERIFIED`, `CONTRADICTED`, `UNVERIFIED`
- `ClaimEvaluation`
- `EvidenceGate`

Claims must remain atomic. Do not treat a long natural-language final answer as one opaque claim.

## Evidence sources

Use accepted TASK-002 trace facts, especially:

- ToolCall
- ToolResult
- ToolResultStatus
- TraceEvent
- TracePointer

Evidence must reference exact trace events, not free-floating strings.

## Deterministic v0.1 claim types

At minimum support typed claims equivalent to:

1. `TOOL_SUCCEEDED`
2. `COMMAND_EXITED_ZERO`
3. `TESTS_PASSED`
4. `FILE_EXISTS` or explicit observed artifact existence
5. `ACTION_COMPLETED`

Do not verify arbitrary semantic claims from prose.

## Core rules

1. Agent statements are claims, never evidence by themselves.
2. Missing evidence => `UNVERIFIED`, never VERIFIED.
3. Explicit contradictory evidence => `CONTRADICTED`.
4. Matching deterministic success evidence => `VERIFIED`.
5. Error/timeout/cancelled tool result cannot verify success.
6. For exit-code claims, only an observed matching result with exit_code == 0 verifies success.
7. A claim must identify or deterministically resolve the action/tool/event it refers to.
8. Evidence from a different trace/call must not satisfy the claim.
9. One evidence item may support multiple claims, but each claim evaluation must retain its own provenance.
10. Verdict precedence: contradiction beats support if both are present for the same exact claimed execution.

## TESTS_PASSED semantics

For v0.1, do not parse arbitrary test frameworks.

Use explicit structured claim metadata, e.g. expected tool/call plus optional expected test command, and require supporting ToolResult evidence with:

- matching call/trace identity;
- SUCCESS status;
- exit_code == 0 when exit code is present/required;
- no contradictory result for the same call.

Do not infer "tests passed" from an AGENT_MESSAGE saying so.

## Evidence graph

Implement a small graph/index that can answer:

- which evidence supports this claim?
- which evidence contradicts this claim?
- which claims cite this evidence?
- resolve TracePointer to event through TraceStore.

Keep graph IDs deterministic and serializable.

## API

Provide APIs equivalent to:

```python
evaluation = gate.evaluate(claim, trace_store)
evaluations = gate.evaluate_many(claims, trace_store)
```

## Required tests

At minimum:

1. successful ToolResult verifies TOOL_SUCCEEDED;
2. ERROR result contradicts TOOL_SUCCEEDED;
3. TIMEOUT contradicts success;
4. no result -> UNVERIFIED;
5. AGENT_MESSAGE "tests passed" alone -> UNVERIFIED;
6. matching test ToolResult success + exit 0 -> VERIFIED;
7. test ToolResult exit 1 -> CONTRADICTED;
8. evidence from another call_id does not verify claim;
9. evidence from another trace does not verify claim;
10. TracePointer resolves to exact supporting event;
11. one evidence event supports multiple independent claims;
12. claim/evaluation JSON round-trip;
13. graph reverse lookup evidence -> claims;
14. contradictory evidence dominates support for same execution;
15. TASK-001/002/003 tests remain green.

## Out of scope

Do not implement:

- LLM claim extraction;
- natural-language entailment;
- fuzzy evidence matching;
- semantic diff/API compatibility analysis;
- Codex/Claude adapters;
- OpenTelemetry;
- database persistence;
- final response rewriting.

TASK-006 owns LLM-assisted extraction.

## Environment

Use only local Python 3.12.9.

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
Do not start TASK-005 until this section says ACCEPTED.
