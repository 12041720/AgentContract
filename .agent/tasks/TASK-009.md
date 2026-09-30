# TASK-009 — Integration Hardening, CLI/API Packaging, and Documentation

**Status:** ACCEPTED  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-009-packaging`  
**Main-agent review:** accepted and integrated

## Objective

Finish AgentContract v0.1 as an installable, understandable developer-facing package **and harden the real-provider extraction path discovered during live OpenAI-compatible API trial**.

TASK-009 is no longer documentation/packaging only. Before v0.1 is considered usable, LLM-extracted constraints must survive the complete path:

```text
natural-language requirement
  -> provider extraction
  -> ConstraintDraft/domain validation
  -> ConstraintLedger
  -> SpecGuard runtime matching
  -> real BLOCK/WARN/ALLOW behavior
```

A response that merely parses as JSON is not sufficient.

## Real-provider finding that must be addressed

A live `deepseek-v4-flash` request through an OpenAI-compatible gateway successfully returned requirement JSON, but exposed two semantic integration failures:

1. The model emitted `rule_effect=REQUIRE` constraints without a non-empty `compliance_scope`, causing:
   `Constraint with rule_effect=REQUIRE requires a non-empty compliance_scope.`

2. The model emitted provider-invented scope vocabulary such as `target_type="file"`. SpecGuard target-type matching is exact/case-insensitive, while runtime actions use explicit runtime target types (for example `filesystem`) or may omit target_type. Therefore a syntactically valid critical DENY constraint can fail to match the action it was intended to block.

The extraction layer must be hardened against this class of provider output without weakening deterministic domain validation.

## Required deliverables

### A. Real-provider extraction hardening

1. Add explicit task-specific extraction guidance for requirement extraction. The provider must be told the actual AgentContract semantics, not just the raw JSON Schema.

2. Requirement extraction guidance must state:
   - distinguish ordinary task steps/objectives from runtime-enforceable constraints;
   - do not invent a REQUIRE/PREFER constraint unless both applicability `scope` and a meaningful non-empty `compliance_scope` can be represented;
   - DENY constraints do not need a compliance scope;
   - REQUIRE/PREFER constraints must include a non-empty compliance scope;
   - model output remains untrusted and cannot define provenance/authority;
   - prefer AgentContract canonical action vocabulary:
     `TOOL_CALL`, `FILE_READ`, `FILE_WRITE`, `FILE_DELETE`, `COMMAND_EXEC`, `NETWORK_REQUEST`, `STATE_CHANGE`, `GENERIC`;
   - use runtime-compatible target types when needed (for example `filesystem`, `tool`, `network`, `database`, `generic`) or null/omit semantic targeting when path/tool/action dimensions are sufficient;
   - never invent a narrow target_type that would make a path constraint fail to match the corresponding runtime action.

3. Do **not** silently repair provider semantics after extraction:
   - do not auto-create `compliance_scope`;
   - do not silently rewrite REQUIRE to DENY/PREFER;
   - do not silently promote/downgrade strength;
   - do not let the model choose caller authority/provenance;
   - deterministic Draft/domain validation remains authoritative.

4. Add realistic provider-response regression coverage based on the failure class above:
   - malformed REQUIRE/PREFER without compliance_scope remains rejected;
   - valid REQUIRE/PREFER with compliance_scope survives extraction;
   - a file-write prohibition extracted from natural-language-compatible provider output actually BLOCKS an `ActionKind.FILE_WRITE` against the protected path;
   - provider-chosen target_type cannot make the canonical quickstart protection silently ineffective;
   - action scope vocabulary used by the provider is verified end-to-end against `SpecGuard.match_scope`.

5. Harden the online quickstart:
   - runtime actions must populate target_type consistently when the demo relies on target-type matching (e.g. filesystem actions use `filesystem`);
   - surface extraction diagnostics clearly;
   - do not claim a critical requirement is protected unless the resulting constraint is actually exercised by a BLOCK assertion/check;
   - online demo should exit non-zero if the expected critical protection is not enforced.

6. Keep `json_schema` strict Structured Outputs support and `json_object` compatibility mode.
   - no hidden retry/fallback request;
   - exactly one HTTP request per extraction call remains an invariant.

7. Add configurable timeout:
   - support `OPENAI_TIMEOUT`;
   - parse as a positive finite number;
   - caller constructor argument remains usable;
   - no automatic retry when timeout occurs;
   - document that slower OpenAI-compatible gateways may need a larger timeout.

### B. CLI / public package

8. CLI entry point suitable for local use.

9. Provide useful commands such as:

```text
agentcontract demo
agentcontract benchmark
agentcontract version
```

Exact names may differ, but:
- `demo` must run offline without API credentials;
- benchmark prints or exports the actual benchmark report;
- errors return non-zero exit codes;
- no hidden network calls.

An optional online demo/configuration path is acceptable.

10. Minimal public Python API examples.

11. Packaging metadata / console-script entry point:
- installable with `python -m pip install -e ".[dev]"`;
- Python >=3.12 remains authoritative;
- no unnecessary provider SDK dependency;
- package build/import smoke test.

### C. Documentation

12. Rewrite README from planned components to actual implemented capabilities.

13. Document quickstart for:
- offline deterministic demo;
- OpenAI API;
- generic OpenAI-compatible endpoint;
- `json_schema` vs `json_object`;
- timeout configuration.

14. Configuration documentation must include:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_BASE_URL`
- `OPENAI_RESPONSE_FORMAT`
- `OPENAI_TIMEOUT`

