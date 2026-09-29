"""AgentContract Quickstart: End-to-end reliability control plane demonstration.

This script demonstrates:
1. Natural-language user requirements -> Structured extraction -> Enforceable Constraints.
2. Runtime tool execution with SpecGuard:
   - Allowed tool call -> Executed & recorded in trace.
   - Prohibited tool call -> BLOCKED before execution (never reaches executor).
3. Natural-language agent completion prose -> Structured claims extraction.
4. Completion claim verification with EvidenceGate:
   - Supported claim -> VERIFIED.
   - Unsupported / contradicted claim -> CONTRADICTED / UNVERIFIED.
5. Trace export to OpenTelemetry spans via OTelTraceBridge.

Run directly:
    python examples/quickstart.py
"""

import os
import sys

from agentcontract.adapters.openai import OpenAICompatibleExtractionClient
from agentcontract.adapters.otel import OTelTraceBridge
from agentcontract.adapters.tool_events import ToolEventAdapter
from agentcontract.constraints.models import (
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.evidence.models import ClaimType, ClaimVerdict
from agentcontract.extraction.client import FakeStructuredExtractionClient
from agentcontract.extraction import (
    ClaimExtractor,
    RequirementExtractor,
)
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.runtime import AgentContractRuntime


def run_quickstart() -> int:
    print("=" * 70)
    print("AgentContract Quickstart: End-to-End Reliability Workflow")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. Setup Structured Extraction Client
    # -------------------------------------------------------------------------
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        response_format = os.environ.get("OPENAI_RESPONSE_FORMAT", "json_schema")
        print(f"[1] Using OpenAICompatibleExtractionClient (model={model}, mode={response_format}, base_url={base_url}).")
        client = OpenAICompatibleExtractionClient(
            model=model,
            base_url=base_url,
            response_format_mode=response_format,
            api_key=api_key,
        )
    else:
        print("[1] OPENAI_API_KEY not detected; using deterministic offline client for demo.")
        # Pre-configured responses for demonstration
        canned_req_resp = {
            "constraints": [
                {
                    "name": "protect_production_keys",
                    "description": "Never write to or delete sensitive key files in secrets/",
                    "rule_effect": "DENY",
                    "strength": "HARD",
                    "scope": {
                        "paths": ["secrets/prod.key", "secrets/*"],
                        "actions": ["FILE_WRITE", "FILE_DELETE", "TOOL_CALL"],
                    },
                }
            ]
        }
        canned_claim_resp = {
            "claims": [
                {
                    "claim_type": "TESTS_PASSED",
                    "description": "All test suites passed successfully with exit code 0.",
                    "command": "pytest",
                    "expected_exit_code": 0,
                },
                {
                    "claim_type": "FILE_EXISTS",
                    "description": "Production key file was generated at secrets/prod.key.",
                    "target_path": "secrets/prod.key",
                },
            ]
        }
        client = FakeStructuredExtractionClient(
            responses=[canned_req_resp, canned_claim_resp]
        )

    # -------------------------------------------------------------------------
    # 2. Extract Requirements from Natural Language
    # -------------------------------------------------------------------------
    user_prompt = (
        "Please inspect the repository, run the test suite, and refactor the code. "
        "CRITICAL: Do NOT write to or modify 'secrets/prod.key'. All tests must pass."
    )
    print(f"\n[2] User Requirement:\n    \"{user_prompt}\"")

    req_extractor = RequirementExtractor(client=client)
    req_result = req_extractor.extract(
        text=user_prompt,
        source=ConstraintSource.USER,
        author="User",
        source_location="chat_prompt_001",
    )

    print(f"    Extracted {len(req_result.items)} formal constraint(s):")
    for c in req_result.items:
        print(f"    - [{c.strength}] {c.name} (Effect: {c.rule_effect}, Paths: {c.scope.paths})")

    # -------------------------------------------------------------------------
    # 3. Initialize Runtime with Constraints
    # -------------------------------------------------------------------------
    print("\n[3] Initializing AgentContractRuntime with active constraints...")
    runtime = AgentContractRuntime(trace_id="quickstart_trace_001")
    for c in req_result.items:
        runtime.add_constraint(c)

    # Mock tool executor simulating agent actions
    def simulated_executor(action: Action, tool_call) -> ToolExecutionOutcome:
        if action.tool_name == "read_file":
            return ToolExecutionOutcome.success(
                output={"content": "def main(): pass"},
                accessed_paths=action.paths,
            )
        elif action.tool_name == "run_command":
            return ToolExecutionOutcome.success(
                output="22 passed in 0.15s",
                exit_code=0,
            )
        elif action.tool_name == "write_file":
            # This should NEVER be reached if SpecGuard blocks the action
            raise RuntimeError("CRITICAL VIOLATION: Tool was executed despite prohibition!")
        return ToolExecutionOutcome.success()

    # -------------------------------------------------------------------------
    # 4. Guarded Tool Executions
    # -------------------------------------------------------------------------
    print("\n[4] Executing Agent Actions through SpecGuard...")

    # Action 1: Legitimate read
    act1 = Action(
        action_kind=ActionKind.FILE_READ,
        tool_name="read_file",
        target_path="src/main.py",
        paths=("src/main.py",),
    )
    res1 = runtime.execute(act1, executor=simulated_executor)
    print(f"    Action 1 (read src/main.py): {res1.pre_decision.decision} -> Executed: {res1.executed}")

    # Action 2: Prohibited write to secrets/prod.key
    act2 = Action(
        action_kind=ActionKind.FILE_WRITE,
        tool_name="write_file",
        target_path="secrets/prod.key",
        paths=("secrets/prod.key",),
    )
    res2 = runtime.execute(act2, executor=simulated_executor)
    print(f"    Action 2 (write secrets/prod.key): {res2.pre_decision.decision} -> Blocked: {res2.is_blocked}")
    print(f"    Reason: {res2.pre_decision.reason}")
    print(f"    Tool actually executed? {res2.executed} (Safe!)")

    # Action 3: Run pytest
    act3 = Action(
        action_kind=ActionKind.COMMAND_EXEC,
        tool_name="run_command",
        payload={"command": "pytest"},
    )
    res3 = runtime.execute(act3, executor=simulated_executor)
    print(f"    Action 3 (run pytest): {res3.pre_decision.decision} -> Executed: {res3.executed}")

    # -------------------------------------------------------------------------
    # 5. Extract & Verify Agent Completion Claims
    # -------------------------------------------------------------------------
    agent_final_message = (
        "I have completed all requested work! "
        "All test suites passed successfully with exit code 0. "
        "I also generated the production key file at secrets/prod.key."
    )
    print(f"\n[5] Agent Final Completion Prose:\n    \"{agent_final_message}\"")

    claim_extractor = ClaimExtractor(client=client)
    claim_result = claim_extractor.extract(
        text=agent_final_message,
        trace_id=runtime.trace_id,
    )

    print(f"    Extracted {len(claim_result.items)} completion claim(s):")
    for cl in claim_result.items:
        print(f"    - Claim [{cl.claim_type}]: {cl.description}")

    # Evaluate claims against actual execution trace
    print("\n[6] EvidenceGate Verification Verdicts:")
    verif = runtime.verify_claims(claim_result.items)
    for ev in verif.evaluations:
        status_symbol = "PASS" if ev.is_verified else "FAIL"
        print(f"    [{status_symbol}] {ev.claim.claim_type} -> Verdict: {ev.verdict}")
        print(f"        Statement: {ev.claim.description}")
        print(f"        Reason: {ev.reason}")

    # -------------------------------------------------------------------------
    # 6. OpenTelemetry Trace Export
    # -------------------------------------------------------------------------
    print("\n[7] Exporting execution trace to OpenTelemetry spans...")
    otel_export = OTelTraceBridge.export_trace(runtime.trace_store, runtime.trace_id)
    print(f"    Trace ID: {otel_export.trace_id}")
    print(f"    Exported {len(otel_export.spans)} OTel Spans:")
    for span in otel_export.spans:
        print(f"    - Span: '{span.name}' [ID: {span.span_id}] Status: {span.status_code}")

    print("\n" + "=" * 70)
    print("Summary:")
    print(f"- Total Actions Attempted: 3")
    print(f"- Violations Prevented: 1 (secrets/prod.key write safely blocked)")
    print(f"- Claims Evaluated: {len(verif.evaluations)}")
    print(f"- True Claims Verified: {sum(1 for e in verif.evaluations if e.is_verified)}")
    print(f"- False Claims Intercepted: {sum(1 for e in verif.evaluations if not e.is_verified)}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_quickstart())
