# TASK-009 — CLI/API Packaging and Documentation

**Status:** READY_FOR_EXECUTOR  
**Milestone:** M4 — Integration-ready project  
**Owner:** Execution agent  
**Work branch:** `task/TASK-009-packaging`  
**Main-agent review:** pending

## Objective

Turn the accepted AgentContract v0.1 core into an installable, understandable developer-facing package.

## Required deliverables

1. CLI entry point suitable for local use.
2. Minimal public Python API examples.
3. README rewritten from "planned components" to actual implemented capabilities.
4. Quickstart documentation for:
   - offline deterministic demo;
   - OpenAI API;
   - generic OpenAI-compatible endpoint.
5. Configuration documentation for:
   - OPENAI_API_KEY
   - OPENAI_MODEL
   - OPENAI_BASE_URL
   - OPENAI_RESPONSE_FORMAT
6. Benchmark documentation explaining metric definitions and current 13-scenario deterministic limitations.
7. Packaging metadata / console script entry point.
8. Version and install verification.
9. Security/authority model section clearly distinguishing:
   - LLM extraction;
   - deterministic enforcement;
   - observable evidence;
   - no claim self-verification.
10. No development-workflow concepts presented as AgentContract product functionality.

## CLI

Provide useful commands such as:

```text
agentcontract demo
agentcontract benchmark
agentcontract version
```

Exact names may differ, but:
- commands must use accepted core components;
- demo must run offline without API credentials;
- benchmark prints or exports the actual benchmark report;
- errors return non-zero exit codes;
- no hidden network calls.

Optional online demo flag/config is acceptable.

## Packaging

- installable with `python -m pip install -e ".[dev]"`;
- console script declared in `pyproject.toml`;
- Python >=3.12 remains authoritative;
- no unnecessary provider SDK dependency;
- package build/import smoke test.

## Documentation

README must describe current reality, not future intent.

Include:
- what problem AgentContract solves;
- architecture;
- minimal Python example;
- quickstart commands;
- API-backed extraction setup;
- benchmark meaning/limitations;
- current v0.1 limitations;
- repository development notes separated from product documentation.

Do not market the 13 deterministic benchmark scenarios as proof of real-world model performance.

## Tests

At minimum:
- CLI version;
- CLI offline demo;
- CLI benchmark;
- invalid command/config exit behavior;
- package root imports;
- pyproject console entry point;
- README commands match executable behavior;
- full existing suite remains green.

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

**Known limitations:**  
TBD

**Commit/PR:**  
TBD

**Questions/blockers:**  
TBD

## Main Agent Review

> Main agent only.

**Verdict:** PENDING
