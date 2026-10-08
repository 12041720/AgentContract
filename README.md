# AgentContract

**Runtime Constraint Tracking and Evidence-Grounded Verification for Long-Horizon Agents**

[English](README.md) | [简体中文](README_zh.md)

AgentContract is a deterministic reliability and safety control plane for tool-using AI agents. It extracts requirements from user instructions, translates them into enforceable runtime constraints, intercepts prohibited tool actions before execution, and verifies completion claims against observable trace evidence.

```text
User Intent
    ↓
Requirement Extraction (Drafts & Domain Validation)
    ↓
Constraint Ledger (Lifecycle & Conflict Tracking)
    ↓
Proposed Action ──→ SpecGuard (Pre-Action Interception: BLOCK / WARN / ALLOW)
    ↓
Tool Execution Outcome ──→ Trace Store (Normalized Events & Provenance)
    ↓
Agent Completion Prose ──→ Claim Extraction
    ↓
EvidenceGate (Deterministic Verification: VERIFIED / CONTRADICTED / UNVERIFIED)
    ↓
Verified Completion & OpenTelemetry Export
```

---

## The Two Core Failure Modes Addressed

1. **Constraint Drift**: Long-horizon agents easily forget, ignore, or override negative constraints ("do not modify `secrets/prod.key`", "never drop production tables") as conversational context grows or tools loop. SpecGuard intercepts actions deterministically before they reach the tool executor—without relying on the agent to self-police.
2. **Unsupported Completion**: Agents frequently declare tasks finished or tests passed even when executions failed, timed out, or never ran. EvidenceGate evaluates atomic completion claims strictly against observable trace evidence.

---

## Architecture & Implemented Capabilities (v0.1)

### 1. Structured Extraction Layer (`agentcontract.extraction`)
- **Vendor-Neutral Protocol**: `StructuredExtractionClient` abstraction allows swapping between OpenAI, local models (vLLM, Ollama), or test mocks without code changes.
- **Provider-Specific Guidance & Schemas**: Provides OpenAI strict Structured Outputs compatible JSON schemas (`to_strict_json_schema`) ensuring `additionalProperties: false` and strict nullability.
- **Draft & Domain Validation Boundary**: Model outputs enter candidate drafts (`ConstraintDraft`, `ClaimDraft`) and are validated by strict domain invariants. Models cannot tamper with caller provenance (`ConstraintSource.USER`), alter author metadata, or bypass required fields.
- **Strict Rule Constraints**: `REQUIRE` and `PREFER` rules strictly require non-empty `compliance_scope`; prohibitions (`DENY`) operate without compliance scopes.

### 2. Constraint Ledger (`agentcontract.constraints`)
- **Versioned Lifecycle Tracking**: Explicit states (`ACTIVE`, `REVOKED`, `SUPERSEDED`, `CONFLICTED`) with validated transition graphs.
- **Fine-Grained Scopes**: Scopes support target resource paths (globs and directory hierarchies), tool identifiers, canonical action kinds (`FILE_READ`, `FILE_WRITE`, `FILE_DELETE`, `TOOL_CALL`, `COMMAND_EXEC`), and target types (`filesystem`, `tool`, `network`, `database`).
- **Conflict Lifecycle**: Supports explicit conflict marking and resolution (`mark_conflicted()`, `resolve_conflict()`) with audit provenance.

### 3. SpecGuard Runtime Enforcement (`agentcontract.guard`)
- **Pre-Action Interception**: Evaluates actions before execution. Violations of `HARD` constraints trigger immediate `BLOCK`, preventing tool invocation completely.
- **Post-Action Validation**: Verifies observed runtime side effects (`ActionObservation`) against ledger rules.
- **Hierarchical Precedence**: `BLOCK` (Hard violation) > `WARN` (Soft / Assumption violation) > `ALLOW`.

### 4. Trace Store & OpenTelemetry Export (`agentcontract.trace`, `agentcontract.adapters.otel`)
- **Immutable Chronological History**: Preserves append-only records of user requests, agent steps, tool calls, tool results, and guard decisions.
- **Deterministic Correlation IDs**: Generates stable 32-hex `traceId` and 16-hex `spanId` representations compliant with the OpenTelemetry (OTLP) wire specification while retaining original identifiers in `agentcontract.*` attributes.

