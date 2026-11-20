import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parser import VerilogASTParser

class ParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = VerilogASTParser()

    def test_parse_ansi_module(self):
        code = """
        module adder_test #(parameter WIDTH = 4) (
            input wire [WIDTH-1:0] a,
            input wire [WIDTH-1:0] b,
            input wire cin,
            output wire [WIDTH-1:0] sum,
            output wire cout
        );
            assign {cout, sum} = a + b + cin;
        endmodule
        """
        temp_file = ROOT / "build" / "temp_ansi.v"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(code, encoding="utf-8")

        modules = self.parser.parse_file(temp_file)
        self.assertEqual(len(modules), 1)
        mod = modules[0]
        self.assertEqual(mod.name, "adder_test")
        self.assertIn("a", mod.ports)
        self.assertIn("cout", mod.ports)
        self.assertEqual(mod.ports["a"].direction, "input")
        self.assertEqual(mod.ports["a"].width, 4)
        self.assertEqual(mod.ports["cin"].width, 1)
        self.assertEqual(mod.ports["cout"].direction, "output")
        self.assertEqual(mod.ports["cout"].width, 1)
        self.assertFalse(mod.is_testbench)

    def test_parse_non_ansi_module(self):
        code = """
        module legacy_adder (a, b, cin, sum, cout);
            input [3:0] a, b;
            input cin;
            output [3:0] sum;
            output cout;
            assign {cout, sum} = a + b + cin;
        endmodule
        """
        temp_file = ROOT / "build" / "temp_non_ansi.v"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(code, encoding="utf-8")

        modules = self.parser.parse_file(temp_file)
        self.assertEqual(len(modules), 1)
        mod = modules[0]
        self.assertEqual(mod.name, "legacy_adder")
        self.assertEqual(mod.ports["a"].width, 4)
        self.assertEqual(mod.ports["sum"].width, 4)
        self.assertEqual(mod.ports["cin"].width, 1)

    def test_parse_testbench_and_instantiation(self):
        code = """
        module tb_adder;
            reg [3:0] a, b;
            reg cin;
            wire [3:0] sum;
            wire cout;
            adder uut (.a(a), .b(b), .cin(cin), .sum(sum), .cout(cout));
            initial begin
                $display("START");
                $finish;
            end
        endmodule
        """
        temp_file = ROOT / "build" / "temp_tb.v"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(code, encoding="utf-8")

        modules = self.parser.parse_file(temp_file)
        self.assertEqual(len(modules), 1)
        tb = modules[0]
        self.assertTrue(tb.is_testbench)
        self.assertEqual(len(tb.instantiations), 1)
        self.assertEqual(tb.instantiations[0].module_type, "adder")
        self.assertIn("a", tb.instantiations[0].port_connections)
        self.assertEqual(tb.instantiations[0].port_connections["a"], "a")

if __name__ == "__main__":
    unittest.main()
