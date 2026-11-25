from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import List, Optional

try:
    from .engine import RegressionEngine
    from .models import (
        STATUS_PASS,
        STATUS_PASS_REFERENCE_VERIFIED,
        STATUS_PASS_TESTBENCH_ONLY,
        TestResult,
    )
except (ImportError, ValueError):
    from rtl_framework.engine import RegressionEngine
    from rtl_framework.models import (
        STATUS_PASS,
        STATUS_PASS_REFERENCE_VERIFIED,
        STATUS_PASS_TESTBENCH_ONLY,
        TestResult,
    )

__version__ = "1.0.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rtl-framework",
        description="RTL Regression and Verification Framework - Automated HDL Verification Engine"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 'run' subcommand
    run_parser = subparsers.add_parser("run", help="Run automated RTL regression and verification")
    _add_run_arguments(run_parser)

    # 'replay' subcommand
    replay_parser = subparsers.add_parser("replay", help="Replay a historic execution run by Run ID")
    replay_parser.add_argument("run_id", type=str, help="Historic Run ID or prefix to replay")
    replay_parser.add_argument("--project", "--project-dir", dest="project_dir", type=str, default=None, help="Root directory of HDL project")
    replay_parser.add_argument("--config", type=str, default=None, help="Path to configuration JSON")

    # Add run arguments to top-level parser too, allowing 'rtl-framework --project ...'
    _add_run_arguments(parser)

    return parser


def _add_run_arguments(p: argparse.ArgumentParser):
    p.add_argument("--project", "--project-dir", dest="project_dir", type=str, default=None, help="Root directory of HDL project (default: current directory)")
    p.add_argument("--config", type=str, default=None, help="Path to project configuration JSON")
    p.add_argument("--simulator", choices=["icarus", "iverilog", "questa", "modelsim", "vsim", "edalize", "verilator"], default=None, help="Simulator adapter backend")
    p.add_argument("--force", action="store_true", help="Force re-run of all verification plans, bypassing cache")
    p.add_argument("--serial", action="store_true", help="Run simulations sequentially instead of in parallel")
    p.add_argument("--workers", type=int, default=4, help="Maximum worker threads for simulation")
    p.add_argument("--duts", nargs="*", help="Specific DUT names to filter and verify")
    p.add_argument("--timeout", type=float, default=None, help="Simulation execution timeout in seconds")


def run_command(args: argparse.Namespace) -> int:
    project_root = Path(args.project_dir).resolve() if args.project_dir else Path.cwd().resolve()
    config_file = Path(args.config).resolve() if args.config else None

    # If config not explicitly passed, check if project_root / config.json exists
    if not config_file and (project_root / "config.json").exists():
        config_file = (project_root / "config.json").resolve()

    engine = RegressionEngine(
        root_dir=project_root,
        config_path=config_file,
        simulator=args.simulator,
        timeout=args.timeout
    )

    if getattr(args, "command", None) == "replay" and getattr(args, "run_id", None):
        results = engine.replay_run(args.run_id)
    else:
        results = engine.run_regression(
            force_rerun=args.force,
            parallel=not args.serial,
            max_workers=args.workers,
            dut_filter=args.duts
        )

    # Determine exit code: 1 if any plan had a functional failure, compile error, or simulation failure
    error_statuses = {
        "FUNCTIONAL FAIL",
        "INVALID_OUTPUT",
        "APPROXIMATION_OUT_OF_BOUND",
        "REFERENCE_UNVALIDATED",
        "COMPILE ERROR",
        "INTERFACE ERROR",
        "TIMEOUT",
        "INCOMPLETE",
        "INVALID RESULTS",
        "REFERENCE_DISPUTED",
        "LICENSE ERROR",
        "SIMULATION ERROR",
    }
    has_errors = any(r.status in error_statuses for r in results)
    return 1 if has_errors else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Default to 'run' if no subcommand was explicitly matched but args were provided
    if args.command is None:
        args.command = "run"

    try:
        return run_command(args)
    except KeyboardInterrupt:
        print("\n[ABORTED] Verification run interrupted by user.")
        return 130
    except Exception as exc:
        print(f"\n[ERROR] Framework execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