### 5. EvidenceGate Verification (`agentcontract.evidence`)
- **Atomic Verification**: Claims are broken down into discrete statements (`TESTS_PASSED`, `FILE_EXISTS`, `TOOL_SUCCEEDED`, `COMMAND_EXITED_ZERO`, `ACTION_COMPLETED`).
- **Deterministic Verdicts**: Evaluates claims directly against trace evidence:
  - `VERIFIED`: Supported by concrete, recorded trace events.
  - `CONTRADICTED`: Proven false by contradictory trace data (e.g. tool returned error status).
  - `UNVERIFIED`: Lacks sufficient supporting evidence in the trace.
- **Anti-Self-Verification**: Claims cannot verify themselves; only observable tool executions and external state checks can serve as ground truth.

### 6. Reliability Benchmark Harness (`agentcontract.benchmark`)
- Evaluates 13 deterministic reliability scenarios across four control variants:
  - `BASELINE`: Agent without guardrails.
  - `SPECGUARD`: Pre-action constraint enforcement enabled.
  - `EVIDENCEGATE`: Post-execution claim verification enabled.
  - `FULL_AGENTCONTRACT`: Both SpecGuard and EvidenceGate active.

### 7. Codex Harness Integration (`agentcontract.integrations.codex`)
- **Native Lifecycle Hooks**: Real-time integration with OpenAI Codex via `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, and `Stop`.
- **PreToolUse SpecGuard Interception**: Blocks prohibited file modifications (e.g. `secrets/prod.key`) before execution via structured PreToolUse deny payload.
- **Stop Evidence Verification**: Verifies completion claims (e.g. `TESTS_PASSED`) against recorded trace evidence via EvidenceGate.
- **Detailed Documentation**: See [Codex Integration Guide](docs/integrations/codex.md).

---

## Installation

AgentContract requires **Python 3.12+**. It contains zero mandatory third-party SDK dependencies (uses Pydantic and standard library `urllib`).

```bash
# Clone the repository
git clone https://github.com/12041720/AgentContract.git
cd AgentContract

# Install in editable mode with development dependencies
python -m pip install -e ".[dev]"
```

Verify installation:
```bash
agentcontract --version
```

---

## Command-Line Interface (CLI)

The package provides a built-in CLI for demonstrations and benchmarking:

### 1. View Version
```bash
agentcontract version
```

### 2. Run Demonstration
Runs the end-to-end reliability workflow demonstration:
```bash
# Offline deterministic demo (default, no network calls or API keys needed)
agentcontract demo

# Online demo using configured OpenAI/compatible model gateway (requires OPENAI_API_KEY)
agentcontract demo --online
```

### 3. Run Benchmark Suite
Executes the 13 deterministic evaluation scenarios across all four architecture variants:
```bash
# Terminal table format (default)
agentcontract benchmark

# Markdown table format
agentcontract benchmark --format markdown

# Machine-readable JSON output
agentcontract benchmark --format json
```

### 4. Codex Harness Management
Manage AgentContract lifecycle hooks inside OpenAI Codex project environments:
```bash
# Install hooks to current or specified project (.codex/hooks.json)
agentcontract codex install [--project /path/to/project]

# Check hooks installation and session verification status
agentcontract codex status [--project /path/to/project]

# Uninstall hooks from target project
agentcontract codex uninstall [--project /path/to/project]
```

---

## Configuration Reference

The OpenAI-compatible extraction adapter (`OpenAICompatibleExtractionClient`) and quickstart support the following environment variables:

| Environment Variable | Description | Default |
|---|---|---|
| `OPENAI_API_KEY` | API key for OpenAI or compatible model gateway | *None (triggers offline demo)* |
| `OPENAI_MODEL` | Target language model identifier | `gpt-4o-mini` |
| `OPENAI_BASE_URL` | Base URL of the API gateway | `https://api.openai.com/v1` |
| `OPENAI_RESPONSE_FORMAT` | Format mode: `json_schema` (strict Structured Outputs) or `json_object` (JSON mode) | `json_schema` |
| `OPENAI_TIMEOUT` | Network request timeout in seconds (must be a positive number) | `30.0` (or `120.0` in quickstart) |

### Configuration Files (.env)
AgentContract automatically discovers and loads configuration from `.env` or `.agentcontract.env` in the working directory or parent directories. It supports environment variable expansion (including PowerShell `$env:VAR` and standard `${VAR}` / `$VAR` syntax):

```ini
# .env (automatically ignored by git)
OPENAI_API_KEY="your-api-key"
OPENAI_MODEL="gpt-4o-mini"
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_RESPONSE_FORMAT="json_schema"
OPENAI_TIMEOUT="30"

# Also supports variable expansion and PowerShell syntax, e.g.:
# OPENAI_API_KEY="${HOST_KEY}"
# $env:OPENAI_API_KEY = $env:HOST_KEY
```

