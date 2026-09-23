# Main-Agent Review Log

Append-only record of implementation reviews.

## 2026-09-22 — Repository initialization

**Verdict:** project scaffold established.

Reviewed:
- project mission and scope;
- persistent main-agent / execution-agent workflow;
- v0.1 architecture boundaries;
- initial roadmap;
- TASK-001 acceptance contract.

Next:
- execution agent implements TASK-001;
- main agent reviews its diff and tests before activating TASK-002.

---

## 2026-09-23 — TASK-001 first implementation review

**Implementation reviewed:** `0ce2fd897ba5e407407586fe67db987b3e182f6d`

**Verdict:** CHANGES_REQUESTED

**Blocking findings:**
- Python 3.11 compatibility is broken by Python 3.12-only `type ConstraintId = str` syntax, despite the project declaring Python 3.11+ support.
- Durable constraint/provenance/snapshot models are only shallow-frozen; nested lists/dicts remain externally mutable and can silently alter historical ledger state.

**Required hardening:**
- make lifecycle transitions involving `CONFLICTED` explicit and tested rather than relying on incidental `is_terminal` behavior;
- reject or explicitly normalize incompatible initial/replacement lifecycle states;
- run the full suite on Python 3.11 and the current development Python.

**Positive findings:**
- narrow vendor-neutral design;
- clear provenance and authority modeling;
- useful typed exceptions and supersession lineage;
- good initial round-trip/failure-path tests;
- no out-of-scope LLM/network/database work.

**Next:** execution agent fixes TASK-001 on `task/TASK-001-core-ledger`; TASK-002 remains blocked.

---

## 2026-09-23 — TASK-001 second implementation review

**Implementation reviewed:** `85f0195326a5dbba7f51ddf4863e0ba550affe28`

**Verdict:** CHANGES_REQUESTED — ROUND 2

**Verified improvements:**
- Python 3.11-compatible type alias adopted.
- Executor reports passing test suites on Python 3.11.12 and 3.12.9.
- tuple/deep-freezing work improved nested isolation.
- CONFLICTED lifecycle intent is now documented and partially tested.

**Remaining blockers:**
- `FrozenDict` subclasses `dict` and remains mutable through operations such as `|=` and base-class mutators; durable history therefore is not truly immutable.
- `ALLOWED_TRANSITIONS` is not the single enforcement source; `mark_conflicted` can currently permit state behavior not represented by the transition table.

**Next:** execution agent must replace the mutable-dict subclass approach, centralize transition validation, add bypass/table-driven tests, and resubmit TASK-001.

---

## 2026-09-23 — TASK-001 third implementation review

**Implementation reviewed:** `b1522169346945cb22a4be62bcf1cb2c2b0731a8`

**Verdict:** CHANGES_REQUESTED — ROUND 3 (FINAL HARDENING)

**Verified improvements:**
- composition-based `FrozenDict` blocks normal dict mutation paths;
- lifecycle validation is centralized through `validate_transition`;
- all 16 status-pair transitions are table-tested;
- CONFLICTED handling and peer preconditions are explicit.

**Remaining blockers:**
- `FrozenDict._data` is still a directly reachable mutable dictionary, so recorded metadata/provenance can still be mutated externally.
- public `ALLOWED_TRANSITIONS` is a mutable dictionary, allowing callers to rewrite lifecycle semantics at runtime.

**Next:** apply two narrow immutability fixes, rerun Python 3.11/3.12 suites, and resubmit. TASK-002 remains blocked.

---

## 2026-09-23 — TASK-001 final review and integration

**Final implementation reviewed:** `a3953f94fae767939c33d0cfcd0be904cc75adad`

**Verdict:** ACCEPTED

**Integration:**
- execution PR #1 was closed because persistent `.agent/*` state had intentionally diverged between main and the task branch;
- main agent created a clean integration branch containing only implementation/test changes;
- PR #2 was squash-merged to `main`;
- main integration commit: `48a7ae1cc07025a400b11804c298c2970cfc5107`.

**Final acceptance:**
- Python 3.11+ compatibility;
- deeply isolated immutable constraint/provenance metadata;
- read-only lifecycle transition policy;
- centralized lifecycle validation;
- version-preserving ledger semantics;
- executor-reported 33/33 tests passing on Python 3.11.12 and 3.12.9.

**Threat-model boundary:** interpreter-level sabotage/reflection intended solely to violate private implementation invariants is outside v0.1 immutability guarantees.

**Next:** TASK-002 — Unified trace and provenance model is active.

---

## 2026-09-23 — Development Python baseline correction

**Decision:** use the user's actual local development interpreter as the project test baseline.

- Local development Python: **3.12.9**.
- `pyproject.toml` now declares `requires-python = ">=3.12"`.
- Execution agents must not download alternate Python versions solely to satisfy a compatibility matrix unless the user explicitly requests it.
- TASK-002 instructs the executor to remove the uv-managed Python 3.11 installed only for prior compatibility testing, then run the suite once on local Python 3.12.9.
- Historical TASK-001 review records mentioning Python 3.11 remain unchanged because they describe what was actually tested at that time.

---

## 2026-09-23 — TASK-002 first implementation review

**Implementation reviewed:** `431534bd21ab62751a63b47db19d6368c5828a08`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- local Python 3.12.9 baseline followed and uv-managed 3.11 removed;
- shared immutable primitive extracted cleanly;
- strong initial trace identity/sequence/correlation model;
- pointer/filter/serialization paths implemented;
- executor reports 64/64 tests passing.

**Blocking findings:**
- TOOL_RESULT can contain contradictory provenance when `parent_id` points to a different tool call than `ToolResult.call_id`.
- `ToolResult.output: Any` can retain unsupported mutable objects such as `bytearray`, allowing recorded history to change after creation and weakening JSON durability guarantees.

**Next:** execution agent fixes TASK-002 on `task/TASK-002-trace-model`; TASK-003 remains blocked.

---
