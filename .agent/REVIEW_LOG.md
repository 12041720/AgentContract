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

## 2026-09-28 — TASK-004 second implementation review

**Implementation reviewed:** `855bfbb6545b596fd427f49b8c3e87f23a5944a6`

**Verdict:** CHANGES_REQUESTED — ROUND 2

**Verified fixes:**
- GENERIC claims remain UNVERIFIED;
- deterministic single-execution resolution and conjunctive selectors for execution claims;
- ambiguous executions remain UNVERIFIED;
- FrozenDict hash/equality contract repaired;
- stale EvidenceGraph reverse edges cleared on replacement;
- contradiction precedence factored and directly unit-tested;
- executor reports 130/130 tests passing on local Python 3.12.9.

**Remaining narrow issues:**
- FILE_EXISTS still treats generic `files` and `changed_paths` arrays as existence evidence;
- FILE_EXISTS does not enforce supplied tool/command selectors consistently;
- command matching still uses unsafe prefix semantics.

**Next:** apply the three narrow fixes and resubmit TASK-004. TASK-005 remains blocked.

---

## 2026-09-28 — TASK-004 third implementation review

**Implementation reviewed:** `23830c1dfefb0431e85cbecf594c09223ce52ebe`

**Verdict:** CHANGES_REQUESTED — ROUND 3

**Verified fixes:**
- FILE_EXISTS accepts only explicit existence semantics;
- FILE_EXISTS execution selectors are conjunctive and deterministic;
- command matching is exact instead of prefix-based;
- executor reports 132/132 tests passing on local Python 3.12.9.

**Final blocker:**
- trace-level FILE_EXISTS aggregates stale historical support/contradiction and lets any old contradiction override later state; state claims must respect event sequence and use the latest explicit observation for the target.

**Next:** apply the final temporal-ordering fix and resubmit TASK-004. TASK-005 remains blocked.

---

## 2026-09-28 — TASK-004 final review and integration

**Final implementation reviewed:** `3209bb52c0c311d3a6051611ef56942b0a85a939`

**Verdict:** ACCEPTED

**Integration commit:** `f93c5f70e93e4d2ef8341c719dba66f951ed8e03`

**Final acceptance:**
- deterministic typed EvidenceGate verdicts;
- exact execution identity and conjunctive selectors;
- strict structured FILE_EXISTS evidence;
- trace-level FILE_EXISTS uses latest explicit state by sequence;
- stale graph edges and FrozenDict hash contract repaired;
- executor-reported 133/133 tests passing on local Python 3.12.9.

**Next:** TASK-005 — agent/tool runtime wrapper and end-to-end demo is active.

---

## 2026-09-28 — TASK-005 first implementation review

**Implementation reviewed:** `4e028fe6f98d9e6bdb57239128033031150e755e`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- synchronous runtime wrapper connects SpecGuard, TraceStore, tool execution, post-action validation, and EvidenceGate;
- BLOCK/WARN/ALLOW paths exist;
- correlated ToolCall/ToolResult tracing exists;
- executor failures become ERROR evidence;
- executor reports 154/154 tests passing on local Python 3.12.9.

**Blocking findings:**
- internal executor TypeError can trigger multiple executor invocations due to signature fallback/retry logic;
- actual `target_type` reported by ToolExecutionOutcome is dropped before post-action SpecGuard;
- Executor Report contains an incorrect full commit SHA; actual implementation commit is `4e028fe6f98d9e6bdb57239128033031150e755e`.

**Next:** execution agent fixes TASK-005 on `task/TASK-005-runtime-wrapper`; TASK-006 remains blocked.

---

## 2026-09-28 — TASK-005 second implementation review

**Implementation reviewed:** `77281cfaba5ca6256cfd97d9c28f7e613958ac4c`

**Verdict:** CHANGES_REQUESTED — ROUND 2

**Verified fixes:**
- executor internal TypeError does not trigger retry;
- executor arguments are bound before one invocation;
- actual target_type reaches post-action SpecGuard;
- target_type mismatch can produce post-action BLOCK;
- executor reports 157/157 tests passing on local Python 3.12.9.

**Remaining narrow issues:**
- `RuntimeExecutionResult.executed` is true even when signature validation fails before executor invocation;
- `ToolExecutionOutcome.success()/from_tool_result()` convert unordered sets to tuples before validation and bypass deterministic-order rejection.

