"""AgentContract Command Line Interface (CLI)."""

import argparse
import json
import os
import sys
from typing import Sequence

import agentcontract
from agentcontract.benchmark.models import BenchmarkReport, BenchmarkVariant
from agentcontract.benchmark.runner import BenchmarkRunner


def format_benchmark_text(report: BenchmarkReport) -> str:
    """Format benchmark report into a clean, human-readable terminal table."""
    lines = [
        "=" * 105,
        f"AgentContract Reliability Benchmark Report (Run ID: {report.run_id})",
        f"Scenarios: {report.scenario_count} | Repetitions: {report.repetitions} | Timestamp: {report.created_at.isoformat()}",
        "-" * 105,
        f"{'Variant':<22} {'CVR':>8} {'UCR':>8} {'FBR':>8} {'TSR':>8} {'Extra Calls':>13} {'Avg Latency':>13} {'Overhead':>13}",
        "-" * 105,
    ]
    for variant in (
        BenchmarkVariant.BASELINE,
        BenchmarkVariant.SPECGUARD,
        BenchmarkVariant.EVIDENCEGATE,
        BenchmarkVariant.FULL_AGENTCONTRACT,
    ):
        m = report.metrics.get(variant)
        if not m:
            continue
        cvr = f"{m.constraint_violation_rate * 100:.1f}%"
        ucr = f"{m.unsupported_completion_rate * 100:.1f}%"
        fbr = f"{m.false_blocking_rate * 100:.1f}%"
        tsr = f"{m.task_success_rate * 100:.1f}%"
        extra = str(m.total_extra_tool_calls)
        lat = f"{m.avg_latency_ms:.2f}ms"
        overhead = f"+{m.latency_overhead_ms:.2f}ms" if m.latency_overhead_ms is not None else "-"
        lines.append(
            f"{m.variant.value:<22} {cvr:>8} {ucr:>8} {fbr:>8} {tsr:>8} {extra:>13} {lat:>13} {overhead:>13}"
        )
    lines.append("=" * 105)
    return "\n".join(lines)


def format_benchmark_markdown(report: BenchmarkReport) -> str:
    """Format benchmark report into a Markdown table."""
    lines = [
        f"### AgentContract Reliability Benchmark Report (Run: `{report.run_id}`)",
        "",
        f"- Scenarios evaluated: {report.scenario_count}",
        f"- Repetitions per scenario: {report.repetitions}",
        f"- Timestamp: {report.created_at.isoformat()}",
        "",
        "| Variant | CVR | UCR | FBR | TSR | Extra Calls | Avg Latency | Latency Overhead |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for variant in (
        BenchmarkVariant.BASELINE,
        BenchmarkVariant.SPECGUARD,
        BenchmarkVariant.EVIDENCEGATE,
        BenchmarkVariant.FULL_AGENTCONTRACT,
    ):
        m = report.metrics.get(variant)
        if not m:
            continue
        cvr = f"{m.constraint_violation_rate * 100:.1f}%"
        ucr = f"{m.unsupported_completion_rate * 100:.1f}%"
        fbr = f"{m.false_blocking_rate * 100:.1f}%"
        tsr = f"{m.task_success_rate * 100:.1f}%"
        extra = str(m.total_extra_tool_calls)
        lat = f"{m.avg_latency_ms:.2f}ms"
        overhead = f"+{m.latency_overhead_ms:.2f}ms" if m.latency_overhead_ms is not None else "-"
        lines.append(
            f"| `{m.variant.value}` | {cvr} | {ucr} | {fbr} | {tsr} | {extra} | {lat} | {overhead} |"
        )
    return "\n".join(lines)


def run_demo_command(online: bool = False) -> int:
    """Run the end-to-end quickstart demonstration."""
    from examples.quickstart import run_quickstart

    if not online:
        # Guarantee offline execution without network calls
        orig_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            return run_quickstart()
        finally:
            if orig_key is not None:
                os.environ["OPENAI_API_KEY"] = orig_key
    else:
        return run_quickstart()


def run_benchmark_command(repetitions: int = 1, fmt: str = "text") -> int:
    """Execute the standard 13-scenario reliability benchmark harness."""
    runner = BenchmarkRunner()
    report = runner.run(repetitions=repetitions)

    if fmt == "json":
        print(report.model_dump_json(indent=2))
    elif fmt == "markdown":
        print(format_benchmark_markdown(report))
    else:
        print(format_benchmark_text(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line parser."""
    parser = argparse.ArgumentParser(
        prog="agentcontract",
        description="AgentContract: Runtime constraint tracking and evidence-grounded verification.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"AgentContract {agentcontract.__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # version subcommand
    subparsers.add_parser("version", help="Print AgentContract version and exit.")

    # demo subcommand
    demo_parser = subparsers.add_parser("demo", help="Run end-to-end reliability workflow demonstration.")
    demo_parser.add_argument(
        "--online",
        action="store_true",
        default=False,
        help="Run online using OPENAI_API_KEY (default: offline deterministic demo without network calls).",
    )

    # benchmark subcommand
    bench_parser = subparsers.add_parser(
        "benchmark",
        help="Run reliability evaluation benchmark across 13 scenarios and print results.",
    )
    bench_parser.add_argument(
        "--repetitions",
        type=int,
        default=1,
        help="Number of evaluation repetitions per scenario (default: 1).",
    )
    bench_parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output report format (default: text).",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "version":
        print(f"AgentContract {agentcontract.__version__}")
        return 0

    if args.command == "demo":
        return run_demo_command(online=args.online)

    if args.command == "benchmark":
        return run_benchmark_command(repetitions=args.repetitions, fmt=args.format)

    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
