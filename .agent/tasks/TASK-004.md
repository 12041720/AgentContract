# TASK-004 — Claims, Evidence Graph, and Deterministic EvidenceGate

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-004-evidence-gate`  
**Main-agent review:** third-round final state-semantics fix requested

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
- **Environment Baseline:** Developed and tested exclusively on the user's installed local **Python 3.12.9** baseline (`python --version` -> `Python 3.12.9`).
- **Domain Models & Invariants (`src/agentcontract/evidence/models.py`):**
  - `ClaimVerdict`: Enum (`VERIFIED`, `CONTRADICTED`, `UNVERIFIED`).
  - `ClaimType`: Enum supporting `TOOL_SUCCEEDED`, `COMMAND_EXITED_ZERO`, `TESTS_PASSED`, `FILE_EXISTS`, `ACTION_COMPLETED`, and `GENERIC`.
  - `EvidenceRelation`: Enum (`SUPPORTS`, `CONTRADICTS`, `NEUTRAL`).
  - `EvidenceRef`: Immutable pointer model linking to exact `TracePointer`, preserving `call_id`, `event_kind`, `relation`, `reason`, and frozen `metadata`.
  - `Claim`: Immutable atomic claim representation capturing claim identity, type, description, trace/session/call scope, tool/command parameters, expected exit code, and UTC timestamp.
  - `ClaimEvaluation`: Immutable verdict container recording evaluated claim, verdict, ordered supporting & contradicting evidence tuples, explanation reason, and UTC timestamp. Strictly rejects unordered `set`/`frozenset` inputs for evidence sequences.
- **Evidence Graph (`src/agentcontract/evidence/graph.py`):**
  - Bidirectional index linking claims to supporting and contradicting evidence.
  - Reverse lookup: `get_claims_citing_evidence(event_id, trace_id=...)` returns all claims citing a given trace event in deterministic encounter order.
  - Resolves `TracePointer` to concrete `TraceEvent` against `TraceStore`.
- **Deterministic EvidenceGate (`src/agentcontract/evidence/gate.py`):**
  - `evaluate(claim, trace_store)` and `evaluate_many(claims, trace_store)`.
  - Strict deterministic rules enforced:
    - Rule 1: `AGENT_MESSAGE` events are never evidence by themselves (an agent claiming "tests passed" yields `UNVERIFIED` without backing tool results).
    - Rule 2: Missing trace evidence yields `UNVERIFIED`.
    - Rule 3: Contradictory evidence (ERROR, TIMEOUT, CANCELLED, exit_code != expected) yields `CONTRADICTED`.
    - Rule 4: Matching success evidence yields `VERIFIED`.
    - Rule 5: Non-zero exit code or tool failure status cannot verify success.
    - Rule 6: For exit code claims, only observed matching results with exit_code == 0 (or expected) verify success.
    - Rule 7/8: Trace and call identity isolation: evidence from another trace or call_id cannot satisfy a scoped claim.
    - Rule 9: One evidence event can independently support multiple claims, while evaluations retain individual provenance.
    - Rule 10: Contradiction dominates support for the same execution or target observation.
    - Rule 11: `GENERIC` claims are never verified by deterministic `EvidenceGate` (returns `UNVERIFIED`).
    - Rule 12: Execution claims require deterministic identity resolution; 0 or multiple ambiguous matches return `UNVERIFIED`.
    - Rule 13: Claim selectors (`call_id`, `tool_name`, `command`) are strictly conjunctive and must all match the same execution.
    - Rule 14: `FILE_EXISTS` strictly requires structured file observation (`path/target/file + exists=True/False`, `created_paths`, `existing_paths`, `missing_paths`, `deleted_paths`). Generic arrays such as `files` and `changed_paths` are rejected.
    - Rule 15: If `FILE_EXISTS` specifies execution selectors (`call_id`, `tool_name`, `command`), they are conjunctive and must resolve to a unique execution (0 or >1 matches return `UNVERIFIED`).
    - Rule 16: Command matching uses strict normalized equality (`==`); prefix matching (`startswith`) is strictly forbidden.
    - Rule 17: Trace-level `FILE_EXISTS` claims (`trace_id + target_path`, no execution selectors) enforce temporal ordering by evaluating explicit file-state observations in trace sequence order; authoritative verdict is governed by the latest explicit observation for that target (missing -> created yields `VERIFIED`, created -> missing yields `CONTRADICTED`, unrelated subsequent observations do not alter state). Execution-scoped `FILE_EXISTS` continues evaluating only the uniquely resolved execution.
- **Evidence Graph (`src/agentcontract/evidence/graph.py`):**
  - Bidirectional index linking claims to supporting and contradicting evidence.
  - When re-evaluating/updating an existing claim, old reverse edges (`_event_to_claims` and `_trace_and_event_to_claims`) are purged before indexing new citations.
  - Preserves deterministic encounter order.
- **Packaging and Common Utilities:**
  - `FrozenDict.__hash__`: Fixed to preserve the standard Python equality/hash contract by hashing sorted items without object identity `id()` fallbacks; raises `TypeError` if contained values are unhashable.
  - Exported all evidence primitives in `src/agentcontract/evidence/__init__.py` and top-level `src/agentcontract/__init__.py`.

**Files changed:**  
- `src/agentcontract/common/immutable.py` (fixed `FrozenDict.__hash__` to preserve Python hash/equality contract without `id()` fallback)
- `src/agentcontract/evidence/gate.py` (enforced strict exact command matching, explicit existence fields for FILE_EXISTS, conjunctive execution resolution for FILE_EXISTS, temporal ordering for trace-level FILE_EXISTS, and determine_verdict)
- `src/agentcontract/evidence/graph.py` (purged stale reverse edges on re-evaluation in `add_evaluation()`)
- `tests/evidence/test_gate.py` (updated Scenario 15, updated conjunctive command tests, added regression tests for files/changed_paths rejection, FILE_EXISTS execution selectors, exact command matching, and trace-level FILE_EXISTS temporal ordering)
- `tests/evidence/test_models.py` (added regression test for `FrozenDict` hash/equality contract)
- `.agent/tasks/TASK-004.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **133 passed in 0.70s** (100% pass rate: 35 constraint tests + 41 trace tests + 26 guard tests + 31 evidence tests).
- All 15 required test scenarios verified green, including all new regression tests.