**Next:** apply the two narrow fixes and resubmit TASK-005. TASK-006 remains blocked.

---

## 2026-09-28 — TASK-005 final review and integration

**Final implementation reviewed:** `4f9946b074445aa2f68671f83899b7f40e718647`

**Verdict:** ACCEPTED

**Integration commit:** `94ec3c32dc685528fa5265e11c8945b16fdbc6b4`

**Final acceptance:**
- full synchronous runtime loop connects constraints, SpecGuard, tool execution, trace, post-action validation, and EvidenceGate;
- executor invocation is exactly-once;
- pre-binding failures report `executed=False`, body failures report `executed=True`;
- post-action observed target_type is enforced;
- unordered path sets cannot bypass durable ordering validation;
- executor-reported 158/158 tests passing on local Python 3.12.9.

**Next:** TASK-006 — LLM-assisted requirement/claim extraction adapters is active.

---

## 2026-09-28 — TASK-006 first implementation review

**Implementation reviewed:** `d7de73d40c97cf5234700d75ef6e1734f784ce47`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- provider-neutral structured extraction protocol;
- separate untrusted draft models and durable domain models;
- caller trace/session and requirement provenance override model proposals;
- claims remain unverified until deterministic EvidenceGate evaluation;
- no automatic ledger mutation;
- executor reports 186/186 tests passing on local Python 3.12.9.

**Blocking findings:**
- omitted authority/strength/effect/scope can silently become USER/HARD/global DENY;
- draft models silently ignore unexpected model fields;
- scope list values are string-coerced instead of strictly validated;
- per-instance deterministic default ID generators can collide across extractor instances.

**Hardening requested:**
- complete spoof diagnostics for caller-owned provenance/scope fields.

**Next:** execution agent fixes TASK-006 on `task/TASK-006-extraction-adapters`; TASK-007 remains blocked.

---

## 2026-09-28 — TASK-006 final review and integration

**Final implementation reviewed:** `0e8c33a86f0533b6016e9350f46ab708ee17abb6`

**Verdict:** ACCEPTED

**Integration commit:** `cc61b75d34e75ea47ee2f289874a719bf4be247f`

**Final acceptance:**
- caller authority/source must be explicit;
- no unsafe HARD/DENY/global defaults;
- unknown model fields are forbidden;
- scope item types are strict and non-coercive;
- default IDs are collision-resistant;
- spoofed provenance/trace/session/IDs cannot affect durable objects;
- claims remain subject to deterministic EvidenceGate verification;
- executor-reported 195/195 tests passing on local Python 3.12.9.

**Milestone:** M2 Working AgentContract demo complete.

**Next:** TASK-007 — benchmark scenarios and reliability metrics is active.

---

## 2026-09-28 — TASK-007 first benchmark review

**Implementation reviewed:** `57169def3d64024a4f96a205db80005cc184b9f9`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- four isolated benchmark variants;
- 12 deterministic scenario classes;
- typed serializable benchmark models;
- metric aggregation and zero-denominator handling;
- actual local benchmark table reported;
- executor reports 218/218 tests passing on local Python 3.12.9.

**Blocking findings:**
- TSR is contaminated by claim acceptance/EvidenceGate verdicts instead of being independent scenario task truth;
- Extra Tool Calls is currently just executed-violation count;
- FBR counts post-action BLOCK even though the action already executed;
- aggregate tests hard-code FULL_AGENTCONTRACT as the winner;
- repeated-run test does not compare repetitions;
- latency overhead clips negative measured deltas to zero.

**Hardening requested:**
- validate positive repetitions, unique scenario IDs, and unique variants.

**Next:** fix TASK-007 benchmark semantics and rerun the real benchmark; TASK-008 remains blocked.

---

## 2026-09-28 — TASK-007 final review and integration

**Final implementation reviewed:** `6b035b5af57241a1be5d22e7e5e122ed9431260b`

**Verdict:** ACCEPTED

**Integration commit:** `12dad52df4b2901905c2ea92c07f8a71d2934d7f`

**Final acceptance:**
- four benchmark variants remain isolated;
- 13 deterministic scenarios;
- TSR/UCR semantics decoupled;
- extra tool-call metric uses explicit scenario ground truth;
- FBR counts only false pre-action prevention;
- repetitions compare deterministic semantic outputs;
- benchmark tests do not hard-code a winner;
- signed latency delta retained;
- executor-reported 222/222 tests passing on local Python 3.12.9.

