"""CLI bridge called by OpenCode project plugin."""

import json
from pathlib import Path
import sys
from typing import Any

from agentcontract.adapters.opencode import evaluate_opencode_tool_call


def main() -> None:
    """Main CLI entry point for OpenCode plugin communication."""
    if len(sys.argv) < 2 or sys.argv[1] != "check":
        print(json.dumps({"decision": "BLOCK", "reasons": ["Invalid bridge arguments"]}))
        sys.exit(1)

    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"decision": "BLOCK", "reasons": ["Empty input to bridge"]}))
            sys.exit(1)

        payload = json.loads(raw_input)
        project_dir = Path(payload.get("project_dir", "."))
        tool = str(payload.get("tool", ""))
        call_id = str(payload.get("call_id", ""))
        session_id = str(payload.get("session_id", ""))
        args = payload.get("args", {})

        result = evaluate_opencode_tool_call(
            project_dir=project_dir,
            tool=tool,
            args=args,
            call_id=call_id,
            session_id=session_id,
        )
        print(json.dumps(result))
        sys.exit(0)

    except Exception as e:
        print(
            json.dumps(
                {
                    "decision": "BLOCK",
                    "reasons": [f"Bridge internal error: {e}"],
                    "violating_constraint_ids": ["ERR_BRIDGE"],
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
