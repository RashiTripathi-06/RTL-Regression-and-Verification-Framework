import tempfile
import shutil
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rtl_framework.models import (
    ModuleInfo,
    PortSpec,
    InstanceInfo,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_PASS_TESTBENCH_ONLY,
)
from rtl_framework.scanner import ProjectScanner
from rtl_framework.matcher import DUTTestbenchMatcher
from rtl_framework.engine import RegressionEngine


class AuditCorrectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_audit_test_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hierarchy_classifies_internal_modules(self):
        """Internal submodules instantiated by a top-level DUT must be classified INTERNAL_MODULE."""
        (self.temp_dir / "rtl").mkdir()
        (self.temp_dir / "tb").mkdir()

        (self.temp_dir / "rtl" / "sub_helper.v").write_text(
            "module sub_helper(input [3:0] x, output [3:0] y); assign y = x; endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "rtl" / "top_dut.v").write_text(
            "module top_dut(input [3:0] a, output [3:0] b); sub_helper u0(.x(a), .y(b)); endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "tb" / "tb_top_dut.v").write_text(
            "module tb_top_dut; reg [3:0] a; wire [3:0] b; top_dut uut(.a(a), .b(b)); endmodule\n",
            encoding="utf-8",
        )

        scanner = ProjectScanner(self.temp_dir)
        proj = scanner.scan()
        self.assertEqual([m.name for m in proj.candidate_duts], ["top_dut"])
        self.assertEqual([m.name for m in proj.internal_modules], ["sub_helper"])
        self.assertEqual(proj.module_classifications["sub_helper:sub_helper"], "INTERNAL_MODULE")

    def test_named_port_instantiation_prevents_cross_matching(self):
        """
        Modules with identical port widths/directions (multiplier, prop_posit_var_mult, mask)
        must not cross-match testbenches that use explicit instantiation + named ports.
        """
        mod_mult = ModuleInfo(
            name="multiplier",
            file_path=Path("rtl/multiplier.v"),
            ports={"opd_a": PortSpec("opd_a", "input", 16), "opd_b": PortSpec("opd_b", "input", 16), "product": PortSpec("product", "output", 16)},
            port_order=["opd_a", "opd_b", "product"],
        )
        mod_prop = ModuleInfo(
            name="prop_posit_var_mult",
            file_path=Path("rtl/prop_posit_var_mult.v"),
            ports={"a": PortSpec("a", "input", 16), "b": PortSpec("b", "input", 16), "result": PortSpec("result", "output", 16)},
            port_order=["a", "b", "result"],
        )
        mod_mask = ModuleInfo(
            name="mask",
            file_path=Path("rtl/mask.v"),
            ports={"N": PortSpec("N", "input", 16), "m": PortSpec("m", "input", 16), "masked": PortSpec("masked", "output", 16)},
            port_order=["N", "m", "masked"],
        )
        tb_mult = ModuleInfo(
            name="tb_multiplier",
            file_path=Path("tb/tb_multiplier.v"),
            instantiations=[InstanceInfo("dut", "multiplier", port_connections={"opd_a": "a", "opd_b": "b", "product": "product"})],
            internal_signals={"a": PortSpec("a", "input", 16), "b": PortSpec("b", "input", 16), "product": PortSpec("product", "output", 16)},
            tb_driven_signals={"a", "b"},
            tb_observed_signals={"product"},
            is_testbench=True,
        )
        tb_prop = ModuleInfo(
            name="tb_prop_posit_var_mult",
            file_path=Path("tb/tb_prop_posit_var_mult.v"),
            instantiations=[InstanceInfo("dut", "prop_posit_var_mult", port_connections={"a": "a", "b": "b", "result": "result"})],
            internal_signals={"a": PortSpec("a", "input", 16), "b": PortSpec("b", "input", 16), "result": PortSpec("result", "output", 16)},
            tb_driven_signals={"a", "b"},
            tb_observed_signals={"result"},
            is_testbench=True,
        )

        all_mods = {m.name: m for m in (mod_mult, mod_prop, mod_mask, tb_mult, tb_prop)}
        matcher = DUTTestbenchMatcher(all_mods, {m.name: m for m in (mod_mult, mod_prop, mod_mask)})
        valid, iface_errs, unmatched = matcher.match_all([mod_mult, mod_prop, mod_mask], [tb_mult, tb_prop])

        pairs = {(m.dut.name, m.testbench.name, m.is_ambiguous) for m in valid}
        self.assertEqual(pairs, {("multiplier", "tb_multiplier", False), ("prop_posit_var_mult", "tb_prop_posit_var_mult", False)})
        self.assertEqual([u.name for u in unmatched], ["mask"])

    def test_faulty_rtl_detected_as_functional_fail(self):
        """A deliberately faulty RTL design must be flagged as FUNCTIONAL FAIL."""
        (self.temp_dir / "rtl").mkdir()
        (self.temp_dir / "tb").mkdir()
        (self.temp_dir / "rtl" / "faulty_adder.v").write_text(
            "module faulty_adder(input [3:0] a, input [3:0] b, output [3:0] sum); assign sum = a ^ b; endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "tb" / "tb_faulty_adder.v").write_text(
            """module tb_faulty_adder;
                reg [3:0] a, b; wire [3:0] sum;
                integer pass_c = 0, fail_c = 0;
                faulty_adder uut(.a(a), .b(b), .sum(sum));
                initial begin
                    $display("=== TESTBENCH_START ===");
                    a = 4'd3; b = 4'd5; #1;
                    if (sum === 4'd8) pass_c = pass_c + 1;
                    else begin $display("FAIL: 3+5=%0d", sum); fail_c = fail_c + 1; end
                    $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_c + fail_c, pass_c, fail_c);
                    $display("=== TESTBENCH_DONE ===");
                    $finish;
                end
            endmodule\n""",
            encoding="utf-8",
        )
        engine = RegressionEngine(root_dir=self.temp_dir)
        results = engine.run_regression(force_rerun=True, parallel=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, STATUS_FUNCTIONAL_FAIL)
        self.assertEqual(results[0].failed_vectors, 1)

    def test_missing_dependency_classified_as_compile_error(self):
        """An RTL design referencing an undeclared submodule must be classified as COMPILE ERROR."""
        (self.temp_dir / "rtl").mkdir()
        (self.temp_dir / "tb").mkdir()
        (self.temp_dir / "rtl" / "broken_top.v").write_text(
            "module broken_top(input [3:0] a, output [3:0] b); missing_submod u0(.x(a), .y(b)); endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "tb" / "tb_broken_top.v").write_text(
            """module tb_broken_top;
                reg [3:0] a; wire [3:0] b;
                broken_top uut(.a(a), .b(b));
                initial begin a = 0; #1; $finish; end
            endmodule\n""",
            encoding="utf-8",
        )
        engine = RegressionEngine(root_dir=self.temp_dir)
        results = engine.run_regression(force_rerun=True, parallel=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, STATUS_COMPILE_ERROR)

    def test_ambiguous_positional_matching_refused(self):
        """Ambiguous candidates with identical positional widths must be reported AMBIGUOUS MATCH and not executed."""
        (self.temp_dir / "rtl").mkdir()
        (self.temp_dir / "tb").mkdir()
        (self.temp_dir / "rtl" / "cand_a.v").write_text(
            "module cand_a(input [7:0] x, input [7:0] y, output [7:0] z); assign z = x + y; endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "rtl" / "cand_b.v").write_text(
            "module cand_b(input [7:0] p, input [7:0] q, output [7:0] r); assign r = p - q; endmodule\n",
            encoding="utf-8",
        )
        (self.temp_dir / "tb" / "tb_unknown_unit.v").write_text(
            """module tb_unknown_unit;
                reg [7:0] in1, in2; wire [7:0] out1;
                unknown_unit uut(in1, in2, out1);
                initial begin in1 = 1; in2 = 2; #1; $finish; end
            endmodule\n""",
            encoding="utf-8",
        )
        engine = RegressionEngine(root_dir=self.temp_dir)
        results = engine.run_regression(force_rerun=True, parallel=False)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r.status, STATUS_AMBIGUOUS_MATCH)
            self.assertEqual(r.execution_status, "EXEC_SKIPPED")


if __name__ == "__main__":
    unittest.main()