**Milestone:** M3 Measurable reliability complete.

**Next:** TASK-008 — external integrations and telemetry is active.

---

## 2026-09-29 — TASK-008 first integration review

**Implementation reviewed:** `8a11a0c079926c2f98a1f01df380aef2b8484429`

**Verdict:** CHANGES_REQUESTED

**Verified strengths:**
- external tool adapter boundary;
- exactly-once OpenAI-compatible extraction HTTP request;
- provider output remains untrusted and caller authority remains enforced;
- offline/online quickstart path exists;
- executor reports 253/253 tests passing on local Python 3.12.9.

**Blocking findings:**
- OTLP JSON uses arbitrary AgentContract IDs directly as OTLP traceId/spanId, which violates OTLP wire ID format;
- external changed/accessed paths silently stringify malformed non-string values.

**Hardening requested:**
- configurable schema-enforced Structured Outputs mode, without hidden retries.

**Next:** fix TASK-008 narrow integration issues; TASK-009 remains blocked.

---

## 2026-09-29 — TASK-008 second integration review

**Implementation reviewed:** `0a148bb2a9c40142fce59cab1462d3e7047f9e03`

**Verdict:** CHANGES_REQUESTED — FINAL API COMPATIBILITY FIX

**Verified fixed:**
- valid deterministic OTLP wire IDs;
- original AgentContract correlation IDs preserved;
- strict external path typing;
- configurable json_schema/json_object request mode;
- exactly one provider request, no hidden retries.

**Remaining blocker:**
- core extraction JSON Schemas are not strict OpenAI Structured Outputs compatible: not all properties are required and at least one nested object remains open/free-form.

**Next:** make the actual schema sent by the OpenAI adapter strict-compatible, update quickstart env configuration, rerun tests. TASK-009 remains blocked.

---

## 2026-09-29 — TASK-008 final review and integration

**Final implementation reviewed:** `47fd8ffa4a7bfa9f27cb69e01dce6d6ff0583934`

**Verdict:** ACCEPTED

**Integration commit:** `0469bf7a0204eba56aaa2fe44d65edfb63b8b4ac`

**Final acceptance:**
- external tool adapters and strict path typing;
- deterministic valid OTLP wire IDs with original IDs preserved;
- OpenAI-compatible exactly-once structured extraction client;
- strict Structured Outputs compatible provider schemas;
- JSON mode compatibility fallback;
- online/offline quickstart environment configuration;
- executor-reported 268/268 tests passing on local Python 3.12.9.

**Next:** TASK-009 — CLI/API packaging and documentation is active.

---

## 2026-09-29 — TASK-009 scope expanded after live provider trial

**Status:** READY_FOR_EXECUTOR

A live OpenAI-compatible `deepseek-v4-flash` requirement-extraction run reached the real provider successfully and returned valid JSON, but exposed semantic integration failures before runtime enforcement:

- provider emitted REQUIRE constraints without non-empty `compliance_scope`, correctly rejected by domain validation;
- provider emitted `target_type="file"`, which can fail exact runtime target-type matching and make a syntactically valid DENY constraint ineffective.

TASK-009 now includes final real-provider extraction hardening before CLI/package/documentation completion.

Additional acceptance requirements include:
- task-specific extraction guidance for AgentContract semantics;
- end-to-end proof that extracted critical DENY constraints actually BLOCK matching runtime actions;
- no silent semantic repair of untrusted provider output;
- `OPENAI_TIMEOUT` support;
- manual OpenAI-compatible smoke test after automated tests.

---

## 2026-09-29 — TASK-009 first final review

**Implementation reviewed:** `460c1357ce3cc26b04d70095efe9e27ef038bf8f`

**Verdict:** CHANGES_REQUESTED

**Verified:**
- real provider returned durable critical DENY;
- SpecGuard blocked protected FILE_WRITE before execution;
- safe actions remained executable;
- REQUIRE/PREFER guidance and timeout configuration added;
- CLI/package entry point exists;
- executor reports 284 tests passing.

**Blocking findings:**
- claim prompt advertises unsupported FILE_MODIFIED / FILE_ABSENT values not present in ClaimType/schema;
- real pytest success claim remains UNVERIFIED because extraction omitted deterministic selectors;
- README falsely claims automatic conflict detection although current ledger requires explicit conflict marking;
- original TASK-009 acceptance still lacks concrete invalid-online-config, README-command, and built-package smoke checks.

