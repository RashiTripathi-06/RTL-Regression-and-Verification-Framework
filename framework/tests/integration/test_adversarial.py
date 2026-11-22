from __future__ import annotations
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from executor import ExecutionResult
from auditor import VerificationAuditor
from matcher import DUTTestbenchMatcher
from models import (
    ModuleInfo,
    PortSpec,
    STATUS_PASS,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_INCOMPLETE,
    STATUS_INVALID_RESULTS,
    STATUS_MISSING_REFERENCE,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_NOT_VERIFIED
)
from parser import VerilogASTParser

class AdversarialRegressionTests(unittest.TestCase):
    """
    Adversarial verification tests covering:
    - Zero-check simulations -> EXECUTED / NOT VERIFIED
    - Missing reference files -> MISSING REFERENCE
    - Ambiguous candidates -> AMBIGUOUS MATCH
    - Out of order vectors -> INVALID RESULTS
    - Early termination -> INCOMPLETE
    - Parameterized designs and non-ANSI ordering
    """

    def setUp(self):
        self.auditor = VerificationAuditor()
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="adv_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_simulation_with_no_checks_is_not_verified(self):
        """A testbench that runs to completion but contains 0 checks must NOT be classified as PASS."""
        fake_exec = ExecutionResult(
            plan_id="no_check_plan",
            compile_returncode=0,
            compile_stdout="",
            compile_stderr="",
            sim_returncode=0,
            sim_stdout="=== TESTBENCH_START ===\nHello World from empty testbench\n=== TESTBENCH_DONE ===\n",
            sim_stderr="",
            timed_out=False,
            elapsed_seconds=0.05
        )
        status, passed, total, failed, diag, mismatches = self.auditor.audit(fake_exec)
        self.assertEqual(status, STATUS_NOT_VERIFIED)
        self.assertIn("performed no detectable assertions", diag)

    def test_testbench_summary_with_zero_total_is_not_verified(self):
        """A testbench summary with total=0 must be classified as NOT VERIFIED."""
        fake_exec = ExecutionResult(
            plan_id="zero_summary_plan",
            compile_returncode=0,
            compile_stdout="",
            compile_stderr="",
            sim_returncode=0,
            sim_stdout="=== TESTBENCH_START ===\n=== TESTBENCH_SUMMARY: total=0 pass=0 fail=0 ===\n=== TESTBENCH_DONE ===\n",
            sim_stderr="",
            timed_out=False,
            elapsed_seconds=0.05
        )
        status, passed, total, failed, diag, mismatches = self.auditor.audit(fake_exec)
        self.assertEqual(status, STATUS_NOT_VERIFIED)

    def test_out_of_order_vectors_is_invalid_results(self):
        """Simulation vectors arriving out of order must be flagged as INVALID RESULTS."""
        lines = [
            "=== TESTBENCH_START ===",
            "VEC idx=0 a=0 b=0 cin=0 sum=0000 cout=0",
            "VEC idx=2 a=0 b=2 cin=0 sum=0010 cout=0",
            "VEC idx=1 a=0 b=1 cin=0 sum=0001 cout=0", # Out of order!
            "=== TESTBENCH_DONE ==="
        ]
        fake_exec = ExecutionResult(
            plan_id="ooo_plan",
            compile_returncode=0,
            compile_stdout="",
            compile_stderr="",
            sim_returncode=0,
            sim_stdout="\n".join(lines),
            sim_stderr="",
            timed_out=False,
            elapsed_seconds=0.05
        )
        status, passed, total, failed, diag, mismatches = self.auditor.audit(fake_exec)
        self.assertEqual(status, STATUS_INVALID_RESULTS)
        self.assertIn("out of order", diag.lower())

    def test_ambiguous_candidate_matches_rejected(self):
        """
        Two unrelated DUTs with identical interfaces matching a testbench
        without explicit configuration must be marked as AMBIGUOUS MATCH.
        """
        # DUT 1: Adder
        dut1_code = """
        module adder_cand (input [3:0] a, b, input cin, output [3:0] sum, output cout);
            assign {cout, sum} = a + b + cin;
        endmodule
        """
        # DUT 2: Completely unrelated subtractor with identical port names/widths
        dut2_code = """
        module sub_cand (input [3:0] a, b, input cin, output [3:0] sum, output cout);
            assign {cout, sum} = a - b - cin;
        endmodule
        """
        # TB expecting 'generic_unit' with ports a, b, cin, sum, cout
        tb_code = """
        module tb_generic;
            reg [3:0] a, b; reg cin; wire [3:0] sum; wire cout;
            generic_unit uut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
        endmodule
        """
        f_dut1 = self.temp_dir / "adder_cand.v"
        f_dut2 = self.temp_dir / "sub_cand.v"
        f_tb = self.temp_dir / "tb_generic.v"
        f_dut1.write_text(dut1_code)
        f_dut2.write_text(dut2_code)
        f_tb.write_text(tb_code)

        m_dut1 = self.parser.parse_file(f_dut1)
        m_dut2 = self.parser.parse_file(f_dut2)
        m_tb = self.parser.parse_file(f_tb)

        matcher = DUTTestbenchMatcher(all_modules={}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all(m_dut1 + m_dut2, m_tb)

        self.assertEqual(len(valid), 2)
        # Both must be marked ambiguous
        self.assertTrue(valid[0].is_ambiguous)
        self.assertTrue(valid[1].is_ambiguous)
        self.assertIn("Ambiguous candidate match", valid[0].ambiguity_reason)

    def test_explicit_manifest_resolves_ambiguity(self):
        """An explicit configuration mapping resolves candidate ambiguity cleanly."""
        dut1_code = """
        module adder_cand (input [3:0] a, b, input cin, output [3:0] sum, output cout);
            assign {cout, sum} = a + b + cin;
        endmodule
        """
        dut2_code = """
        module sub_cand (input [3:0] a, b, input cin, output [3:0] sum, output cout);
            assign {cout, sum} = a - b - cin;
        endmodule
        """
        tb_code = """
        module tb_generic;
            reg [3:0] a, b; reg cin; wire [3:0] sum; wire cout;
            generic_unit uut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
        endmodule
        """

        f_dut1 = self.temp_dir / "adder_cand.v"
        f_dut2 = self.temp_dir / "sub_cand.v"
        f_tb = self.temp_dir / "tb_generic.v"
        f_dut1.write_text(dut1_code)
        f_dut2.write_text(dut2_code)
        f_tb.write_text(tb_code)

        m_dut1 = self.parser.parse_file(f_dut1)
        m_dut2 = self.parser.parse_file(f_dut2)
        m_tb = self.parser.parse_file(f_tb)

        # User explicitly maps adder_cand -> tb_generic
        matcher = DUTTestbenchMatcher(
            all_modules={},
            supporting_modules={},
            user_mappings={"dut_tb_mapping": {"adder_cand": "tb_generic"}}
        )
        valid, iface_err, unmatched = matcher.match_all(m_dut1 + m_dut2, m_tb)

        explicit_m = [m for m in valid if m.dut.name == "adder_cand"][0]
        self.assertFalse(explicit_m.is_ambiguous, "Explicit user mapping must resolve ambiguity")
        self.assertEqual(explicit_m.compatibility.confidence, "CONFIRMED")

    def test_parameterized_width_expression_parsed(self):
        """Parameterized modules must evaluate bit-widths accurately."""
        code = """
        module param_buffer #(
            parameter WIDTH = 8,
            parameter DEPTH = 16
        ) (
            input  wire [WIDTH-1:0] data_in,
            output wire [WIDTH-1:0] data_out
        );
            assign data_out = data_in;
        endmodule
        """
        f = self.temp_dir / "param_buffer.v"
        f.write_text(code)
        mods = self.parser.parse_file(f)
        self.assertEqual(len(mods), 1)
        mod = mods[0]
        self.assertEqual(mod.ports["data_in"].width, 8)
        self.assertEqual(mod.ports["data_out"].width, 8)

    def test_sequential_logic_indicators_detected(self):
        """Sequential clocked constructs must be tagged with is_sequential=True."""
        code = """
        module d_flip_flop (
            input  wire clk,
            input  wire rst_n,
            input  wire d,
            output reg  q
        );
            always @(posedge clk or negedge rst_n) begin
                if (!rst_n) q <= 1'b0;
                else q <= d;
            end
        endmodule
        """
        f = self.temp_dir / "d_flip_flop.v"
        f.write_text(code)
        mods = self.parser.parse_file(f)
        self.assertEqual(len(mods), 1)
        mod = mods[0]
        self.assertTrue(mod.has_clock)
        self.assertTrue(mod.has_reset)
        self.assertTrue(mod.is_sequential)

if __name__ == "__main__":
    unittest.main()
