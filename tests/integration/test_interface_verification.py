from __future__ import annotations
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from parser import VerilogASTParser
from matcher import DUTTestbenchMatcher
from models import ModuleInfo, PortSpec, InstanceInfo

class InterfaceVerificationTests(unittest.TestCase):
    """
    Tests rigorous interface compatibility checks:
    - Direction verification
    - Width verification
    - Positional connection mapping
    - Ambiguous mapping detection
    """

    def setUp(self):
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_test_iface_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_incorrect_port_direction_detected(self):
        """A DUT that drives a port that the testbench also drives as an input must fail compatibility."""
        dut_code = """
        module bad_direction_unit (
            output wire [3:0] a,
            output wire [3:0] b,
            output wire       cin,
            output wire [3:0] sum,
            output wire       cout
        );
            assign sum = 4'b0;
            assign cout = 1'b0;
            assign a = 4'b0;
            assign b = 4'b0;
            assign cin = 1'b0;
        endmodule
        """
        dut_file = self.temp_dir / "bad_direction_unit.v"
        dut_file.write_text(dut_code)

        tb_mods = self.parser.parse_file(Path("tb/tb_adder.v"))
        dut_mods = self.parser.parse_file(dut_file)

        matcher = DUTTestbenchMatcher(all_modules={}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all(dut_mods, tb_mods)

        # tb_adder expects 'adder', so this different name must not match as wrapper-compatible due to direction conflicts
        self.assertEqual(len(valid), 0, "Conflicting port directions must prevent wrapper compatibility")
        self.assertEqual(len(unmatched), 1)

    def test_incorrect_port_width_detected(self):
        """A DUT with incorrect port widths must be flagged with an interface mismatch."""
        dut_code = """
        module adder (
            input  wire [7:0] a,   // 8-bit instead of 4-bit!
            input  wire [3:0] b,
            input  wire       cin,
            output wire [3:0] sum,
            output wire       cout
        );
            assign {cout, sum} = a[3:0] + b + cin;
        endmodule
        """
        dut_file = self.temp_dir / "adder_wide_a.v"
        dut_file.write_text(dut_code)

        tb_mods = self.parser.parse_file(Path("tb/tb_adder.v"))
        dut_mods = self.parser.parse_file(dut_file)

        matcher = DUTTestbenchMatcher(all_modules={}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all(dut_mods, tb_mods)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(iface_err), 1, "Must be classified as interface error")
        self.assertIn("bit-width mismatch", iface_err[0].compatibility.reason)
        self.assertIn("'a'", iface_err[0].compatibility.reason)

    def test_positional_port_connections_handled(self):
        """Testbenches that instantiate DUT positionally must have ports resolved in order."""
        tb_code = """
        module tb_positional;
            reg  [3:0] in_a;
            reg  [3:0] in_b;
            reg        c_in;
            wire [3:0] s_out;
            wire       c_out;

            // Positional instantiation: no .port() syntax
            adder dut_inst (in_a, in_b, c_in, s_out, c_out);

            initial begin
                $display("=== TESTBENCH_START ===");
                {in_a, in_b, c_in} = 9'b0;
                #5;
                $display("VEC idx=0 in_a=%0d in_b=%0d c_in=%0d s_out=%0d c_out=%0d", in_a, in_b, c_in, s_out, c_out);
                $display("=== TESTBENCH_DONE ===");
                $finish;
            end
        endmodule
        """
        tb_file = self.temp_dir / "tb_positional.v"
        tb_file.write_text(tb_code)

        tb_mods = self.parser.parse_file(tb_file)
        self.assertEqual(len(tb_mods), 1)
        tb = tb_mods[0]
        self.assertEqual(len(tb.instantiations), 1)
        inst = tb.instantiations[0]
        self.assertEqual(inst.positional_connections, ["in_a", "in_b", "c_in", "s_out", "c_out"])

        dut_mods = self.parser.parse_file(Path("designs/adder_behavioral.v"))
        matcher = DUTTestbenchMatcher(all_modules={}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all(dut_mods, [tb])

        self.assertEqual(len(valid), 1, "Positional testbench must match compatible DUT")
        self.assertEqual(valid[0].compatibility.confidence, "HEURISTIC")
        self.assertEqual(len(valid[0].compatibility.port_mapping), 5)

    def test_ambiguous_port_mapping_detected(self):
        """Detect ambiguous port mapping when ports cannot be resolved deterministically."""
        dut_code = """
        module ambiguous_unit (
            input  wire [3:0] port_x,
            input  wire [3:0] port_y,
            output wire [3:0] res_1,
            output wire [3:0] res_2
        );
            assign res_1 = port_x;
            assign res_2 = port_y;
        endmodule
        """
        tb_code = """
        module tb_ambiguous;
            reg  [3:0] alpha, beta;
            wire [3:0] gamma, delta;

            target_box uut (.data_a(alpha), .data_b(beta), .out_a(gamma), .out_b(delta));

            initial begin
                $display("=== TESTBENCH_START ===");
                alpha = 0; beta = 0;
                #1;
                $display("=== TESTBENCH_DONE ===");
                $finish;
            end
        endmodule
        """
        dut_file = self.temp_dir / "ambiguous_unit.v"
        dut_file.write_text(dut_code)
        tb_file = self.temp_dir / "tb_ambiguous.v"
        tb_file.write_text(tb_code)

        dut_mods = self.parser.parse_file(dut_file)
        tb_mods = self.parser.parse_file(tb_file)

        matcher = DUTTestbenchMatcher(all_modules={}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all(dut_mods, tb_mods)

        # Ambiguous candidate names with identical widths and directions should flag ambiguity
        if valid:
            self.assertTrue(valid[0].is_ambiguous or valid[0].compatibility.is_ambiguous)
        else:
            self.assertEqual(len(unmatched), 1)

if __name__ == "__main__":
    unittest.main()
