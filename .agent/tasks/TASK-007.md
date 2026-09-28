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
- Implemented deterministic reliability benchmark harness in `agentcontract.benchmark` evaluating 4 variants: `BASELINE`, `SPECGUARD`, `EVIDENCEGATE`, and `FULL_AGENTCONTRACT`.
- Created typed Pydantic models in `agentcontract.benchmark.models`: `BenchmarkVariant`, `ScriptedAction`, `BenchmarkScenario`, `ScenarioExecutionRecord`, `ScenarioResult`, `BenchmarkMetrics`, and `BenchmarkReport` with `extra="forbid"`, immutability, and JSON round-trip serialization.
- Implemented mathematical metric formulas with safe zero-denominator behavior (`None`):
  - Constraint Violation Rate: $\text{CVR} = \frac{\text{violating\_actions\_executed}}{\text{violating\_actions\_attempted}}$
  - Unsupported Completion Rate: $\text{UCR} = \frac{\text{unsupported\_claims\_accepted}}{\text{positive\_claims\_asserted}}$
  - False Blocking Rate: $\text{FBR} = \frac{\text{non\_violating\_actions\_blocked}}{\text{non\_violating\_actions\_attempted}}$
  - Task Success Rate: $\text{TSR} = \frac{\text{successful\_tasks}}{\text{total\_tasks}}$
  - Extra tool calls, trace/event counts, and measured elapsed latency overhead.
- Created 12 deterministic benchmark scenarios in `agentcontract.benchmark.scenarios` covering all 12 required classes:
  1. `scen_01_forbidden_write`: hard forbidden file write;
  2. `scen_02_soft_warning`: soft preference warning;
  3. `scen_03_post_action_violation`: hidden post-action side effect;
  4. `scen_04_failed_tool_false_claim`: failed tool reported as success;
  5. `scen_05_tests_passed_no_evidence`: tests claimed passed without evidence;
  6. `scen_06_file_exists_no_evidence`: file claimed created without evidence;
  7. `scen_07_stale_file_state`: stale file-state observation followed by newer state;
  8. `scen_08_ambiguous_repeated_calls`: ambiguous repeated tool executions;
  9. `scen_09_timeout_execution`: timeout/cancelled execution;
  10. `scen_10_require_compliance`: REQUIRE/PREFER compliance behavior;
  11. `scen_11_unrelated_constraint`: unrelated constraint that should not block;
  12. `scen_12_clean_successful_task`: clean multi-step task completed safely and successfully.
- Implemented `BenchmarkRunner` in `agentcontract.benchmark.runner` orchestrating variant isolation, deterministic repetition, and runtime evaluation without duplicating core logic.
- Re-exported benchmark API at root package `agentcontract`.
- Added 23 regression tests across `tests/benchmark/` covering models, metrics edge cases, scenario integrity, ground-truth resolution, variant isolation, repeated run stability, and full report execution.

**Files changed:**  
- `src/agentcontract/benchmark/models.py`
- `src/agentcontract/benchmark/scenarios.py`
- `src/agentcontract/benchmark/runner.py`
- `src/agentcontract/benchmark/__init__.py`
- `src/agentcontract/__init__.py`
- `tests/benchmark/test_models.py`
- `tests/benchmark/test_metrics.py`
- `tests/benchmark/test_scenarios.py`
- `tests/benchmark/test_runner.py`
- `.agent/tasks/TASK-007.md`

**Tests/checks:**  
- `python --version` -> `Python 3.12.9`
- `python -m pytest tests/benchmark/ -v` -> 23 passed in 0.48s
- `python -m pytest -v` -> 218 passed in 1.17s (zero regressions across TASK-001 through TASK-006)

**Benchmark run:**  
Deterministic run results from local run `bench_run_8ab89d23` (12 standard scenarios, 1 repetition):
| Metric | BASELINE | SPECGUARD | EVIDENCEGATE | FULL_AGENTCONTRACT |
| --- | --- | --- | --- | --- |
| **Constraint Violation Rate (CVR)** | 1.0000 (3/3) | 0.3333 (1/3) | 1.0000 (3/3) | 0.3333 (1/3) |
| **Unsupported Completion Rate (UCR)** | 0.6923 (9/13) | 0.4615 (6/13) | 0.1538 (2/13) | 0.0000 (0/13) |
| **False Blocking Rate (FBR)** | 0.0000 (0/12) | 0.0000 (0/12) | 0.0000 (0/12) | 0.0000 (0/12) |
| **Task Success Rate (TSR)** | 0.2500 (3/12) | 0.2500 (3/12) | 0.2500 (3/12) | 0.2500 (3/12) |
| **Extra Tool Calls** | 3 | 1 | 3 | 1 |
| **Total Tool Calls** | 15 (avg 1.25) | 13 (avg 1.08) | 15 (avg 1.25) | 13 (avg 1.08) |
| **Total Trace Events** | 0 (avg 0.00) | 0 (avg 0.00) | 30 (avg 2.50) | 54 (avg 4.50) |
| **Avg Latency (ms)** | 0.060 ms | 0.310 ms | 0.171 ms | 0.991 ms |
| **Latency Overhead (ms)** | baseline (0.0 ms) | +0.250 ms | +0.111 ms | +0.931 ms |

**Known limitations:**  
- Token overhead is omitted/None since the 12 deterministic scenarios execute local tools rather than external LLM calls.
- Initial suite contains 12 scenarios; extensible to 100–300 scenarios in future tasks without changing the runner API.

**Commit/PR:**  
Commit SHA: `57169de` (implementation) on branch `task/TASK-007-benchmark`.

**Questions/blockers:**  
None. Ready for main agent review.

## Main Agent Review

> Main agent only.

**Verdict:** PENDING

**Next instruction:**  
Do not start TASK-008 until this section says ACCEPTED.
