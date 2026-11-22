import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from engine import RegressionEngine
from models import (
    STATUS_PASS,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_INTERFACE_ERROR,
    STATUS_INCOMPLETE,
    STATUS_TIMEOUT,
    STATUS_INVALID_RESULTS,
    STATUS_NO_MATCH,
)

class EndToEndRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine = RegressionEngine(root_dir=ROOT)
        cls.results = engine.run_regression(force_rerun=True, parallel=True)
        cls.res_by_plan = {r.plan_id: r for r in cls.results}

    def test_rca_and_behavioral_pass(self):
        rca_res = self.res_by_plan.get("adder_rca__tb_adder")
        self.assertIsNotNone(rca_res)
        self.assertIn(rca_res.status, (STATUS_PASS, "PASS_REFERENCE_VERIFIED"))
        self.assertEqual(rca_res.passed_vectors, 512)

        beh_res = self.res_by_plan.get("adder_behavioral__tb_adder")
        self.assertIsNotNone(beh_res)
        self.assertIn(beh_res.status, (STATUS_PASS, "PASS_REFERENCE_VERIFIED"))
        self.assertEqual(beh_res.passed_vectors, 512)

    def test_cla_with_wrapper_passes(self):
        cla_res = self.res_by_plan.get("adder_cla__tb_adder")
        self.assertIsNotNone(cla_res)
        self.assertIn(cla_res.status, (STATUS_PASS, "PASS_REFERENCE_VERIFIED"))
        self.assertTrue(cla_res.wrapper_used)
        self.assertEqual(cla_res.passed_vectors, 512)

    def test_alu_passes_second_dut_type(self):
        alu_res = self.res_by_plan.get("alu_4bit__tb_alu")
        self.assertIsNotNone(alu_res)
        self.assertIn(alu_res.status, (STATUS_PASS, "PASS_TESTBENCH_ONLY"))
        self.assertEqual(alu_res.passed_vectors, 10)

    def test_buggy_adder_functional_fail_with_exact_vectors(self):
        buggy_res = self.res_by_plan.get("adder_buggy__tb_adder")
        self.assertIsNotNone(buggy_res)
        self.assertEqual(buggy_res.status, STATUS_FUNCTIONAL_FAIL)
        self.assertGreater(buggy_res.failed_vectors, 0)
        self.assertTrue(len(buggy_res.failing_vectors) > 0)
        first_mm = buggy_res.failing_vectors[0]
        self.assertIn("inputs", first_mm)
        self.assertIn("actual_outputs", first_mm)
        self.assertIn("expected_outputs", first_mm)

    def test_syntax_error_is_compile_error(self):
        syntax_res = self.res_by_plan.get("adder_syntax_error__tb_adder")
        self.assertIsNotNone(syntax_res)
        self.assertEqual(syntax_res.status, STATUS_COMPILE_ERROR)

    def test_bad_ports_is_interface_error(self):
        bad_res = self.res_by_plan.get("adder_bad_ports__tb_adder")
        self.assertIsNotNone(bad_res)
        self.assertEqual(bad_res.status, STATUS_INTERFACE_ERROR)
        self.assertIn("bit-width mismatch", bad_res.diagnostic_summary)

    def test_incomplete_simulation_detected(self):
        inc_res = self.res_by_plan.get("adder_incomplete__tb_adder")
        self.assertIsNotNone(inc_res)
        self.assertEqual(inc_res.status, STATUS_INCOMPLETE)

    def test_infinite_loop_timeout_detected(self):
        to_res = self.res_by_plan.get("adder_infinite_loop__tb_adder")
        self.assertIsNotNone(to_res)
        self.assertEqual(to_res.status, STATUS_TIMEOUT)

    def test_uninitialized_x_is_invalid_results(self):
        x_res = self.res_by_plan.get("adder_x_output__tb_adder")
        self.assertIsNotNone(x_res)
        self.assertEqual(x_res.status, STATUS_INVALID_RESULTS)

    def test_unmatched_multiplier_is_no_match(self):
        no_tb = self.res_by_plan.get("multiplier_4bit__NO_TB")
        self.assertIsNotNone(no_tb)
        self.assertEqual(no_tb.status, STATUS_NO_MATCH)

if __name__ == "__main__":
    unittest.main()