**Next:** narrow final fixes on TASK-009 branch; v0.1 remains unaccepted.

---

## 2026-09-30 — TASK-009 final review and v0.1 completion

**Final implementation reviewed:** `9cdbea938a588a0bbd5a0cb93d9cf04a71771679`

**Final branch head/report:** `c9e066081c0747094a2763daa1ad981deac39e86`

**Verdict:** ACCEPTED

**Integration commit:** `6c24d9f749e0249a8a75da89effccbdcdb5c6e5e`

**Verified end-to-end outcome:**
- critical protected-file write -> BLOCK before execution;
- genuine pytest success claim -> VERIFIED from trace ToolResult;
- fabricated protected-file existence claim -> UNVERIFIED;
- safe actions remain executable;
- provider claim vocabulary matches domain ClaimType/schema;
- README corrected to explicit conflict lifecycle and implemented claim types;
- CLI/package surfaces are installable and documented;
- executor reports 288/288 tests passing on Python 3.12.9;
- executor reports clean wheel build and isolated package import/CLI smoke test;
- live OpenAI-compatible `deepseek-v4-flash` smoke test passed the v0.1 acceptance path.

**Milestone:** AgentContract v0.1 complete.

---

## 2026-09-30 — TASK-010 first real Codex integration review

**Actual branch head reviewed:** `1d1600b29f54b9272b169e68a5f3e5fc5e9de49c`

**Verdict:** CHANGES_REQUESTED

**Verified progress:**
- real Codex lifecycle hook integration exists for SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/Stop;
- real Codex CLI acceptance run was performed;
- protected-file attempts were observed and file hash remained unchanged in the reported run;
- PostToolUse trace/evidence and Stop EvidenceGate plumbing are present;
- executor reports 313 tests passing.

**Blocking findings:**
- configured OpenAICompatibleExtractionClient is never actually used because adapter calls nonexistent extract_requirements/extract_claims methods and silently falls back to regex;
- PreToolUse response emits unsupported Codex fields such as continue and legacy approve, conflicting with current official hook semantics;
- required opaque/destructive Bash fail-closed/approval policy is not implemented;
- session store has atomic file replacement but no cross-process transaction lock, so concurrent hooks can lose state;
- standalone plugin manifest shape needs alignment with the current documented Codex plugin contract.

**Next:** fix on `task/TASK-010-codex-hooks`, rerun full tests and a real Codex session, and report exact final branch SHA.

---

## 2026-10-08 — TASK-010 second review

**Review head:** `1b3a86140078e42f604f05dbe391ba06ea92e549`  
**Implementation:** `af244867eb83f0e6adab49eeab13bd3693157ece`  
**Verdict:** CHANGES_REQUESTED

Previous five blockers have received material fixes: configured provider extraction, Codex PreToolUse supported deny JSON, opaque shell heuristics, per-session cross-process file lock, and plugin compatibility layout. Executor reports 321 passing tests and a live Codex session with DENY/VERIFIED/UNVERIFIED outcomes.

New blocking correctness issues:
1. Unknown/dynamic shell command syntax defaults to non-opaque and can allow protected writes through variable-derived paths.
2. Mixed apply_patch is classified with one action kind; an unrelated Delete File header suppresses FILE_WRITE constraints on other paths.
3. Corrupted persisted ledger is silently reset to empty, eliminating HARD protections.
4. Test and packaging gaps: only thread concurrency test for a cross-process contract, and plugin manifest/discovery not fully compliant/verified.

See Main Agent Review in `.agent/tasks/TASK-010.md` for exact fixes. No main merge.

---

## 2026-10-08 — TASK-010 third review

**Reviewed implementation:** `aee5b53fb5917cb42c5add72d0f719b2524a1872`  
**Reviewed branch head:** `1caecc4937c010ca999829c3131a6d1fc700d3ad`  
**Verdict:** CHANGES_REQUESTED

**Progress:** Previous reported shell fail-open, mixed patch write evasion, corrupt ledger JSON, and spawned-process test deficiencies have materially improved; executor reports 333 tests passing and live Codex DENY/VERIFIED/UNVERIFIED.