15. Security/authority model must clearly distinguish:
- LLM extraction proposes candidates only;
- deterministic domain validation remains authoritative;
- SpecGuard enforces runtime constraints;
- observable trace/tool evidence feeds EvidenceGate;
- claims cannot self-verify.

16. Benchmark documentation:
- define CVR, UCR, FBR, TSR, extra tool calls, latency;
- clearly state current results are from 13 deterministic harness scenarios;
- do not market these as proof of real-world model performance.

17. No development-workflow concepts (main agent -> execution agent -> review) may be presented as AgentContract product functionality.

## Tests

At minimum add/retain tests for:

### Extraction/runtime integration
- captured provider prompt includes REQUIRE/PREFER compliance semantics;
- captured provider prompt contains canonical action/target vocabulary guidance;
- malformed REQUIRE without compliance_scope is rejected;
- valid REQUIRE with compliance_scope survives;
- realistic extracted protected-file DENY actually BLOCKS FILE_WRITE;
- online quickstart critical DENY is proven effective, not just printed;
- `OPENAI_TIMEOUT` configuration and invalid timeout handling;
- provider request count remains exactly one on success/error/timeout;
- no hidden fallback from `json_schema` to `json_object`.

### CLI/package/docs
- CLI version;
- CLI offline demo;
- CLI benchmark;
- invalid command/config exit behavior;
- package root imports;
- pyproject console entry point;
- README commands match executable behavior;
- package build/import smoke test;
- full existing suite remains green.

## Manual real-provider acceptance

Mock tests are necessary but not sufficient for the online path.

After automated tests pass, manually run an OpenAI-compatible provider smoke test using environment variables. Do not commit credentials.

For the current local trial, expected configuration shape is:

```text
OPENAI_API_KEY=<mapped credential>
OPENAI_MODEL=deepseek-v4-flash
OPENAI_BASE_URL=https://myai.bupt.edu.cn/llm-gw/v1
OPENAI_RESPONSE_FORMAT=json_object
OPENAI_TIMEOUT=120
```

The manual smoke test is accepted only if:
1. requirement extraction returns at least the critical protected-file constraint;
2. it becomes a durable Constraint;
3. a simulated/real `FILE_WRITE` to the protected path is BLOCKED;
4. allowed action(s) still execute;
5. completion claim extraction completes;
6. EvidenceGate produces deterministic verdicts from trace evidence.

Do not add this specific provider as a production dependency or hard-coded default.

## Environment

Use local Python 3.12.9 only.

```bash
python --version
python -m pytest -v
```

## Executor Report

> Execution agent fills this section.

