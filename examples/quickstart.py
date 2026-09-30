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

import sys
from agentcontract.demo import run_quickstart

if __name__ == "__main__":
    sys.exit(run_quickstart())
