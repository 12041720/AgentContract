"""Tests for external tool event adapters and normalization."""

import json
import pytest

from agentcontract.adapters.exceptions import AdapterValidationError
from agentcontract.adapters.tool_events import (
    ExternalToolCallRecord,
    ExternalToolResultRecord,
    ToolEventAdapter,
)
from agentcontract.guard.models import Action, ActionKind, ActionObservation
from agentcontract.runtime.models import ToolExecutionOutcome
from agentcontract.trace.models import ToolCall, ToolResult, ToolResultStatus


def test_tool_call_mapping_flat_dict() -> None:
    record = {
        "call_id": "call_001",
        "tool_name": "read_file",
        "arguments": {"path": "src/main.py", "encoding": "utf-8"},
    }
    tc = ToolEventAdapter.to_tool_call(record)
    assert isinstance(tc, ToolCall)
    assert tc.call_id == "call_001"
    assert tc.tool_name == "read_file"
    assert tc.arguments["path"] == "src/main.py"
    assert tc.arguments["encoding"] == "utf-8"


def test_tool_call_mapping_openai_format() -> None:
    record = {
        "id": "call_openai_123",
        "type": "function",
        "function": {
            "name": "write_file",
            "arguments": json.dumps({"path": "output.txt", "content": "hello world"}),
        },
    }
    tc = ToolEventAdapter.to_tool_call(record)
    assert isinstance(tc, ToolCall)
    assert tc.call_id == "call_openai_123"
    assert tc.tool_name == "write_file"
    assert tc.arguments["path"] == "output.txt"
    assert tc.arguments["content"] == "hello world"


def test_tool_call_mapping_object_with_attributes() -> None:
    class DummyToolCallObj:
        id = "call_obj_999"
        name = "grep_search"
        arguments = {"query": "def test_"}

    tc = ToolEventAdapter.to_tool_call(DummyToolCallObj())
    assert tc.call_id == "call_obj_999"
    assert tc.tool_name == "grep_search"
    assert tc.arguments["query"] == "def test_"


def test_tool_call_malformed_rejected() -> None:
    # Missing call_id
    with pytest.raises(AdapterValidationError, match="non-empty string 'call_id'"):
        ToolEventAdapter.to_tool_call({"tool_name": "foo", "arguments": {}})

    # Missing tool_name
    with pytest.raises(AdapterValidationError, match="non-empty string 'tool_name'"):
        ToolEventAdapter.to_tool_call({"call_id": "call_1", "arguments": {}})

    # Invalid JSON string arguments
    with pytest.raises(AdapterValidationError, match="Failed to parse JSON string arguments"):
        ToolEventAdapter.to_tool_call({
            "call_id": "call_1",
            "tool_name": "foo",
            "arguments": "not-valid-json{",
        })

    # JSON string decodes to non-mapping
    with pytest.raises(AdapterValidationError, match="must decode to a JSON object"):
        ToolEventAdapter.to_tool_call({
            "call_id": "call_1",
            "tool_name": "foo",
            "arguments": "[\"item1\", \"item2\"]",
        })

    # None record
    with pytest.raises(AdapterValidationError, match="cannot be None"):
        ToolEventAdapter.to_tool_call(None)

    # Unsupported record type
    with pytest.raises(AdapterValidationError, match="Unsupported tool call record type"):
        ToolEventAdapter.to_tool_call(42)


def test_to_action_field_mapping_and_path_discovery() -> None:
    # Auto-infers path from arguments
    record = {
        "call_id": "call_write_1",
        "tool_name": "write_file",
        "arguments": {"path": "src/module.py", "content": "x = 1"},
    }
    action = ToolEventAdapter.to_action(record)
    assert isinstance(action, Action)
    assert action.action_kind == ActionKind.FILE_WRITE
    assert action.tool_name == "write_file"
    assert action.target_path == "src/module.py"
    assert action.paths == ("src/module.py",)

    # Command execution inference
    cmd_record = {
        "call_id": "call_bash_1",
        "tool_name": "run_command",
        "arguments": {"command": "pytest -v"},
    }
    cmd_action = ToolEventAdapter.to_action(cmd_record)
    assert cmd_action.action_kind == ActionKind.COMMAND_EXEC
    assert cmd_action.tool_name == "run_command"


