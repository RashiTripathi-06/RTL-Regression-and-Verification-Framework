import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from models import PortSpec, ModuleInfo, InstanceInfo
from matcher import DUTTestbenchMatcher

class MatcherTests(unittest.TestCase):
    def setUp(self):
        # Create a mock testbench module that instantiates 'adder'
        self.tb = ModuleInfo(
            name="tb_adder",
            file_path=Path("tb/tb_adder.v"),
            ports={},
            instantiations=[
                InstanceInfo(
                    instance_name="uut",
                    module_type="adder",
                    port_connections={"a": "a", "b": "b", "cin": "cin", "sum": "sum", "cout": "cout"}
                )
            ],
            internal_signals={
                "a": PortSpec("a", "input", 4),
                "b": PortSpec("b", "input", 4),
                "cin": PortSpec("cin", "input", 1),
                "sum": PortSpec("sum", "output", 4),
                "cout": PortSpec("cout", "output", 1),
            },
            is_testbench=True
        )

        # Base adder module definition
        self.adder_base = ModuleInfo(
            name="adder",
            file_path=Path("designs/adder_base.v"),
            ports={
                "a": PortSpec("a", "input", 4),
                "b": PortSpec("b", "input", 4),
                "cin": PortSpec("cin", "input", 1),
                "sum": PortSpec("sum", "output", 4),
                "cout": PortSpec("cout", "output", 1),
            }
        )

        self.all_mods = {"tb_adder": self.tb, "adder": self.adder_base}

    def test_exact_name_match(self):
        dut = ModuleInfo(
            name="adder",
            file_path=Path("designs/adder_rca.v"),
            ports={
                "a": PortSpec("a", "input", 4),
                "b": PortSpec("b", "input", 4),
                "cin": PortSpec("cin", "input", 1),
                "sum": PortSpec("sum", "output", 4),
                "cout": PortSpec("cout", "output", 1),
            }
        )
        matcher = DUTTestbenchMatcher(self.all_mods, {})
        valid, iface_errs, unmatched = matcher.match_all([dut], [self.tb])
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(unmatched), 0)
        m = valid[0]
        self.assertEqual(m.compatibility.match_type, "EXACT_NAME")
        self.assertFalse(m.compatibility.wrapper_needed)

    def test_wrapper_compatible_match(self):
        dut = ModuleInfo(
            name="adder_cla",
            file_path=Path("designs/adder_cla.v"),
            ports={
                "a": PortSpec("a", "input", 4),
                "b": PortSpec("b", "input", 4),
                "cin": PortSpec("cin", "input", 1),
                "sum": PortSpec("sum", "output", 4),
                "cout": PortSpec("cout", "output", 1),
            }
        )
        matcher = DUTTestbenchMatcher(self.all_mods, {})
        valid, iface_errs, unmatched = matcher.match_all([dut], [self.tb])
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(unmatched), 0)
        m = valid[0]
        self.assertEqual(m.compatibility.match_type, "WRAPPER_COMPATIBLE")
        self.assertTrue(m.compatibility.wrapper_needed)
        self.assertEqual(m.target_instantiation, "adder")

    def test_incompatible_port_width(self):
        dut = ModuleInfo(
            name="adder_8bit",
            file_path=Path("designs/adder_8bit.v"),
            ports={
                "a": PortSpec("a", "input", 8),
                "b": PortSpec("b", "input", 8),
                "cin": PortSpec("cin", "input", 1),
                "sum": PortSpec("sum", "output", 8),
                "cout": PortSpec("cout", "output", 1),
            }
        )
        matcher = DUTTestbenchMatcher(self.all_mods, {})
        valid, iface_errs, unmatched = matcher.match_all([dut], [self.tb])
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(unmatched[0].name, "adder_8bit")

if __name__ == "__main__":
    unittest.main()