### Using Generic OpenAI-Compatible Endpoints
To use AgentContract with third-party gateways (e.g. DeepSeek, vLLM, LiteLLM, Ollama):
```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="https://your-gateway.example.com/v1"
export OPENAI_MODEL="deepseek-v4-flash"
export OPENAI_RESPONSE_FORMAT="json_object"
export OPENAI_TIMEOUT="120"

python examples/quickstart.py
```

---

## Python API Usage

```python
from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime import AgentContractRuntime
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.evidence.models import Claim, ClaimType

# 1. Initialize Runtime
runtime = AgentContractRuntime(trace_id="session_trace_001")

# 2. Add an Enforceable Hard Constraint
runtime.add_constraint(
    Constraint(
        id="protect_prod_keys",
        name="protect_prod_keys",
        description="Never write to or delete secrets/prod.key",
        strength=ConstraintStrength.HARD,
        rule_effect=RuleEffect.DENY,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_text="Do not touch secrets/prod.key",
            author="User",
        ),
        scope=ConstraintScope(
            target_type="filesystem",
            paths=("secrets/prod.key",),
            actions=("FILE_WRITE", "FILE_DELETE"),
        ),
    )
)

# 3. Guarded Execution of an Action
def tool_executor(action, tool_call):
    return ToolExecutionOutcome.success(output="File written")

prohibited_action = Action(
    action_kind=ActionKind.FILE_WRITE,
    tool_name="write_file",
    target_path="secrets/prod.key",
    target_type="filesystem",
)

result = runtime.execute(prohibited_action, executor=tool_executor)
print("Blocked by SpecGuard?", result.is_blocked)  # True
print("Tool actually executed?", result.executed)   # False

# 4. Evidence-Grounded Claim Verification
claims = [
    Claim(
        claim_id="cl_01",
        claim_type=ClaimType.TESTS_PASSED,
        description="All tests passed with exit code 0",
        trace_id=runtime.trace_id,
        command="pytest",
        expected_exit_code=0,
    )
]

verification = runtime.verify_claims(claims)
for eval_record in verification.evaluations:
    print(f"Claim: {eval_record.claim.description} -> Verdict: {eval_record.verdict}")
```

---

## Security & Authority Model

AgentContract separates generative candidate proposals from deterministic verification:

1. **Untrusted LLM Output**: Model output is treated as raw untrusted JSON. Prompts are guided with explicit task rules, but the output can never assert its own authority, rewrite provenance sources (`USER` vs `AGENT_INFERENCE`), or inflate constraint strength.
2. **Deterministic Domain Gates**: Extracted candidate models pass through strict Pydantic validation. Invalid schemas, missing compliance scopes on `REQUIRE` rules, or spoofed attributes are rejected immediately.
3. **Pre-Action Enforcement**: SpecGuard executes independently of the model. Prohibited actions are blocked in code before network or filesystem access can occur.
4. **Observable Evidence Grounding**: EvidenceGate relies solely on durable records in `TraceStore`. A completion claim is only marked `VERIFIED` if verified evidence exists within the trace.

---

## Reliability Benchmark & Metrics

The benchmark suite evaluates how agent architectures handle adversarial conditions, drift, and false assertions across 13 standardized scenarios:

### Metric Definitions

- **Constraint Violation Rate (CVR)**: Percentage of prohibited actions that were executed. *(Lower is better; 0.0% is optimal)*
- **Unsupported Completion Rate (UCR)**: Percentage of false or unbacked completion claims accepted without verification. *(Lower is better; 0.0% is optimal)*
- **False Blocking Rate (FBR)**: Percentage of safe, compliant actions mistakenly blocked pre-action. *(Lower is better; 0.0% is optimal)*
- **Task Success Rate (TSR)**: Percentage of scenarios where all required goals completed without violations or false blocks. *(Higher is better)*
- **Extra Tool Calls**: Number of tool invocations performed beyond scenario ground truth requirements.
- **Latency Overhead**: Mean execution time added per scenario by constraint evaluation and trace recording.

> **Note on Benchmark Scope**: Benchmark results reflect deterministic evaluation scenarios designed to test control-plane mechanics under defined conditions. They evaluate architectural guarantees rather than predicting general LLM capabilities on open-ended creative tasks.

---

## License

MIT License. See [LICENSE](LICENSE) for details.
