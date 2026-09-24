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

## 2026-09-24 — TASK-002 second implementation review

**Implementation reviewed:** `9f60435eb74a86c2811accc2c57440381ffab9aa`

**Verdict:** CHANGES_REQUESTED — ROUND 2 (NARROW DURABILITY FIX)

**Verified fixes:**
- TOOL_RESULT parent/call provenance is now consistent.
- arbitrary mutable/custom tool outputs are rejected.
- blank pointer session IDs are rejected.
- executor reports 71/71 tests passing on local Python 3.12.9.

**Remaining issue:**
- durable value semantics are inconsistent for set/frozenset and non-finite floats; serialization can change value/type across round-trip.
- TraceEvent payload normalization accepts/promises a broader domain than its Pydantic field annotation declares.

**Next:** narrow and align the durable value domain, add strict round-trip tests, then resubmit TASK-002. TASK-003 remains blocked.

---

## 2026-09-24 — TASK-002 final review and integration

**Final implementation reviewed:** `7518701badfd7db18a9994f6eab21987f1282b1d`

**Verdict:** ACCEPTED

**Integration commit:** `2c71b2509dc82a95a2c3ce298602811f549ac1ff`

**Final acceptance:**
- unified vendor-neutral trace/event model;
- strict event identity and per-trace sequence integrity;
- tool-call/result correlation with unambiguous parent provenance;
- immutable JSON-durable trace value domain;
- exact semantic round-trip for supported values;
- TracePointer and deterministic query/filter support;
- TASK-001 compatibility preserved;
- executor-reported 74/74 tests passing on local Python 3.12.9.

**Next:** TASK-003 — SpecGuard pre/post action validation engine is active.

---

## 2026-09-24 — TASK-003 first implementation review

**Implementation reviewed:** `033eed532a47a9d735b2ea7e3aa4008e4cb5797d`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- solid Action / Observation / Decision model;
- ACTIVE-only enforcement;
- deterministic BLOCK > WARN > ALLOW aggregation;
- correct DENY handling across HARD/SOFT/ASSUMPTION;
- pre/post APIs and TracePointer provenance implemented;
- executor reports 99/99 tests passing on local Python 3.12.9.

**Blocking findings:**
- REQUIRE/PREFER semantics punish matching compliant actions instead of detecting missing compliance;
- selector "exact match" coerces values through strings and loses type semantics;
- post-action validation discards accessed effects when changed paths are present;
- set/frozenset inputs can make serialized/order-sensitive decisions nondeterministic.

**Next:** execution agent fixes TASK-003 on `task/TASK-003-specguard`; TASK-004 remains blocked.

---

## 2026-09-24 — TASK-003 second implementation review

**Reviewed branch head:** `9146c0e98e5446762c635252f0bf064e7eea62e9`

**Verdict:** CHANGES_REQUESTED — ROUND 2

**Verified fixes:**
- applicability/compliance semantics introduced for REQUIRE/PREFER;
- post-action writes/reads evaluated independently;
- unordered order-sensitive inputs rejected;
- executor reports 100/100 tests passing on local Python 3.12.9.

**Remaining blockers:**
- exact selector equality still treats int and float as equal and is not recursively type-strict for nested values;
- REQUIRE/PREFER without `compliance_scope` silently become no-op rules instead of failing validation.

**Review-process note:** Executor Report referenced non-remote SHA `b9b4c05`; actual pushed branch head was `9146c0e98e5446762c635252f0bf064e7eea62e9`.

**Next:** apply the two narrow fixes and resubmit TASK-003. TASK-004 remains blocked.

---

## 2026-09-24 — TASK-003 final review and integration

**Final implementation reviewed:** `cf80fd45246e74a11c11798022e2e7ef0797a236`

**Verdict:** ACCEPTED

**Integration commit:** `495b23b262d51e076ad2f6c36b81edba4169f4d4`

**Final acceptance:**
- deterministic DENY / REQUIRE / PREFER rule semantics;
- explicit applicability vs compliance scopes;
- recursive exact typed selector matching;
- REQUIRE/PREFER model validation prevents silent no-op configuration;
- all observed post-action read/write/tool effects are evaluated;
- deterministic decision ordering and aggregation;
- executor-reported 102/102 tests passing on local Python 3.12.9.

**Next:** TASK-004 — deterministic EvidenceGate core is active.

---

## 2026-09-24 — TASK-004 first implementation review

**Implementation reviewed:** `129f9ca7d81b923c7d13e7980b454c15b70af5c7`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- typed claims/evidence/evaluations;
- ToolResult status-based verification;
- trace/call provenance retained;
- bidirectional EvidenceGraph foundation;
- executor reports 123/123 tests passing on local Python 3.12.9.

**Blocking findings:**
- under-scoped claims and GENERIC claims can be incorrectly VERIFIED;
- call_id currently bypasses simultaneously supplied tool/command selectors;
- FILE_EXISTS accepts free text/unrelated output as file-state evidence;
- FrozenDict identity-based hash fallback violates equality/hash contract;
- reevaluating a claim can leave stale EvidenceGraph reverse edges;
- contradiction precedence test incorrectly merges distinct executions.

**Next:** execution agent fixes TASK-004 on `task/TASK-004-evidence-gate`; TASK-005 remains blocked.

---
