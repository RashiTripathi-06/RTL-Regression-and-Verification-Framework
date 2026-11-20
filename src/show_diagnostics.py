#!/usr/bin/env python3
"""Helper script to display detailed failing vector diagnostics from regression summary."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
summary_file = ROOT / "reports" / "regression_summary.json"

if not summary_file.exists():
    print(f"Summary file not found: {summary_file}")
    sys.exit(1)

data = json.loads(summary_file.read_text(encoding="utf-8"))

target_plan = sys.argv[1] if len(sys.argv) > 1 else "adder_buggy__tb_adder"

found = False
for r in data.get("results", []):
    if r.get("plan_id") == target_plan:
        found = True
        print(f"Plan ID    : {r['plan_id']}")
        print(f"DUT Name   : {r['dut_name']}")
        print(f"Testbench  : {r['tb_name']}")
        print(f"Status     : {r['status']}")
        print(f"Diagnostic : {r['diagnostic_summary']}")
        print(f"Failing Vectors Breakdown (first {min(10, len(r.get('failing_vectors', [])))}):")
        for v in r.get("failing_vectors", [])[:10]:
            if "raw" in v:
                print(f"  [Assertion Failure] {v['raw']}")
            else:
                idx = v.get("index", "?")
                inputs = v.get("inputs", {})
                act = v.get("actual_outputs", {})
                exp = v.get("expected_outputs", {})
                in_str = ", ".join(f"{k}={val}" for k, val in inputs.items())
                act_str = ", ".join(f"{k}={val}" for k, val in act.items())
                exp_str = ", ".join(f"{k}={val}" for k, val in exp.items())
                print(f"  [Index {idx:>3}] Inputs: ({in_str}) -> Actual: ({act_str}) vs Expected: ({exp_str})")
        break

if not found:
    print(f"Plan '{target_plan}' not found in results.")
