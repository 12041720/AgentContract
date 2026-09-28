# TASK-004 — Claims, Evidence Graph, and Deterministic EvidenceGate

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-004-evidence-gate`  
**Main-agent review:** second-round changes requested

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
- **Evidence Graph (`src/agentcontract/evidence/graph.py`):**
  - Bidirectional index linking claims to supporting and contradicting evidence.
  - When re-evaluating/updating an existing claim, old reverse edges (`_event_to_claims` and `_trace_and_event_to_claims`) are purged before indexing new citations.
  - Preserves deterministic encounter order.
- **Packaging and Common Utilities:**
  - `FrozenDict.__hash__`: Fixed to preserve the standard Python equality/hash contract by hashing sorted items without object identity `id()` fallbacks; raises `TypeError` if contained values are unhashable.
  - Exported all evidence primitives in `src/agentcontract/evidence/__init__.py` and top-level `src/agentcontract/__init__.py`.

**Files changed:**  
- `src/agentcontract/common/immutable.py` (fixed `FrozenDict.__hash__` to preserve Python hash/equality contract without `id()` fallback)
- `src/agentcontract/evidence/gate.py` (enforced strict exact command matching, explicit existence fields for FILE_EXISTS, conjunctive execution resolution for FILE_EXISTS, and determine_verdict)
- `src/agentcontract/evidence/graph.py` (purged stale reverse edges on re-evaluation in `add_evaluation()`)
- `tests/evidence/test_gate.py` (updated Scenario 15, updated conjunctive command tests, added regression tests for files/changed_paths rejection, FILE_EXISTS execution selectors, and exact command matching)
- `tests/evidence/test_models.py` (added regression test for `FrozenDict` hash/equality contract)
- `.agent/tasks/TASK-004.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **132 passed in 0.87s** (100% pass rate: 35 constraint tests + 41 trace tests + 26 guard tests + 30 evidence tests).
- All 15 required test scenarios verified green, including all new regression tests.

**Known limitations:**  
- v0.1 claims evaluation operates in-memory against `TraceStore`. Persistent graph database storage is planned for subsequent milestones.
- Natural language claim extraction and prose entailment are reserved for TASK-006.

**Commit/PR:**  
- Branch: `task/TASK-004-evidence-gate`
- Implementation Commit SHA: `23830c1` (`23830c1dfefb0431e85cbecf594c09223ce52ebe`)

**Questions/blockers:**  
- None. All review blockers resolved and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED — ROUND 2 (FINAL NARROW FIXES)

**Reviewed implementation:** `855bfbb6545b596fd427f49b8c3e87f23a5944a6`

**Round-1 fixes verified:**
- GENERIC claims now stay UNVERIFIED.
- execution-backed claims require trace scope and deterministic single-execution resolution.
- call_id/tool_name/command are conjunctive for execution claims.
- ambiguous execution matches return UNVERIFIED.
- FrozenDict no longer uses identity-based hashing.
- EvidenceGraph removes stale reverse edges on claim replacement.
- contradiction precedence is now directly unit-tested through `determine_verdict()`.
- executor reports 130 tests passing on local Python 3.12.9.

### BLOCKER 1 — FILE_EXISTS still accepts fields that are not existence evidence

Executor Report says FILE_EXISTS strictly accepts structured existence fields such as:

```text
path + exists
created_paths
existing_paths
missing_paths
```

But implementation still treats these as support:

```python
changed_paths
files
```

and Scenario 15 still expects:

```python
output={"files": ["out.txt", "schema.sql"]}
```

to VERIFIED.

A file appearing in a generic `files` list does not prove existence; `changed_paths` also does not necessarily mean the path currently exists.

**Required fix:**
For v0.1 support only explicit existence semantics:
- exact `path/target/file + exists=True` -> SUPPORTS;
- exact `path/target/file + exists=False` -> CONTRADICTS;
- `created_paths` / `existing_paths` -> SUPPORTS;
- `missing_paths` / `deleted_paths` -> CONTRADICTS.

Remove `files`, `changed_paths`, and other generic arrays as existence proof.

Update Scenario 15 accordingly and add explicit regression tests that `files=[target]` and `changed_paths=[target]` remain UNVERIFIED.

### BLOCKER 2 — FILE_EXISTS does not enforce all supplied execution selectors

The FILE_EXISTS branch only narrows by `call_id`. If a claim supplies:

```text
call_id = c1
tool_name = stat
command = ...
```

the branch can still use c1 evidence even when its ToolCall has a different tool/command.

If no call_id is supplied, FILE_EXISTS currently ignores tool_name/command entirely and scans every event in the trace.

**Required fix:**
- When FILE_EXISTS includes execution selectors, they must be conjunctive just like other execution-backed claims.
- If `call_id` is supplied, validate the associated ToolCall against any supplied tool_name/command before accepting its result.
- If only tool_name/command are supplied, resolve deterministically; zero or multiple matching executions -> UNVERIFIED.
- A FILE_EXISTS claim with only `trace_id + target_path` may continue to behave as a trace-level state claim across explicit state observations.

Add tests for mismatching call_id+tool_name and ambiguous tool-only FILE_EXISTS claims.

### BLOCKER 3 — command matching is still prefix-based and can false-match

`_command_in_tool_call()` currently accepts:

```python
val.startswith(target_cmd)
```

So a claim for `pytest` can match a completely different command such as `pytestevil`.

For deterministic v0.1 verification, avoid fuzzy/prefix command semantics.

**Required fix:**
- use exact normalized command equality for v0.1, or an explicitly structured command representation;
- `pytest` must not match `pytestevil`;
- if you want `pytest` and `pytest -v` to be considered different, that is acceptable and safer for v0.1;
- add regression tests.

**Required re-check:**
- local Python 3.12.9 only;
- update the tests themselves so they express the stricter semantics;
- `python --version`;
- `python -m pytest -v`;
- TASK-001/002/003 suites remain green;
- update Executor Report with actual pushed commit SHA.

**Next instruction:**
Apply these three narrow fixes on `task/TASK-004-evidence-gate`. Do not start TASK-005.