**Known limitations:**  
- v0.1 claims evaluation operates in-memory against `TraceStore`. Persistent graph database storage is planned for subsequent milestones.
- Natural language claim extraction and prose entailment are reserved for TASK-006.

**Commit/PR:**  
- Branch: `task/TASK-004-evidence-gate`
- Implementation Commit SHA: pending push

**Questions/blockers:**  
- None. All review blockers resolved and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — ROUND 3 (FINAL STATE-ORDERING FIX)

**Reviewed implementation:** `23830c1dfefb0431e85cbecf594c09223ce52ebe`

**Round-2 fixes verified:**
- FILE_EXISTS no longer accepts generic `files` or `changed_paths` arrays as existence proof.
- FILE_EXISTS execution selectors now resolve conjunctively and uniquely.
- command matching is exact; prefix matches are rejected.
- executor reports 132 tests passing on local Python 3.12.9.

### FINAL BLOCKER — trace-level FILE_EXISTS ignores temporal ordering

For a trace-level FILE_EXISTS claim (no execution selector), the gate scans all explicit observations and accumulates both support and contradiction. The global rule then makes any contradiction dominate any support.

That is wrong for a state claim when observations occur at different times.

Example:

```text
sequence 1: missing_paths = ["x.txt"]
sequence 3: created_paths = ["x.txt"]
```

At the end of the trace, the latest explicit observation says the file exists. Current logic still returns CONTRADICTED because historical contradiction always dominates.

The task's contradiction-precedence rule applies to conflicting evidence for the **same exact claimed execution**, not to stale historical state observations.

**Required fix:**
- For FILE_EXISTS with explicit execution selectors: keep evaluating only the uniquely resolved execution result.
- For trace-level FILE_EXISTS (`trace_id + target_path`, no execution selectors): evaluate explicit file-state observations in trace sequence order and use the **latest explicit observation for that target** as the authoritative state.
- Earlier state evidence may be retained as provenance/history if useful, but must not override a later explicit state.
- If latest explicit state says exists -> VERIFIED.
- If latest explicit state says missing/deleted -> CONTRADICTED.
- If no explicit state observation -> UNVERIFIED.
- If one single event internally contains both support and contradiction for the same target, contradiction may still dominate for that event.

**Required tests:**
1. missing first, created later -> VERIFIED;
2. created first, missing later -> CONTRADICTED;
3. unrelated later observations do not change target state;
4. execution-scoped FILE_EXISTS behavior remains unchanged.

**Required re-check:**
- local Python 3.12.9 only;
- `python --version`;
- `python -m pytest -v`;
- TASK-001/002/003 suites remain green;
- update Executor Report with actual pushed commit SHA.

**Next instruction:**
Apply this final narrow fix on `task/TASK-004-evidence-gate`. Do not start TASK-005.