def test_to_action_rejects_set_paths() -> None:
    record = {
        "call_id": "call_1",
        "tool_name": "test_tool",
        "arguments": {},
    }
    with pytest.raises(AdapterValidationError, match="ordered sequence"):
        ToolEventAdapter.to_action(record, paths={"path1", "path2"})


def test_tool_result_status_mapping() -> None:
    # SUCCESS variants
    for s in ("SUCCESS", "success", "OK", "ok", 0, "0"):
        res = ToolEventAdapter.to_tool_result({"call_id": "c1", "status": s, "output": "done"})
        assert res.status == ToolResultStatus.SUCCESS

    # ERROR variants
    for s in ("ERROR", "error", "FAILED", "failed", "FAILURE", 1, "1"):
        res = ToolEventAdapter.to_tool_result({"call_id": "c1", "status": s, "error": "failed"})
        assert res.status == ToolResultStatus.ERROR

    # TIMEOUT variants
    for s in ("TIMEOUT", "timeout", "timed_out"):
        res = ToolEventAdapter.to_tool_result({"call_id": "c1", "status": s})
        assert res.status == ToolResultStatus.TIMEOUT

    # CANCELLED variants
    for s in ("CANCELLED", "cancelled", "CANCELED", "canceled"):
        res = ToolEventAdapter.to_tool_result({"call_id": "c1", "status": s})
        assert res.status == ToolResultStatus.CANCELLED

    # Default to ERROR if error or non-zero exit_code is present
    res_err = ToolEventAdapter.to_tool_result({"call_id": "c1", "error": "Disk full"})
    assert res_err.status == ToolResultStatus.ERROR

    res_exit = ToolEventAdapter.to_tool_result({"call_id": "c1", "exit_code": 2})
    assert res_exit.status == ToolResultStatus.ERROR

    # Default to SUCCESS if no status, error is None, exit_code is 0
    res_default = ToolEventAdapter.to_tool_result({"call_id": "c1", "output": "ok"})
    assert res_default.status == ToolResultStatus.SUCCESS


def test_tool_result_unknown_status_rejected() -> None:
    with pytest.raises(AdapterValidationError, match="Unknown or unsupported tool result status"):
        ToolEventAdapter.to_tool_result({"call_id": "c1", "status": "MAYBE"})


def test_tool_result_output_decoding_json_string() -> None:
    record = {
        "call_id": "c_json",
        "output": json.dumps({"passed": 5, "failed": 0}),
    }
    res = ToolEventAdapter.to_tool_result(record)
    assert res.output["passed"] == 5
    assert res.output["failed"] == 0


def test_tool_result_rejects_invalid_durable_types() -> None:
    # sets are rejected as durable trace values
    record = {
        "call_id": "c_set",
        "output": {"keys": {"a", "b"}},
    }
    with pytest.raises(AdapterValidationError, match="sets are not supported"):
        ToolEventAdapter.to_tool_result(record)


def test_tool_execution_outcome_mapping_and_path_merge() -> None:
    record = {
        "call_id": "c_outcome",
        "status": "SUCCESS",
        "output": {"written": True},
        "changed_paths": ["file_a.txt"],
        "duration_ms": 15.5,
    }
    outcome = ToolEventAdapter.to_tool_execution_outcome(
        record,
        changed_paths=["file_b.txt"],
        accessed_paths=["file_c.txt"],
        action_kind=ActionKind.FILE_WRITE,
        target_type="filesystem",
        tool_name="writer",
    )
    assert isinstance(outcome, ToolExecutionOutcome)
    assert outcome.status == ToolResultStatus.SUCCESS
    assert "file_a.txt" in outcome.changed_paths
    assert "file_b.txt" in outcome.changed_paths
    assert "file_c.txt" in outcome.accessed_paths
    assert outcome.duration_ms == 15.5
    assert outcome.action_kind == ActionKind.FILE_WRITE
    assert outcome.target_type == "filesystem"


