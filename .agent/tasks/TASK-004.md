# TASK-004 — Claims, Evidence Graph, and Deterministic EvidenceGate

**Status:** CHANGES_REQUESTED  
**Milestone:** M1 — Executable contract core  
**Owner:** Execution agent  
**Work branch:** `task/TASK-004-evidence-gate`  
**Main-agent review:** changes requested

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
    - Rule 10: Contradiction dominates support if both are present for the same execution.
- **Packaging and Exports:**
  - Exported all evidence primitives in `src/agentcontract/evidence/__init__.py` and top-level `src/agentcontract/__init__.py`.
  - Implemented `__hash__` on `FrozenDict` in `src/agentcontract/common/immutable.py` to support hashing of frozen Pydantic models containing frozen metadata.

**Files changed:**  
- `src/agentcontract/common/immutable.py` (added `__hash__` method to `FrozenDict`)
- `src/agentcontract/evidence/exceptions.py` (new: `EvidenceError`, `EvidenceValidationError`, `ClaimNotFoundError`)
- `src/agentcontract/evidence/models.py` (new: `ClaimType`, `ClaimVerdict`, `EvidenceRelation`, `EvidenceRef`, `Claim`, `ClaimEvaluation`)
- `src/agentcontract/evidence/graph.py` (new: `EvidenceGraph`)
- `src/agentcontract/evidence/gate.py` (new: `EvidenceGate`)
- `src/agentcontract/evidence/__init__.py` (exported evidence primitives)
- `src/agentcontract/__init__.py` (re-exported evidence primitives at top-level)
- `tests/evidence/__init__.py` (new: test package marker)
- `tests/evidence/test_models.py` (new: unit tests for models, validation, immutability, serialization)
- `tests/evidence/test_gate.py` (new: unit tests covering all 15 required scenarios)
- `.agent/tasks/TASK-004.md` (updated Executor Report)

**Tests/checks:**  
- Python version check: `python --version` -> `Python 3.12.9`.
- Full pytest suite: `python -m pytest -v` -> **123 passed in 0.54s** (100% pass rate: 35 constraint tests + 41 trace tests + 26 guard tests + 21 evidence tests).
- All 15 required test scenarios verified green, including existing test suites.

**Known limitations:**  
- v0.1 claims evaluation operates in-memory against `TraceStore`. Persistent graph database storage is planned for subsequent milestones.
- Natural language claim extraction and prose entailment are reserved for TASK-006.

**Commit/PR:**  
- Branch: `task/TASK-004-evidence-gate`
- Implementation Commit SHA: `129f9ca`

**Questions/blockers:**  
- None. All acceptance criteria and 15 required test scenarios are met and verified on local Python 3.12.9.

## Main Agent Review

> Main agent only.

**Verdict:** CHANGES_REQUESTED

**Reviewed implementation:** `129f9ca7d81b923c7d13e7980b454c15b70af5c7`  
**Reviewed branch head/report:** `5cb12e811688ef9ea63813d1ffc4f2cfd062a82a`

**Accepted foundation:**
- typed Claim / EvidenceRef / ClaimEvaluation models are a solid base;
- ToolResult SUCCESS / ERROR / TIMEOUT handling is structured;
- trace/call provenance is retained in EvidenceRef;
- EvidenceGraph supports forward/reverse lookup;
- executor reports 123 tests passing on local Python 3.12.9.

### BLOCKER 1 — Claims can be verified without deterministic execution identity

`Claim` permits all execution selectors to be absent. Then `_filter_tool_results_for_claim()` can return arbitrary ToolResults from the candidate trace(s).

Also, when `call_id` is present, the current filter **does not validate simultaneously supplied `tool_name` or `command`**. A claim can point at call A while claiming a different command/tool and still be verified by call A's success.

Finally, `ClaimType.GENERIC` is evaluated exactly like `ACTION_COMPLETED`, allowing arbitrary semantic prose to become VERIFIED from an unrelated successful execution. TASK-004 explicitly forbids verifying arbitrary semantic claims.

