import unittest
import tempfile
import shutil
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT))

from models import (
    VerificationPlan,
    CompatibilityEvidence,
    TestResult,
    STATUS_PASS,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_PASS_TESTBENCH_ONLY,
)
from mutator import RTLMutator, MutationQualifier, Mutant


class MutatorTests(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.adder_file = self.tmp_dir / "adder.v"
        self.adder_file.write_text(
            "module adder(input [7:0] a, input [7:0] b, output [7:0] sum);\n"
            "  assign sum = a + b;\n"
            "endmodule\n",
            encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_mutant_generation(self):
        mutants = RTLMutator.generate_mutants(self.adder_file)
        self.assertGreater(len(mutants), 0)
        m0 = mutants[0]
        self.assertEqual(m0.mutation_type, "AOR")
        self.assertIn("-", m0.mutated_line)

    def test_mutation_qualification_mock(self):
        plan = VerificationPlan(
            plan_id="adder__tb",
            dut_name="adder",
            dut_module="adder",
            dut_file=self.adder_file,
            tb_name="tb_adder",
            tb_module="tb_adder",
            tb_file=self.tmp_dir / "tb_adder.v",
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct",
                match_type="EXACT_NAME",
                expected_module_name="adder",
                actual_module_name="adder"
            ),
            required_sources=[self.adder_file],
            data_files=[]
        )

        mutants = [
            Mutant("MUT_AOR_001", "AOR", 2, "assign sum = a + b;", "assign sum = a - b;", "module adder... endmodule"),
            Mutant("MUT_AOR_002", "AOR", 2, "assign sum = a + b;", "assign sum = a * b;", "module adder... endmodule")
        ]

        # Case 1: Strict checker that kills all mutants
        def strict_runner(dut_file, sources, bdir):
            return TestResult(plan_id="p", dut_name="adder", tb_name="tb", status=STATUS_FUNCTIONAL_FAIL)

        rep1 = MutationQualifier.qualify_testbench(plan, list(mutants), strict_runner, self.tmp_dir / "b1")
        self.assertEqual(rep1.killed_mutants, 2)
        self.assertEqual(rep1.survived_mutants, 0)
        self.assertEqual(rep1.mutation_score, 100.0)

        # Case 2: Weak X-only checker where mutants survive
        def weak_runner(dut_file, sources, bdir):
            return TestResult(plan_id="p", dut_name="adder", tb_name="tb", status=STATUS_PASS_TESTBENCH_ONLY)

        rep2 = MutationQualifier.qualify_testbench(plan, list(mutants), weak_runner, self.tmp_dir / "b2")
        self.assertEqual(rep2.killed_mutants, 0)
        self.assertEqual(rep2.survived_mutants, 2)
        self.assertEqual(rep2.mutation_score, 0.0)


if __name__ == "__main__":
    unittest.main()