**Remaining blockers:**
1. Aggregate action-kinds and paths in a mixed patch are matched independently, causing false BLOCKs even if no forbidden `(path, action_kind)` pair exists.
2. Missing ledger file on an existing session still replaces policy with empty ledger, a fail-open.
3. Empty/malformed PreToolUse input still succeeds without explicit deny; validation errors unhandled.
4. Plugin root manifest incorrectly uses `extensions.com.openai.hooks` as a flattened key instead of nesting under `extensions.com.openai`; the plugin discovery test is a self-authored simulation rather than actual Codex plugin load.

Full repair acceptance instructions persisted in `.agent/tasks/TASK-010.md`; no merge to main.

---

## 2026-10-08 — TASK-010 fourth review

**Implementation reviewed:** `ed68dffa7176d390ac10a87b34a278e0b0c6b173`  
**Branch head reviewed:** `f45bab73a65a4e4dabf84b2995d983c1f90c7b71`  
**Verdict:** CHANGES_REQUESTED

**Progress:** Round-3 guard correctness fixes are present: fine-grained mixed-patch evaluation; missing ledger/trace fail-closed; malformed PreToolUse deny; official nested plugin hook manifest. Executor reports 340 passing tests and live Codex DENY/VERIFIED/UNVERIFIED.

**Remaining blockers:**
1. Uncaught PreToolUse exceptions, especially per-session `SessionLock` TimeoutError or I/O errors, can exit hook without explicit DENY; Codex hook failures can fail open.
2. Real Codex plugin marketplace install/list proves discovery and enablement but not that plugin hooks were trusted and executed; real safety session used project-local hooks instead.

See precise acceptance checks in `.agent/tasks/TASK-010.md`. Keep task on branch; no main merge.

---

## 2026-10-09 — TASK-010 final review / M5 accepted

**Final implementation:** `c4128dc5caee4a509c372569804f0f621ab08da9`  
**Reviewed task branch:** `3d664720ceb330148fbaa03a096475c11ef68f13`  
**Selective main integration:** `8b3d4ee1f7ad11991a04f72f83ba303387965623`  
**Verdict:** ACCEPTED

Round-4 closing checks reviewed: explicit structured DENY for Python-level PreToolUse I/O, lock timeout, state corruption and unexpected exceptions; dispatcher/CLI backup deny; additional regression tests. Executor reports a real installed-and-enabled Codex plugin-only run without project-local hooks. The session observed an actual blocked protected write, unchanged SHA-256, and grounded pytest VERIFIED / unsupported-claim UNVERIFIED.

Executor reports 343 passing pytest tests (Python 3.12.9). Main agent reviewed source and the reported evidence, but did not independently execute the user's Windows Codex session.

TASK-010 complete; M5 Codex integration milestone accepted. No next task active.

---

## 2026-10-09 — TASK-011 activated: Codex global configuration isolation

**State:** READY_FOR_EXECUTOR

The project's Codex plugin integration test invokes marketplace/plugin mutation commands against the inherited user configuration; this can affect ordinary Codex desktop/CLI use, even though cleanup is attempted. `install_hooks()` also replaces pre-existing project hook configuration. The user requires AgentContract to have no cross-workspace or global impact. Opened `.agent/tasks/TASK-011.md` with explicit isolated CODEX_HOME tests, lossless project-only hook merge/uninstall, opt-in plugin trust, and before/after global state checks.

---

## 2026-10-09 — TASK-011 first review

**Implementation:** `1de707eefb514f0ab35f3daf349f0103db1a7301`  
**Branch head:** `74be048cc07d51b2a3b5b6df88296e7e48bf9085`  
**Verdict:** CHANGES_REQUESTED

**Improvement:** Codex plugin mutation subprocesses now use test-local CODEX_HOME; common-case project hook merge/uninstall and audit features implemented. Executor reports 351 passing tests.

**Blocking findings:**
1. Mixed matcher group with AgentContract and third-party child hooks: uninstall deletes entire group and third-party hook.
2. Valid JSON with invalid/unknown hook structural shape gets silently overwritten by installer.
3. Audit ignores global config.toml enabled AgentContract test plugin entries and can falsely certify zero global impact; top-level-only test snapshots miss in-place edits.
4. Filesystem root path guard compares Path to str and fails to block root.

Full reproducible cases and acceptance requirements in `.agent/tasks/TASK-011.md`. No main merge.

---

## 2026-10-09 — TASK-011 second review

**Implementation:** `a33562d570e69bf8b300204ccfa49fbfaa7369b7`  
**Branch head:** `5171c446d836576d820f3346fe309ffe05ab87eb`  
**Verdict:** CHANGES_REQUESTED

