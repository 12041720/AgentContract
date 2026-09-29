# TASK-009 — Integration Hardening, CLI/API Packaging, and Documentation

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-009-packaging`  
**Main-agent review:** pending

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
TBD

**Files changed:**  
TBD

**Tests/checks:**  
TBD

**Packaging checks:**  
TBD

**Manual real-provider check:**  
TBD

**Known limitations:**  
TBD

**Commit/PR:**  
TBD

**Questions/blockers:**  
TBD

## Main Agent Review

> Main agent only.

**Verdict:** PENDING
