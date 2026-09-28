"""End-to-end integration tests connecting extraction layer with AgentContractRuntime and EvidenceGate."""

import sys
from typing import Any
import pytest

from agentcontract.constraints.models import ConstraintSource, ConstraintStrength, RuleEffect
from agentcontract.evidence.models import ClaimType, ClaimVerdict
from agentcontract.extraction.claims import ClaimExtractor
from agentcontract.extraction.client import FakeStructuredExtractionClient
from agentcontract.extraction.helpers import extract_and_verify_claims
from agentcontract.extraction.requirements import RequirementExtractor
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.runtime.session import AgentContractRuntime


def test_scenario_14_and_full_product_e2e_loop() -> None:
    """Full product lifecycle integrating requirements extraction, runtime enforcement,
    and completion claim extraction & verification."""

    # 1. User states requirements in natural language:
    user_prompt = "You may run pytest and build, but never write to /etc/hosts or delete files."

    req_client = FakeStructuredExtractionClient(
        {
            "constraints": [
                {
                    "name": "forbid_hosts_write",
                    "description": "Never write to /etc/hosts",
                    "strength": "HARD",
                    "rule_effect": "DENY",
                    "scope": {
                        "paths": ["/etc/hosts"],
                        "actions": ["write"],
                    },
                }
            ]
        }
    )

    req_extractor = RequirementExtractor(req_client)
    req_res = req_extractor.extract(user_prompt, source=ConstraintSource.USER, author="user")
    assert req_res.is_success is True
    assert len(req_res.items) == 1
    extracted_constraint = req_res.items[0]

    # 2. Runtime initialized
    runtime = AgentContractRuntime()

    # Caller explicitly registers the extracted constraint into the runtime ledger
    runtime.add_constraint(extracted_constraint)
    assert len(runtime.ledger) == 1

    # 3. Agent attempts a forbidden action -> SpecGuard HARD BLOCK!
    block_res = runtime.execute(
        Action(
            tool_name="bash",
            action_kind=ActionKind.FILE_WRITE,
            target_path="/etc/hosts",
            paths=["/etc/hosts"],
        ),
        executor=lambda a, c: ToolExecutionOutcome.success(output="hacked"),
    )
    assert block_res.is_blocked is True
    assert block_res.executed is False

    # 4. Agent attempts an allowed action -> Executes successfully!
    def run_tests_executor(action: Action, tool_call: Any) -> ToolExecutionOutcome:
        return ToolExecutionOutcome.success(
            output="collected 42 items\n42 passed in 1.2s",
            exit_code=0,
        )

    exec_res = runtime.execute(
        Action(
            tool_name="pytest",
            action_kind=ActionKind.COMMAND_EXEC,
            payload={"command": "pytest -v"},
        ),
        executor=run_tests_executor,
    )
    assert exec_res.is_success is True
    assert exec_res.executed is True

    # 5. Agent returns completion text:
    completion_text = "I ran pytest successfully with 42 passed tests, and I also built dist/app.bin"

    claim_client = FakeStructuredExtractionClient(
        {
            "claims": [
                {
                    "claim_type": "TOOL_SUCCEEDED",
                    "description": "pytest ran successfully",
                    "tool_name": "pytest",
                },
                {
                    "claim_type": "FILE_EXISTS",
                    "description": "Output binary dist/app.bin exists",
                    "target_path": "dist/app.bin",
                },
            ]
        }
    )

    claim_extractor = ClaimExtractor(claim_client)

    # 6. Extract and verify claims against runtime's TraceStore using EvidenceGate
    extraction_res, verification_res = extract_and_verify_claims(
        extractor=claim_extractor,
        text=completion_text,
        runtime=runtime,
    )

    assert extraction_res.is_success is True
    assert len(extraction_res.items) == 2

    # Verify claim evaluations:
    # Claim 1: TOOL_SUCCEEDED for tool_name="pytest" -> supported by executed tool result!
    eval1 = verification_res.get(extraction_res.items[0].claim_id)
    assert eval1 is not None
    assert eval1.verdict == ClaimVerdict.VERIFIED
    assert len(eval1.supporting_evidence) > 0

    # Claim 2: FILE_EXISTS for "dist/app.bin" -> never generated or executed -> UNVERIFIED!
    eval2 = verification_res.get(extraction_res.items[1].claim_id)
    assert eval2 is not None
    assert eval2.verdict == ClaimVerdict.UNVERIFIED


def test_scenario_18_no_provider_specific_dependencies_in_extraction_package() -> None:
    """18. Provider-specific types or SDKs (openai, anthropic, google) must be absent from core."""
    import agentcontract.extraction
    import agentcontract.extraction.client
    import agentcontract.extraction.models
    import agentcontract.extraction.requirements
    import agentcontract.extraction.claims

    disallowed_vendors = ["openai", "anthropic", "google.generativeai", "langchain"]
    for mod_name in list(sys.modules.keys()):
        for vendor in disallowed_vendors:
            assert not mod_name.startswith(vendor), f"Found forbidden vendor module loaded: {mod_name}"