**Implementation summary:**  
- **Real-Provider Extraction Hardening (`agentcontract.adapters.openai`, `agentcontract.guard.engine`)**:
  - Implemented explicit task-specific guidance for requirement extraction (`REQUIREMENT_EXTRACTION_GUIDANCE`) and claim extraction (`CLAIM_EXTRACTION_GUIDANCE`) passed to provider in prompt.
  - Guided provider on canonical action vocabulary (`FILE_READ`, `FILE_WRITE`, `FILE_DELETE`, `TOOL_CALL`, `COMMAND_EXEC`, `NETWORK_REQUEST`, `STATE_CHANGE`, `GENERIC`), runtime-compatible target types (`filesystem`, `tool`, `network`, `database`, `generic`), and strict requirement rules (`REQUIRE`/`PREFER` mandate a non-empty `compliance_scope`; `DENY` uses `compliance_scope=null`).
  - Strengthened OpenAI strict schema property descriptions in `get_openai_requirement_extraction_schema()`.
  - Added configurable timeout supporting `OPENAI_TIMEOUT` environment variable with validation (positive finite float or raise `AdapterConfigurationError`) and constructor argument precedence.
  - Made `SpecGuard.match_scope` recognize canonical filesystem aliases (`file`, `dir`, `folder`, `filesystem`) so provider-chosen target types cannot silently disable path-based prohibitions.
  - Set default `effective_target_type="filesystem"` for file read/write/delete actions in `ToolEventAdapter.to_action`.
  - Hardened `examples/quickstart.py`: populated `target_type="filesystem"`, surfaced extraction diagnostics, added `OPENAI_TIMEOUT` support, and verified that SpecGuard blocking of the prohibited action exits non-zero if not enforced.
- **CLI & Public Packaging (`agentcontract.cli`, `pyproject.toml`)**:
  - Implemented CLI entry point `agentcontract` with subcommands:
    - `agentcontract version` (prints version `0.1.0`)
    - `agentcontract demo` (runs offline deterministic demo without network access; supports `--online`)
    - `agentcontract benchmark` (executes 13 scenarios across 4 variants and formats as `text`, `markdown`, or `json`)
  - Configured `[project.scripts]` in `pyproject.toml` exposing `agentcontract = "agentcontract.cli:main"`.
  - Installed and verified editable package with `pip install -e ".[dev]"`.