Round-1 defects substantially repaired; executor reports 352 passing tests. Remaining issues:
1. Installer/uninstaller accept project-local `.codex` junction/symlink pointing outside project, potentially modifying global user Codex home.
2. Uninstall can delete unrelated top-level JSON metadata and empty foreign event arrays.
3. Audit overclaims "Zero External Side Effects Confirmed" from incomplete inspection and suggests broad plugin removal for stale config-only records.
4. Plugin smoke test's home snapshot post-check is skipped on assertion failures; integrate into mandatory teardown.

Full reproducible examples and acceptance criteria: `.agent/tasks/TASK-011.md`. **No merge to main.**

---

## 2026-10-09 — TASK-011 third review and acceptance

**Executor implementation:** `994ea60b9dc076263ae78d4beea6c3bf045ca35e`  
**Reviewed branch:** `29addcc3debadfd1b7a459776392305812a54588` (plus main-agent docs safety edit `f783f93e54761a5acb86a81f03f36e518a62abf3`)  
**Main selective integration:** `a8343521416cbe97a257a4c06f19730c3265ee60`  
**Verdict:** ACCEPTED

Round-2 issues resolved by source inspection and new regressions: rejects escaping project .codex Junction/symlink paths before install/uninstall, preserves all foreign top-level JSON metadata and empty foreign hook event arrays, scopes audit claims to inspected Codex global sources and avoids broad plugin deletion for stale config-only entries, and forces integrity checks in pytest teardown on test failure.

Main agent also corrected integration docs to remove unsafe unconditional global plugin removal guidance and mark unexecuted Codex Desktop checks MANUAL/UNVERIFIED.

**Verification:** Executor reports 355 passing tests (Python 3.12.9, Windows), 0 failing; main agent reviewed implementation/tests/docs but independent clone/testing unavailable because GitHub DNS resolution failed in this container. GitHub combined status had no CI checks. GUI checks remain manual/unverified.

M6 COMPLETE; no new active task.

---

## 2026-10-09 — TASK-012 first review

**Implementation:** `98c5eaea7ae56db6e9e88175b90d099cf863ddd0`  
**Executor branch report head:** `86832ff28f0ad02daa8d4d2c668c49a3f4ce5b2e`  
**Verdict:** CHANGES_REQUESTED

Production patch is narrow and aligned with Codex PreToolUse: ALLOW/no rewritten args -> empty stdout; DENY -> structured hookSpecificOutput. Executor reports 358 passing tests, not independently reproduced.

Blockers:
1. Real tests copy real `~/.codex/auth.json` into temp CODEX_HOME, violating explicit test-auth isolation and creating credential copies.
2. Both real tests use `--dangerously-bypass-approvals-and-sandbox`, allowing arbitrary local effects if Hook fails.
3. DENY test accepts model prose containing 'constraint' without proving a tool was submitted and actually blocked; ALLOW test does not prove Hook itself ran/completed. Require actual guard trace events and correlated tool evidence.
4. CLI subprocess ALLOW test inherits checkout cwd and creates `.agentcontract/sessions` outside test's tmp_path.

No main integration. Full reproducible notes and acceptance requirements in TASK-012 file.

---

## 2026-10-09 — TASK-012 second review

**Implementation:** `0599b50a0c5947a49acbac70400c7775f8f0b0eb`  
**Executor branch head:** `5ba98f73b12a78fe9795445a9667633e9c0c9609`  
**Verdict:** CHANGES_REQUESTED

Positive: ALLOW/empty response and structured DENY remain, real user auth is no longer copied; online tests demand explicit test auth and correctly skip when absent. Executor reports 357 passed / 2 skipped (real online CLI tests were both skipped).

Blockers:
1. Both online Codex subprocesses specify `--approve-for-me` without explicitly selecting `--sandbox workspace-write`; cannot assume ambient sandbox is bounded.
2. DENY E2E test passes on any generic BLOCK trace from any action and does not correlate denial to the actual protected-path write. It can falsely pass when the model refuses the intended write. Require specific action/path/call correlation, real hook denial evidence and unchanged file.
3. Executor Report must mark real CLI ALLOW/Completed and DENY/Blocked unverified due to explicit skips; `Known limitations: None` is not accurate.

Detailed cases and acceptance gate: `.agent/tasks/TASK-012.md`. No main merge.

