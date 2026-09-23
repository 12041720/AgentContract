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
