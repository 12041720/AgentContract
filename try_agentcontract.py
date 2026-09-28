from agentcontract.constraints.models import (
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStrength,
    RuleEffect,
)
from agentcontract.guard.models import Action, ActionKind
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.runtime.session import AgentContractRuntime
from agentcontract.evidence.models import Claim, ClaimType


runtime = AgentContractRuntime()

# 1. 加一条硬约束
constraint = Constraint(
    id="no_hosts_write",
    name="protect_hosts",
    description="禁止修改 /etc/hosts",
    strength=ConstraintStrength.HARD,
    rule_effect=RuleEffect.DENY,
    provenance=ConstraintProvenance(
        source=ConstraintSource.USER,
        source_text="禁止修改 /etc/hosts",
        author="user",
    ),
    scope=ConstraintScope(
        target_type="filesystem",
        paths=("/etc/hosts",),
        actions=("write",),
    ),
)

runtime.add_constraint(constraint)


def executor(action, tool_call):
    print(">>> EXECUTOR 真正执行了:", action.tool_name)

    return ToolExecutionOutcome.success(
        output="command completed",
        exit_code=0,
    )


# 2. 尝试违规操作
blocked = runtime.execute(
    Action(
        tool_name="write_file",
        action_kind=ActionKind.FILE_WRITE,
        target_type="filesystem",
        target_path="/etc/hosts",
        paths=("/etc/hosts",),
        operation="write",
    ),
    executor=executor,
)

print("\n=== Forbidden action ===")
print("Guard:", blocked.pre_decision.decision)
print("Executed:", blocked.executed)


# 3. 执行合法操作
allowed = runtime.execute(
    Action(
        tool_name="pytest",
        action_kind=ActionKind.COMMAND_EXEC,
        operation="execute",
        payload={"command": "pytest -q"},
    ),
    executor=executor,
)

print("\n=== Allowed action ===")
print("Guard:", allowed.pre_decision.decision)
print("Executed:", allowed.executed)
print("Tool result:", allowed.tool_result.status)


# 4. Agent 声称 pytest 成功
claim = Claim(
    claim_id="claim_tests",
    claim_type=ClaimType.TOOL_SUCCEEDED,
    description="pytest executed successfully",
    trace_id=runtime.trace_id,
    tool_name="pytest",
)

verification = runtime.verify_claims([claim])

print("\n=== EvidenceGate ===")
for evaluation in verification.evaluations:
    print(evaluation.claim.description)
    print("Verdict:", evaluation.verdict)
    print("Evidence:", evaluation.supporting_evidence)