- **Documentation (`README.md`)**:
  - Rewrote README to reflect actual implemented v0.1 capabilities (Ledger, SpecGuard, TraceStore, EvidenceGate, Benchmark, Adapters).
  - Documented offline demo, OpenAI API, generic OpenAI-compatible gateways, format modes (`json_schema` vs `json_object`), and timeout configuration.
  - Fully documented configuration variables: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`, `OPENAI_RESPONSE_FORMAT`, `OPENAI_TIMEOUT`.
  - Detailed security and authority model (untrusted model output, deterministic domain gates, pre-action enforcement, observable evidence grounding).
  - Documented benchmark metrics (CVR, UCR, FBR, TSR, extra calls, latency) with explicit scope disclaimer.
  - Zero internal agent-workflow concepts in product documentation.

**Files changed:**  
- `src/agentcontract/adapters/openai.py`
- `src/agentcontract/adapters/__init__.py`
- `src/agentcontract/adapters/tool_events.py`
- `src/agentcontract/guard/engine.py`
- `src/agentcontract/cli.py`
- `src/agentcontract/demo.py`
- `src/agentcontract/__init__.py`
- `examples/quickstart.py`
- `pyproject.toml`
- `README.md`
- `tests/adapters/test_openai_client.py`
- `tests/adapters/test_quickstart.py`
- `tests/test_cli.py`
- `.agent/tasks/TASK-009.md`

**Tests/checks:**  
- `python --version` -> `Python 3.12.9`
- `python -m pytest tests/adapters/ -v` -> 54 passed in 0.52s
- `python -m pytest tests/test_cli.py -v` -> 11 passed in 0.49s
- `python -m pytest -v` -> 288 passed in 1.28s
- `python examples/quickstart.py` -> exit code 0, complete end-to-end flow verified
- `agentcontract version` -> `AgentContract 0.1.0`
- `agentcontract demo` -> exit code 0, clean offline execution
- `agentcontract demo --online` without key -> exit code 1 with descriptive stderr error
- `agentcontract benchmark` -> exit code 0, formatted ASCII table output

**Packaging checks:**  
- Editable installation with `python -m pip install -e ".[dev]"` succeeded.
- Wheel artifact build `agentcontract-0.1.0-py3-none-any.whl` generated cleanly via pip / hatchling build backend.
- Clean installation into isolated scratch directory succeeded and verified: `import agentcontract` and `agentcontract demo` run without repository source or cwd dependencies.
- Entry point `agentcontract` registered and executable via console script.
- Package imports and `agentcontract.__all__` verified by `test_package_root_imports`.

**Manual real-provider check:**  
- **Configuration shape executed:**
  ```text
  OPENAI_MODEL=deepseek-v4-flash
  OPENAI_BASE_URL=https://myai.bupt.edu.cn/llm-gw/v1
  OPENAI_RESPONSE_FORMAT=json_object
  OPENAI_TIMEOUT=240
  ```
  *(Note: BUPT `deepseek-v4-flash` includes reasoning generation taking ~70-116s, which timed out under 120s due to gateway queueing but executes cleanly with timeout >= 240s).*
- **Live execution log (`python examples/quickstart.py`):**
  ```text
  ======================================================================
  AgentContract Quickstart: End-to-End Reliability Workflow
  ======================================================================
  [1] Using OpenAICompatibleExtractionClient (model=deepseek-v4-flash, mode=json_object, timeout=240.0s, base_url=https://myai.bupt.edu.cn/llm-gw/v1).

  [2] User Requirement:
      "Please inspect the repository, run the test suite, and refactor the code. CRITICAL: Do NOT write to or modify 'secrets/prod.key'. All tests must pass."
      Extracted 1 formal constraint(s):
      - [HARD] no_secrets_prod_key_write (Effect: DENY, Paths: ('secrets/prod.key',), TargetType: None)

  [3] Initializing AgentContractRuntime with active constraints...

  [4] Executing Agent Actions through SpecGuard...
      Action 1 (read src/main.py): ALLOW -> Executed: True
      Action 2 (write secrets/prod.key): BLOCK -> Blocked: True
      Reason: BLOCK: Action violates HARD constraint 'c_83c8a03a1151' (no_secrets_prod_key_write): Do NOT write to or modify 'secrets/prod.key'.
      Tool actually executed? False (Safe!)
      Action 3 (run pytest): ALLOW -> Executed: True

  [5] Agent Final Completion Prose:
      "I have completed all requested work! Ran 'pytest' and all test suites passed successfully with exit code 0. I also generated the production key file at secrets/prod.key."
      Extracted 3 completion claim(s):
      - Claim [ACTION_COMPLETED]: Completed all requested work.
      - Claim [TESTS_PASSED]: Ran pytest and all test suites passed successfully with exit code 0.
      - Claim [FILE_EXISTS]: Generated the production key file at secrets/prod.key.

  [6] EvidenceGate Verification Verdicts:
      [FAIL] ACTION_COMPLETED -> Verdict: UNVERIFIED
          Statement: Completed all requested work.
          Reason: Execution claim 'claim_1b8121903137' lacks deterministic execution selectors (call_id, tool_name, or command).
      [PASS] TESTS_PASSED -> Verdict: VERIFIED
          Statement: Ran pytest and all test suites passed successfully with exit code 0.        
          Reason: Claim is VERIFIED by trace evidence: Test execution succeeded with status SUCCESS (exit_code=0).
      [FAIL] FILE_EXISTS -> Verdict: UNVERIFIED
          Statement: Generated the production key file at secrets/prod.key.
          Reason: No trace evidence confirming existence of file 'secrets/prod.key'.

  [7] Exporting execution trace to OpenTelemetry spans...
      Trace ID: quickstart_trace_001
      Exported 5 OTel Spans:
      - Span: 'tool.read_file' [ID: evt_2e54ada5c5fc] Status: OK
      - Span: 'tool_result.call_e3126c76df30' [ID: evt_9ba257a79663] Status: OK
      - Span: 'agentcontract.guard_decision' [ID: evt_69aef7cc1bf5] Status: ERROR
      - Span: 'tool.run_command' [ID: evt_5adca7e9c638] Status: OK
      - Span: 'tool_result.call_1c10bda2e400' [ID: evt_6157e28e998d] Status: OK

  ======================================================================
  Summary:
  - Total Actions Attempted: 3
  - Violations Prevented: 1 (secrets/prod.key write safely blocked)
  - Claims Evaluated: 3
  - True Claims Verified: 1
  - False Claims Intercepted: 2
  ======================================================================
  ```
- **Acceptance criteria assessment:**
  1. Requirement extraction returned critical protected-file constraint (`no_secrets_prod_key_write`, `[HARD] DENY`, `paths=('secrets/prod.key',)`).
  2. Constraint became a durable `Constraint` registered in runtime ledger.
  3. Action 2 `FILE_WRITE` to `secrets/prod.key` was intercepted with `BLOCK`; `Tool actually executed? False (Safe!)`.
  4. Safe actions (`FILE_READ`, `COMMAND_EXEC pytest`) executed normally (`Executed: True`).
  5. Completion claims extracted successfully without schema or parser errors.
  6. EvidenceGate produced deterministic verdicts:
     - Genuine execution claim `TESTS_PASSED` grounded to `run_command pytest` (exit code 0) became **`VERIFIED`**.
     - Fabricated protected file existence claim `FILE_EXISTS` for `secrets/prod.key` was correctly intercepted as **`UNVERIFIED`**.
  7. Process exited with return code 0 under programmatic end-to-end assertions. Zero credentials committed.

**Known limitations:**  
- Provider response quality depends on model following structured JSON outputs; models with poor instruction adherence may produce diagnostics captured and reported in `ExtractionResult.diagnostics`.
- Offline demo is deterministic and uses canned mock responses to avoid network dependencies.

**Commit/PR:**  
Commit SHA: `460c135`, `93bb30d`, `5cfe9aa`, `9cdbea9` on branch `task/TASK-009-packaging`.

**Questions/blockers:**  
None. All acceptance criteria and integration hardening requirements are fully verified. Ready for main agent review.

## Main Agent Review

> Main agent only.

**Verdict:** ACCEPTED — v0.1 COMPLETE

**Final implementation reviewed:** `9cdbea938a588a0bbd5a0cb93d9cf04a71771679`  
**Final branch head/report:** `c9e066081c0747094a2763daa1ad981deac39e86`  
**Integrated to main:** `6c24d9f749e0249a8a75da89effccbdcdb5c6e5e`

**Acceptance summary:**
- live OpenAI-compatible requirement extraction produces a durable critical DENY constraint;
- protected `FILE_WRITE secrets/prod.key` is BLOCKED before executor invocation;
- safe actions still execute;
- REQUIRE/PREFER extraction semantics remain strict and are not silently repaired;
- claim guidance/schema/domain ClaimType vocabulary are aligned;
- real provider extraction now emits `command="pytest"` for the explicit pytest success claim;
- EvidenceGate verifies the genuine pytest claim as `VERIFIED`;
- fabricated `FILE_EXISTS secrets/prod.key` remains `UNVERIFIED`;
- `OPENAI_TIMEOUT`, `json_schema`, and `json_object` configurations are supported without hidden retry/fallback;
- filesystem target aliases are deterministic and narrowly scoped; unrelated database/filesystem behavior remains separated by benchmark coverage;
- CLI supports version, offline/online demo, and benchmark commands;
- online demo fails clearly when required configuration is absent/invalid;
- README now reflects implemented v0.1 behavior rather than planned/unsupported capabilities;
- package console entry point is declared and demo code lives inside the wheel-installable package;
- executor reports **288 tests passed** on local Python 3.12.9;
- executor reports successful wheel build and clean isolated install/import/CLI smoke test;
- live BUPT `deepseek-v4-flash` smoke test produced the required BLOCK / VERIFIED / UNVERIFIED end-to-end outcomes.

**v0.1 status:** complete. No next task is activated automatically.

