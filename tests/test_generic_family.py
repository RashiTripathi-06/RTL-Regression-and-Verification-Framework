from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from engine import RegressionEngine
from models import (
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL
)

class GenericFamilyTests(unittest.TestCase):
    """
    Validates generic multi-family regression testing:
    - Counter family (clocked sequential logic with dedicated reference memory)
    - Faulty counter functional failure detection
    - Execution of multiple compatible testbenches for a single DUT
    """

    @classmethod
    def setUpClass(cls):
        engine = RegressionEngine(root_dir=Path("."))
        cls.results = engine.run_regression(force_rerun=True, parallel=False)

    def _find_results(self, dut_name: str, tb_name: str):
        return [r for r in self.results if r.dut_name == dut_name and r.tb_name == tb_name]

    def test_counter_updown_passes(self):
        """4-bit synchronous up/down counter must pass its dedicated testbench."""
        res = self._find_results("counter_updown_4bit", "tb_counter")
        self.assertEqual(len(res), 1, "Plan for counter_updown_4bit__tb_counter must exist")
        self.assertIn(res[0].status, (STATUS_PASS, STATUS_PASS_REFERENCE_VERIFIED))
        self.assertEqual(res[0].passed_vectors, 26)
        self.assertEqual(res[0].failed_vectors, 0)

    def test_counter_faulty_detected_as_functional_fail(self):
        """Intentionally faulty counter must be flagged as FUNCTIONAL FAIL with failing vectors."""
        res = self._find_results("counter_faulty", "tb_counter")
        self.assertEqual(len(res), 1, "Plan for counter_faulty__tb_counter must exist")
        self.assertEqual(res[0].status, STATUS_FUNCTIONAL_FAIL)
        self.assertGreater(res[0].failed_vectors, 0)
        self.assertIn("failed assertions", res[0].diagnostic_summary)

    def test_multiple_compatible_testbenches_executed(self):
        """Adder DUTs compatible with both tb_adder and tb_adder_random must execute both."""
        res_tb_adder = self._find_results("adder_behavioral", "tb_adder")
        res_tb_random = self._find_results("adder_behavioral", "tb_adder_random")
        self.assertEqual(len(res_tb_adder), 1, "adder_behavioral must run under tb_adder")
        self.assertEqual(len(res_tb_random), 1, "adder_behavioral must run under tb_adder_random")
        self.assertIn(res_tb_adder[0].status, (STATUS_PASS, STATUS_PASS_REFERENCE_VERIFIED))
        self.assertIn(res_tb_random[0].status, (STATUS_PASS, STATUS_PASS_TESTBENCH_ONLY))

    def test_alu_family_verified(self):
        """ALU family is also verified independently."""
        res = self._find_results("alu_4bit", "tb_alu")
        self.assertEqual(len(res), 1)
        self.assertIn(res[0].status, (STATUS_PASS, STATUS_PASS_TESTBENCH_ONLY))

if __name__ == "__main__":
    unittest.main()
