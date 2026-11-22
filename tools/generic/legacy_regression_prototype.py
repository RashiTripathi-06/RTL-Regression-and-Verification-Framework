from __future__ import annotations
import csv
import html
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "framework" / "src"))

from models import (
    STATUS_PASS as PASS,
    STATUS_FUNCTIONAL_FAIL as FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR as COMPILE_ERROR,
    STATUS_SIMULATION_ERROR as SIMULATION_ERROR,
    STATUS_TIMEOUT as TIMEOUT,
    STATUS_INCOMPLETE as INCOMPLETE,
    STATUS_INVALID_RESULTS as INVALID_RESULTS,
    STATUS_INTERFACE_ERROR as INTERFACE_ERROR,
    STATUS_NO_MATCH as NO_MATCH,
    TestResult
)
from auditor import VerificationAuditor
from executor import ExecutionResult

VEC_RE = re.compile(
    r"^VEC idx=(\d+) a=(\d+) b=(\d+) cin=(\d+) sum=([01xXzZ]+) cout=([01xXzZ]+)$",
    re.MULTILINE
)

def read_lut(path: Path):
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        word = int(line, 16)
        rows.append({
            "a": (word >> 10) & 0xF,
            "b": (word >> 6) & 0xF,
            "cin": (word >> 5) & 1,
            "cout": (word >> 4) & 1,
            "sum": word & 0xF,
        })
    return rows

def audit_output(stdout: str, golden: list[dict], expected_count: int):
    """Backwards-compatible wrapper for existing unit tests."""
    auditor = VerificationAuditor()
    fake_exec = ExecutionResult(
        plan_id="compat",
        compile_returncode=0,
        compile_stdout="",
        compile_stderr="",
        sim_returncode=0,
        sim_stdout=stdout,
        sim_stderr="",
        timed_out=False,
        elapsed_seconds=0.1,
        edalize_configured=False
    )
    status, passed, total, failed, diagnostic, _ = auditor.audit(
        exec_res=fake_exec,
        golden_lut=golden,
        expected_vector_count=expected_count
    )
    return status, total, passed, failed, diagnostic

def main():
    from engine import RegressionEngine
    engine = RegressionEngine(root_dir=ROOT)
    engine.run_regression()

if __name__ == "__main__":
    main()