---

---

## 2026-10-09 — TASK-012 third review

**Implementation:** `1c4877a90bc60c82f490d5a44a86cf85b903f4e6`  
**Reviewed branch head:** `9bb6a3325db60ccab7e2b4ebde3a9080092f8722`  
**Verdict:** CHANGES_REQUESTED

Explicit `--sandbox workspace-write` added and Executor Report now acknowledges **357 passed / 2 skipped** (online ALLOW/DENY unverified). Static blockers: missing `Any` import causes authenticated DENY test NameError; sandbox assertion is swallowed by `except Exception` and metadata is optional; Guard BLOCK match is not restricted to mutating operation, correlation IDs may be empty, and textual `BLOCK:` is not trustworthy machine-denial evidence; temporary auth cleanup misses pre-try failures and suppresses unlink errors. Both online E2E tests remain skipped, with no independent rerun or GitHub status checks. Detailed findings and remediation in `.agent/tasks/TASK-012.md`. No merge to main.

---

## 2026-10-09 — TASK-012 fourth review

**Implementation reviewed:** `0ce55af4b423e09f43f32eccde25d2c890413772`  
**Executor report HEAD:** `0493fb543f18c0709388cf1ef8fc8ed70e294140`  
**Verdict:** CHANGES_REQUESTED

Positive: missing typing import, broad sandbox-exception swallowing, empty-call-ID check and pre-try auth copy/cleanup scope fixed. Executor reports Python 3.12.9 **360 passed / 2 skipped**, with both real online E2E tests skipped. Independent Windows/Codex run unavailable; no GitHub combined status checks.

Remaining blockers: `action_targets_protected_write` still allows shell command substring false positives (protected path as content value or `.bak` suffix rather than destination). The apparent machine-event evidence is checked against AgentContract trace events rather than Codex CLI JSONL, and remaining stderr checks are not correlated to the specific blocked call. Require exact mutating destination, call-linked machine/runtime denial evidence and matched ALLOW evidence. Real online ALLOW/DENY acceptance remains UNVERIFIED. Full directions in `.agent/tasks/TASK-012.md`. No product merge or next task.

---

## 2026-10-10 — TASK-012 fifth review

**Reviewed remote HEAD:** `2741178152075a8aaa310ceb02b64e77a598023d`  
**Verdict:** CHANGES_REQUESTED

Positive: separate Codex JSONL from AgentContract trace, improved shell destination extraction, call-tag stderr. Executor reports 362 passed/2 skipped on Windows Python 3.12.9. Real Codex CLI ALLOW/DENY online tests both SKIPPED/UNVERIFIED. No GitHub CI checks; independent clone blocked by DNS.

Blocking: redirection regex counts `>` inside a quoted string as a write to `secrets/prod.key`; path matcher accepts unrelated absolute workspaces with same suffix. ALLOW parser counts any non-`failed` `command_execution` (including in-progress) as completed; DENY relies on hook's own stderr as though that proved Codex runtime honored the block. Executor Report SHA `0876d8c...` is not a reachable GitHub commit (422); remote HEAD is `274117815...`. Fix these and obtain dedicated, sandboxed, correlated real Codex E2E proof before acceptance. Details in `.agent/tasks/TASK-012.md`. No merge or next task.

---

## 2026-10-10 — TASK-012 sixth review: BLOCKED on E2E acceptance

**Implementation commit:** `c7f8bdceb70d6a1eb0a0561a90a10fb080bd89c6` (reachable)  
**Reviewed report HEAD:** `4a26d4351063640c44fa435d6f9afa36662b68cf`  
**Verdict:** BLOCKED, not ACCEPTED.

Static improvements address quoted redirection, workspace-aware path comparison, ALLOW terminal-success filtering, and independent Codex-side runtime signal checking for DENY. Executor reports Python 3.12.9 362 passed / 2 skipped (zero failures). **Both required real Codex CLI E2E scenarios skipped** because dedicated test-only credentials were unavailable; no independent runtime run or GitHub CI status. Cannot conclude Codex honored PreToolUse output. A generic failed command item is not necessarily hook rejection; authentic runtime evidence must distinguish these.

Mark TASK-012 BLOCKED pending dedicated test auth and isolated ALLOW/Completed + DENY/Blocked evidence. Preserve protected bytes; no personal auth copying, sandbox bypass, global config mutation, product merge, or next task. Full review in task document.
