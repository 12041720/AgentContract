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
