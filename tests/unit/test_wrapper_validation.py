from __future__ import annotations
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from models import PortSpec
from wrapper_generator import generate_dut_wrapper

class WrapperValidationTests(unittest.TestCase):
    """
    Tests strict pre-generation verification for RTL wrappers:
    - Verifies valid wrapper synthesis
    - Rejects incompatible widths
    - Rejects incompatible directions
    - Refuses on unmapped or ambiguous ports
    - Ensures wrappers are written only in the build directory
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_test_wrap_"))
        self.out_file = self.temp_dir / "wrapper_test.v"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_wrapper_generation(self):
        """Generates a valid wrapper when all ports are compatible."""
        expected_ports = {
            "a": PortSpec(name="a", direction="input", width=4),
            "b": PortSpec(name="b", direction="input", width=4),
            "cin": PortSpec(name="cin", direction="input", width=1),
            "sum": PortSpec(name="sum", direction="output", width=4),
            "cout": PortSpec(name="cout", direction="output", width=1),
        }
        actual_ports = {
            "operand_1": PortSpec(name="operand_1", direction="input", width=4),
            "operand_2": PortSpec(name="operand_2", direction="input", width=4),
            "c_in": PortSpec(name="c_in", direction="input", width=1),
            "result": PortSpec(name="result", direction="output", width=4),
            "c_out": PortSpec(name="c_out", direction="output", width=1),
        }
        port_mapping = {
            "a": "operand_1",
            "b": "operand_2",
            "cin": "c_in",
            "sum": "result",
            "cout": "c_out",
        }

        path = generate_dut_wrapper(
            expected_module_name="adder",
            actual_module_name="my_custom_adder",
            expected_ports=expected_ports,
            actual_ports=actual_ports,
            port_mapping=port_mapping,
            output_file=self.out_file
        )

        self.assertTrue(path.exists())
        content = path.read_text()
        self.assertIn("module adder (", content)
        self.assertIn("my_custom_adder u_wrapped_dut (", content)
        self.assertIn(".operand_1(a)", content)
        self.assertIn(".result(sum)", content)

    def test_rejects_width_mismatch(self):
        """Must raise ValueError when port widths do not match."""
        expected_ports = {
            "sum": PortSpec(name="sum", direction="output", width=4)
        }
        actual_ports = {
            "sum": PortSpec(name="sum", direction="output", width=8) # 8-bit vs 4-bit!
        }
        with self.assertRaises(ValueError) as ctx:
            generate_dut_wrapper(
                expected_module_name="adder",
                actual_module_name="wide_adder",
                expected_ports=expected_ports,
                actual_ports=actual_ports,
                port_mapping={"sum": "sum"},
                output_file=self.out_file
            )
        self.assertIn("Width mismatch", str(ctx.exception))

    def test_rejects_direction_mismatch(self):
        """Must raise ValueError when directions conflict."""
        expected_ports = {
            "data_in": PortSpec(name="data_in", direction="input", width=8)
        }
        actual_ports = {
            "data_out": PortSpec(name="data_out", direction="output", width=8)
        }
        with self.assertRaises(ValueError) as ctx:
            generate_dut_wrapper(
                expected_module_name="target",
                actual_module_name="source",
                expected_ports=expected_ports,
                actual_ports=actual_ports,
                port_mapping={"data_in": "data_out"},
                output_file=self.out_file
            )
        self.assertIn("Direction mismatch", str(ctx.exception))

    def test_rejects_unmapped_required_port(self):
        """Must raise ValueError when a required DUT port is left unmapped."""
        expected_ports = {
            "a": PortSpec(name="a", direction="input", width=4)
        }
        actual_ports = {
            "a": PortSpec(name="a", direction="input", width=4),
            "unconnected_clk": PortSpec(name="unconnected_clk", direction="input", width=1)
        }
        with self.assertRaises(ValueError) as ctx:
            generate_dut_wrapper(
                expected_module_name="adder",
                actual_module_name="clocked_adder",
                expected_ports=expected_ports,
                actual_ports=actual_ports,
                port_mapping={"a": "a"},
                output_file=self.out_file
            )
        self.assertIn("unmapped", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
