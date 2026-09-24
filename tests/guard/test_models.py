"""Tests for SpecGuard domain models, enums, immutability, and serialization."""

import pytest
from pydantic import ValidationError

from agentcontract.common.immutable import FrozenDict
from agentcontract.guard.exceptions import GuardError, GuardValidationError
from agentcontract.guard.models import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
)
from agentcontract.trace.models import (
    ActorKind,
    EventKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    TraceEvent,
    TracePointer,
)


def test_decision_kind_enum_values():
    """DecisionKind must define ALLOW, WARN, and BLOCK."""
    assert DecisionKind.ALLOW == "ALLOW"
    assert DecisionKind.WARN == "WARN"
    assert DecisionKind.BLOCK == "BLOCK"


def test_action_kind_enum_values():
    """ActionKind must cover generic tool, file, command, network, and state operations."""
    assert ActionKind.TOOL_CALL == "TOOL_CALL"
    assert ActionKind.FILE_READ == "FILE_READ"
    assert ActionKind.FILE_WRITE == "FILE_WRITE"
    assert ActionKind.FILE_DELETE == "FILE_DELETE"
    assert ActionKind.COMMAND_EXEC == "COMMAND_EXEC"
    assert ActionKind.NETWORK_REQUEST == "NETWORK_REQUEST"
    assert ActionKind.STATE_CHANGE == "STATE_CHANGE"
    assert ActionKind.GENERIC == "GENERIC"


def test_action_model_immutability():
    """Action must be frozen and prohibit attribute mutation."""
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        target_path="main.py",
        tool_name="editor",
    )
    with pytest.raises(ValidationError):
        action.action_kind = ActionKind.FILE_DELETE  # type: ignore

    with pytest.raises(ValidationError):
        action.target_path = "other.py"  # type: ignore


def test_action_path_and_kind_synchronization():
    """Action automatically synchronizes target_path and paths, and infers TOOL_CALL from tool_name."""
    # target_path populated -> paths automatically contains it
    a1 = Action(action_kind=ActionKind.FILE_READ, target_path="data/config.json")
    assert a1.paths == ("data/config.json",)
    assert a1.target_path == "data/config.json"

    # paths populated -> target_path automatically takes first path
    a2 = Action(action_kind=ActionKind.FILE_WRITE, paths=["src/a.py", "src/b.py"])
    assert a2.target_path == "src/a.py"
    assert a2.paths == ("src/a.py", "src/b.py")

    # tool_name provided with default GENERIC kind -> infers TOOL_CALL
    a3 = Action(tool_name="bash", operation="ls")
    assert a3.action_kind == ActionKind.TOOL_CALL


def test_action_defensive_isolation_and_context_freezing():
    """External mutations to context dict or paths list must not affect Action."""
    raw_ctx = {"env": "prod", "nested": {"level": 1}}
    raw_paths = ["a.py", "b.py"]
    action = Action(
        action_kind=ActionKind.FILE_WRITE,
        paths=raw_paths,
        context=raw_ctx,
    )
    raw_ctx["env"] = "dev"
    raw_paths.append("c.py")

    assert action.context["env"] == "prod"
    assert action.paths == ("a.py", "b.py")
    assert isinstance(action.context, FrozenDict)
    with pytest.raises(TypeError):
        action.context["env"] = "dev"


def test_action_constructors_from_tool_call_and_trace_event():
    """Action.from_tool_call and Action.from_trace_event construct valid Action models."""
    tc = ToolCall(call_id="c-1", tool_name="git", arguments={"cmd": "status"})
    action_tc = Action.from_tool_call(tc, operation="status")
    assert action_tc.action_kind == ActionKind.TOOL_CALL
    assert action_tc.tool_name == "git"
    assert action_tc.operation == "status"
    assert action_tc.payload["cmd"] == "status"

    event = TraceEvent(
        event_id="evt-tc-1",
        trace_id="tr-1",
        session_id="s-1",
        sequence=0,
        actor=ActorKind.AGENT,
        event_kind=EventKind.TOOL_CALL,
        payload=tc,
    )
    action_evt = Action.from_trace_event(event)
    assert action_evt.action_kind == ActionKind.TOOL_CALL
    assert action_evt.tool_name == "git"
    assert action_evt.trace_pointer is not None
    assert action_evt.trace_pointer.trace_id == "tr-1"
    assert action_evt.trace_pointer.event_id == "evt-tc-1"