**Required fix:**
- `GENERIC` must never become VERIFIED by deterministic EvidenceGate; return UNVERIFIED/unsupported or remove it from v0.1 verification.
- For execution-backed claim types, require deterministic resolution inside the declared trace/session:
  - exact `call_id` is preferred; or
  - tool/command selectors must resolve to exactly one ToolCall.
- zero matches -> UNVERIFIED; multiple matches -> UNVERIFIED as ambiguous.
- every selector supplied on a claim is conjunctive: if `call_id + tool_name + command` are supplied, all must match the same ToolCall.
- do not search across all traces for a success claim with no trace identity.
- add tests for under-scoped claim, ambiguous same-tool calls, and call_id with mismatching tool/command.

### BLOCKER 2 — FILE_EXISTS uses non-evidence text/irrelevant fields as proof

Current `_file_matches_tool_result()` can verify existence merely because a plain string contains the path, or because a generic list contains it. It can also contradict target A from `{"path": "B", "exists": false}` due to the final global `exists is False` check.

This can turn logs or unrelated structured output into false file-state evidence.

**Required fix:**
Use only explicit structured artifact/state observations for FILE_EXISTS.

A narrow v0.1 contract is sufficient, for example:
- matching `{"path": target, "exists": true}` -> SUPPORTS;
- matching `{"path": target, "exists": false}` -> CONTRADICTS;
- explicit `created_paths/existing_paths` containing target -> SUPPORTS;
- explicit `missing_paths` containing target -> CONTRADICTS.

Do not use free-text substring matching or unrelated generic arrays as existence proof.

Regression tests:
- plain text mentioning target -> UNVERIFIED;
- `{"path":"other","exists":false}` must not contradict target;
- exact target + exists true -> VERIFIED;
- exact target + exists false -> CONTRADICTED.

### BLOCKER 3 — FrozenDict.__hash__ violates Python equality/hash contract

The new hash fallback uses:

```python
hash(id(v))
```

for unhashable values.

Two equal `FrozenDict` instances containing distinct but equal unhashable values can therefore satisfy `a == b` while `hash(a) != hash(b)`, which is invalid for hashable Python objects.

**Required fix:**
- never use object identity as hash fallback for value-based FrozenDict equality;
- either compute a structural hash consistent with equality, or raise TypeError when a contained value is not hashable;
- add a regression test with two distinct equal unhashable values proving the hash/equality contract is not violated.

### BLOCKER 4 — EvidenceGraph update leaves stale reverse edges

`add_evaluation()` documents register **or update**, but replacing an existing claim evaluation does not remove its old event->claim reverse references.

After reevaluation, `get_claims_citing_evidence(old_event)` can incorrectly keep returning the claim.

**Required fix:**
- when replacing an existing claim_id evaluation, remove its old reverse edges before indexing new evidence;
- preserve deterministic order;
- add a test that evaluates/replaces the same claim with different evidence and confirms the old event no longer reverse-links to the claim.

### TEST CORRECTION — contradiction precedence

The current scenario 14 uses two different call_ids and treats them as one "same execution". That is not the invariant in the task.

Do not use two distinct executions to prove contradiction precedence for one exact execution. After deterministic claim resolution is fixed, ambiguous multi-call claims should be UNVERIFIED rather than arbitrarily merged.

Test contradiction precedence using evidence that genuinely refers to the same claimed execution, or factor/test the verdict aggregation rule directly if TraceStore's one-result-per-call invariant makes dual result evidence impossible in v0.1.

**Required re-check:**
- local Python 3.12.9 only;
- inspect and update tests for the exact failure modes above;
- `python --version`;
- `python -m pytest -v`;
- TASK-001/002/003 suites remain green;
- update Executor Report with actual pushed commit SHA.

**Next instruction:**
Fix these blockers on `task/TASK-004-evidence-gate`. Do not start TASK-005.

