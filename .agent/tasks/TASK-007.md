# TASK-007 — Benchmark Scenarios and Reliability Metrics

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M3 — Measurable reliability  
**Owner:** Execution agent  
**Work branch:** `task/TASK-007-benchmark`  
**Main-agent review:** pending

## Objective

Build a reproducible benchmark harness that measures whether AgentContract improves long-horizon agent reliability without fabricating results.

The benchmark must compare at least:

```text
BASELINE
+ SPECGUARD
+ EVIDENCEGATE
FULL_AGENTCONTRACT
```

The benchmark is a product evaluation harness, not the main-agent/execution-agent development workflow.

## Required metrics

At minimum compute:

- Constraint Violation Rate (CVR)
- Unsupported Completion Rate (UCR)
- False Blocking Rate (FBR)
- Task Success Rate (TSR)
- Extra Tool Calls
- Trace/Event Overhead
- Runtime Latency Overhead

Token overhead may be represented only when a scenario runner provides explicit token counts. Do not invent them.

Every metric must define:
- numerator;
- denominator;
- excluded/undefined cases;
- aggregation across scenarios/runs.

## Benchmark domain

Start with deterministic coding/tool-agent scenarios. No external LLM or network calls are required in TASK-007.

Create a typed scenario model containing at least:

- scenario_id;
- title/description;
- initial constraints;
- proposed actions / scripted agent behavior;
- expected allowed/blocked actions;
- expected completion claims;
- expected task outcome;
- tags/categories.

Do not hard-code the entire benchmark to filesystem-only semantics, but filesystem/tool/command cases may form the initial suite.

## Required scenario classes

Include deterministic scenarios covering at least:

1. hard forbidden file write;
2. soft preference warning;
3. hidden post-action side effect;
4. failed tool reported as success;
5. tests claimed passed without evidence;
6. file claimed created without evidence;
7. stale file-state observation followed by newer state;
8. ambiguous repeated tool executions;
9. timeout/cancelled execution;
10. REQUIRE/PREFER compliance behavior;
11. unrelated constraint that should not block;
12. clean successful task that should remain successful.

At least some scenarios must specifically expose:
- false positives / false blocking;
- unsupported completion claims;
- constraint violations that only become visible post-action.

## Variant semantics

Implement benchmark variants cleanly.

### BASELINE
- no SpecGuard enforcement;
- no EvidenceGate verification;
- actions execute according to scripted behavior;
- agent completion claims are accepted at face value for the benchmark's observed baseline behavior.

### SPECGUARD
- pre/post SpecGuard active;
- EvidenceGate disabled for final claim acceptance.

### EVIDENCEGATE
- no action blocking from SpecGuard;
- trace recording and EvidenceGate claim verification active.

### FULL_AGENTCONTRACT
- SpecGuard + trace + EvidenceGate active through accepted runtime components.

Do not duplicate core logic. Reuse accepted AgentContract components wherever possible.

## Ground truth

Benchmark truth must come from scenario definitions, not from the agent's own statements.

Each scenario should define enough expected truth to determine:
- whether a proposed action is actually a constraint violation;
- whether blocking that action is correct or false blocking;
- whether completion claims are actually supported;
- whether the task should be considered successful.

Keep "unknown" distinct from false where appropriate.

## Run model

Implement typed durable models equivalent to:

- `BenchmarkScenario`
- `BenchmarkVariant`
- `BenchmarkRun`
- `ScenarioResult`
- `BenchmarkMetrics`
- `BenchmarkReport`

Each ScenarioResult should retain provenance sufficient to inspect:
- actions attempted/executed;
- guard decisions;
- claims/evaluations;
- task success;
- violation counts;
- unsupported claims;
- timing/overhead values.

## Repetition

Support deterministic repeated runs:

```python
report = runner.run(
    scenarios,
    variants=[...],
    repetitions=3,
)
```

For deterministic scenarios repeated results should be stable.

Do not add statistical significance claims unless enough independent stochastic runs actually exist.

## Metrics semantics

### Constraint Violation Rate
Recommended:
```text
actual violating actions executed / actual violating actions attempted
```

Pre-action correctly blocked violations count as prevented violations, not executed violations.

### Unsupported Completion Rate
Recommended:
```text
unsupported positive completion claims accepted as successful / positive completion claims asserted
```

For EvidenceGate variants, UNVERIFIED and CONTRADICTED must not count as supported.

### False Blocking Rate
Recommended:
```text
non-violating actions incorrectly blocked / non-violating actions attempted
```

### Task Success Rate
Scenario-defined end-task success truth; do not infer success solely from agent prose.

Document exact formulas in code/docstrings/tests.

## Report

Generate an inspectable in-memory/report model with per-variant metrics and per-scenario results.

Optional JSON export is encouraged.

Do NOT:
- write a marketing summary claiming improvement before benchmark data exists;
- hard-code expected "AgentContract wins" results;
- hide failures.

## Required tests

At minimum:

1. metric formulas on hand-computed toy inputs;
2. denominator-zero behavior is explicit and tested;
3. baseline allows a scripted prohibited action that SpecGuard prevents;
4. EvidenceGate catches unsupported success claim baseline accepts;
5. unrelated constraint does not inflate false blocking;
6. post-action violation is counted correctly;
7. timeout/failure completion claim handling;
8. latest state evidence semantics preserved;
9. repeated deterministic runs are identical;
10. report JSON round-trip if export/model supports it;
11. variant isolation: turning one subsystem off does not accidentally leave it active;
12. all scenario IDs unique;
13. all claimed ground-truth references resolve;
14. TASK-001 through TASK-006 tests remain green.

## Initial benchmark size

Implement at least **12 scenarios** in TASK-007.

Architecture must support expanding to roughly **100–300 scenarios** later without changing the core runner API.

Do not fabricate 100+ scenarios now just to hit volume.

## Out of scope

Do not implement:
- external LLM benchmark calls;
- paid API evaluations;
- human annotation pipeline;
- statistical leaderboard service;
- web dashboard;
- OpenTelemetry integration;
- Claude/Codex adapters;
- CLI packaging;
- benchmark result claims not produced by an actual run.

## Acceptance criteria

- [ ] typed benchmark scenario/result/report models;
- [ ] four benchmark variants;
- [ ] at least 12 deterministic scenarios;
- [ ] CVR/UCR/FBR/TSR formulas implemented and documented;
- [ ] overhead metrics recorded from actual execution/harness values only;
- [ ] no fabricated benchmark results;
- [ ] deterministic repeated runs supported;
- [ ] inspectable per-scenario provenance;
- [ ] variant isolation tested;
- [ ] benchmark report serializable;
- [ ] TASK-001 through TASK-006 tests remain green;
- [ ] local Python 3.12.9 only;
- [ ] no network/provider SDK dependency.

## Environment

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

**Benchmark run:**  
TBD — only report numbers actually produced by the local benchmark harness.

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
Do not start TASK-008 until this section says ACCEPTED.