def test_action_observation_immutability_and_constructors():
    """ActionObservation must be frozen and support from_tool_result constructor."""
    tr = ToolResult(
        call_id="c-1",
        status=ToolResultStatus.SUCCESS,
        output={"files": ["schema.sql"]},
        exit_code=0,
    )
    obs = ActionObservation.from_tool_result(
        tool_result=tr,
        changed_paths=["schema.sql"],
        tool_name="db_migrator",
    )
    assert obs.tool_name == "db_migrator"
    assert obs.changed_paths == ("schema.sql",)
    assert obs.exit_code == 0
    assert obs.output["files"] == ("schema.sql",)

    with pytest.raises(ValidationError):
        obs.exit_code = 1  # type: ignore


def test_guard_decision_immutability_and_properties():
    """GuardDecision must be frozen and provide convenient boolean and consolidation properties."""
    action = Action(action_kind=ActionKind.FILE_WRITE, target_path="secret.key")
    ptr = TracePointer(trace_id="tr-1", event_id="evt-1")

    # Blocked decision
    d_block = GuardDecision(
        decision=DecisionKind.BLOCK,
        action=action,
        matched_constraint_ids=["c-no-secrets"],
        violating_constraint_ids=["c-no-secrets"],
        reasons=["Direct modification of secrets is prohibited."],
        trace_pointer=ptr,
    )
    assert d_block.is_blocked is True
    assert d_block.is_warned is False
    assert d_block.is_allowed is False
    assert d_block.constraint_ids == ("c-no-secrets",)
    assert "Direct modification of secrets is prohibited." in d_block.reason
    assert d_block.trace_pointer == ptr

    with pytest.raises(ValidationError):
        d_block.decision = DecisionKind.ALLOW  # type: ignore

    # Allowed decision
    d_allow = GuardDecision(
        decision=DecisionKind.ALLOW,
        action=action,
    )
    assert d_allow.is_allowed is True
    assert d_allow.is_blocked is False
    assert d_allow.is_warned is False

    # Warned decision
    d_warn = GuardDecision(
        decision=DecisionKind.WARN,
        action=action,
        matched_constraint_ids=["c-soft"],
        violating_constraint_ids=["c-soft"],
        reasons=["Legacy file access"],
    )
    assert d_warn.is_warned is True
    assert d_warn.is_blocked is False
    assert d_warn.is_allowed is False


def test_action_and_decision_serialization_round_trip():
    """Action and GuardDecision must round-trip faithfully through JSON."""
    action = Action(
        action_kind=ActionKind.COMMAND_EXEC,
        tool_name="bash",
        operation="run",
        paths=["deploy.sh", "scripts/init.sh"],
        payload={"args": ["--force"]},
        context={"env": "prod", "debug": False},
        trace_pointer=TracePointer(trace_id="tr-deploy", event_id="e-1", session_id="s-0"),
    )
    action_json = action.model_dump_json()
    rebuilt_action = Action.model_validate_json(action_json)
    assert rebuilt_action == action

    decision = GuardDecision(
        decision=DecisionKind.BLOCK,
        action=action,
        matched_constraint_ids=["c-prod-guard", "c-no-force"],
        violating_constraint_ids=["c-no-force"],
        reasons=["BLOCK: Force flag is prohibited in production."],
        trace_pointer=action.trace_pointer,
        metadata={"evaluated_by": "SpecGuard-v0.1"},
    )
    decision_json = decision.model_dump_json()
    rebuilt_decision = GuardDecision.model_validate_json(decision_json)
    assert rebuilt_decision == decision
    assert rebuilt_decision.decision == DecisionKind.BLOCK
    assert rebuilt_decision.is_blocked is True
    assert rebuilt_decision.action == action
    assert rebuilt_decision.trace_pointer == action.trace_pointer


def test_top_level_package_exports_guard():
    """Verify SpecGuard symbols are exported from root agentcontract package."""
    from agentcontract import (
        Action as RootAction,
        ActionKind as RootActionKind,
        ActionObservation as RootActionObservation,
        DecisionKind as RootDecisionKind,
        GuardDecision as RootGuardDecision,
        GuardError as RootGuardError,
        GuardValidationError as RootGuardValidationError,
        RuleEffect as RootRuleEffect,
        SpecGuard as RootSpecGuard,
        match_scope as RootMatchScope,
    )
    from agentcontract.constraints.models import RuleEffect

    assert RootAction is Action
    assert RootActionKind is ActionKind
    assert RootActionObservation is ActionObservation
    assert RootDecisionKind is DecisionKind
    assert RootGuardDecision is GuardDecision
    assert RootGuardError is GuardError
    assert RootGuardValidationError is GuardValidationError
    assert RootRuleEffect is RuleEffect
    from agentcontract.guard.engine import SpecGuard, match_scope
    assert RootSpecGuard is SpecGuard
    assert RootMatchScope is match_scope
