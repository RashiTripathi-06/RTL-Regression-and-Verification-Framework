import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from auditor import VerificationAuditor
from executor import ExecutionResult
from models import (
    STATUS_PASS as PASS,
    STATUS_FUNCTIONAL_FAIL as FUNCTIONAL_FAIL,
    STATUS_INCOMPLETE as INCOMPLETE,
    STATUS_INVALID_RESULTS as INVALID_RESULTS,
)

def audit_output(stdout: str, golden: list[dict], expected_count: int):
    """Test helper wrapping VerificationAuditor."""
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

def golden_rows():
    rows = []
    for idx in range(512):
        a, b, cin = (idx >> 5) & 15, (idx >> 1) & 15, idx & 1
        total = a + b + cin
        rows.append({"a": a, "b": b, "cin": cin,
                     "sum": total & 15, "cout": (total >> 4) & 1})
    return rows

def log_for(rows, alter=None, omit=None, duplicate=False):
    lines = ["=== TESTBENCH_START ==="]
    for i, row in enumerate(rows):
        if omit == i:
            continue
        summation = row["sum"]
        if alter == i:
            summation ^= 1
        lines.append(
            f"VEC idx={i} a={row['a']} b={row['b']} cin={row['cin']} "
            f"sum={summation:04b} cout={row['cout']:01b}"
        )
    if duplicate:
        row = rows[0]
        lines.append(
            f"VEC idx=0 a={row['a']} b={row['b']} cin={row['cin']} "
            f"sum={row['sum']:04b} cout={row['cout']:01b}"
        )
    lines.append("=== TESTBENCH_DONE ===")
    return "\n".join(lines)

class AuditorTests(unittest.TestCase):
    def setUp(self):
        self.rows = golden_rows()

    def test_all_vectors_pass(self):
        self.assertIn(audit_output(log_for(self.rows), self.rows, 512)[0], (PASS, "PASS_REFERENCE_VERIFIED"))

    def test_output_mismatch_is_functional_fail(self):
        self.assertEqual(audit_output(log_for(self.rows, alter=11), self.rows, 512)[0],
                         FUNCTIONAL_FAIL)

    def test_missing_vector_is_incomplete(self):
        self.assertEqual(audit_output(log_for(self.rows, omit=11), self.rows, 512)[0],
                         INCOMPLETE)

    def test_duplicate_index_is_invalid(self):
        self.assertEqual(audit_output(log_for(self.rows, duplicate=True), self.rows, 512)[0],
                         INVALID_RESULTS)

    def test_unknown_output_is_invalid(self):
        log = log_for(self.rows).replace("sum=0000", "sum=0x00", 1)
        self.assertEqual(audit_output(log, self.rows, 512)[0], INVALID_RESULTS)

if __name__ == "__main__":
    unittest.main()