def test_tool_execution_outcome_rejects_set_paths() -> None:
    record = {"call_id": "c1", "status": "SUCCESS"}
    with pytest.raises(AdapterValidationError, match="ordered sequence"):
        ToolEventAdapter.to_tool_execution_outcome(record, changed_paths={"path1"})

    with pytest.raises(AdapterValidationError, match="ordered sequence"):
        ToolEventAdapter.to_tool_execution_outcome(record, accessed_paths={"path1"})


def test_action_observation_mapping() -> None:
    record = {
        "call_id": "c_obs",
        "status": "SUCCESS",
        "output": "done",
        "exit_code": 0,
    }
    obs = ToolEventAdapter.to_action_observation(
        record,
        changed_paths=("output.log",),
        tool_name="logger",
        action_kind=ActionKind.FILE_WRITE,
        target_type="filesystem",
    )
    assert isinstance(obs, ActionObservation)
    assert obs.tool_name == "logger"
    assert obs.changed_paths == ("output.log",)
    assert obs.action_kind == ActionKind.FILE_WRITE
    assert obs.exit_code == 0


def test_tool_events_rejects_non_string_paths_in_to_action() -> None:
    record = {"call_id": "c1", "tool_name": "write_file", "arguments": {}}

    # Non-string types in paths sequence
    for invalid_path in [123, True, False, {"file": "a.txt"}, ["nested"], object()]:
        with pytest.raises(AdapterValidationError, match="items must be strings"):
            ToolEventAdapter.to_action(record, paths=[invalid_path])  # type: ignore[list-item]

    # Bare string is rejected (must be ordered list/tuple)
    with pytest.raises(AdapterValidationError, match="ordered list or tuple"):
        ToolEventAdapter.to_action(record, paths="not_a_list")  # type: ignore[arg-type]

    # Blank string inside sequence is rejected
    with pytest.raises(AdapterValidationError, match="cannot be empty or blank"):
        ToolEventAdapter.to_action(record, paths=["   "])


def test_tool_events_rejects_non_string_paths_in_outcome_and_observation() -> None:
    record = {"call_id": "c1", "status": "SUCCESS"}

    # Explicit argument validation
    for invalid_val in [123, True, False, {"p": "v"}, ["nested"], 4.5]:
        with pytest.raises(AdapterValidationError, match="items must be strings"):
            ToolEventAdapter.to_tool_execution_outcome(record, changed_paths=[invalid_val])  # type: ignore[list-item]

        with pytest.raises(AdapterValidationError, match="items must be strings"):
            ToolEventAdapter.to_tool_execution_outcome(record, accessed_paths=[invalid_val])  # type: ignore[list-item]

    # Bare strings are rejected for changed_paths / accessed_paths
    with pytest.raises(AdapterValidationError, match="ordered list or tuple"):
        ToolEventAdapter.to_tool_execution_outcome(record, changed_paths="foo.txt")  # type: ignore[arg-type]

    with pytest.raises(AdapterValidationError, match="ordered list or tuple"):
        ToolEventAdapter.to_tool_execution_outcome(record, accessed_paths="foo.txt")  # type: ignore[arg-type]

    # External record dictionary paths validation
    with pytest.raises(AdapterValidationError, match="items must be strings"):
        ToolEventAdapter.to_tool_execution_outcome({"call_id": "c1", "changed_paths": [123, True]})

    with pytest.raises(AdapterValidationError, match="items must be strings"):
        ToolEventAdapter.to_tool_execution_outcome({"call_id": "c1", "accessed_paths": [{"nested": "dict"}]})

    with pytest.raises(AdapterValidationError, match="ordered sequence"):
        ToolEventAdapter.to_tool_execution_outcome({"call_id": "c1", "changed_paths": {"set_a", "set_b"}})

    with pytest.raises(AdapterValidationError, match="ordered sequence"):
        ToolEventAdapter.to_tool_execution_outcome({"call_id": "c1", "accessed_paths": frozenset(["fz_a"])})

    # ActionObservation propagates the same strict validation
    with pytest.raises(AdapterValidationError, match="items must be strings"):
        ToolEventAdapter.to_action_observation(record, changed_paths=[999])  # type: ignore[list-item]

    with pytest.raises(AdapterValidationError, match="items must be strings"):
        ToolEventAdapter.to_action_observation({"call_id": "c1", "changed_paths": [False]})

