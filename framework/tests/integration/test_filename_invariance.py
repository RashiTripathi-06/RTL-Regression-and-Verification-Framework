from __future__ import annotations
import sys
import shutil
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
sys.path.insert(0, str(ROOT / "src"))
from parser import VerilogASTParser
from matcher import DUTTestbenchMatcher
from models import STATUS_INTERFACE_ERROR

def _find_fixture(rel_path: str) -> Path:
    cand = FIXTURES_DIR / rel_path
    if cand.exists():
        return cand
    cand2 = ROOT / rel_path
    if cand2.exists():
        return cand2
    return Path(rel_path)

class FilenameInvarianceTests(unittest.TestCase):
    """
    Validates that DUT and Testbench matching is purely structural
    and completely independent of filenames.
    """

    def setUp(self):
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_test_rename_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_renaming_bad_ports_file_preserves_interface_error(self):
        """Renaming adder_bad_ports.v to arbitrary_name.v must still yield INTERFACE ERROR."""
        orig_file = _find_fixture("designs/adder_bad_ports.v")
        renamed_file = self.temp_dir / "completely_random_module_name_xyz.v"
        shutil.copy2(orig_file, renamed_file)

        tb_mods = self.parser.parse_file(_find_fixture("testbenches/tb_adder.v"))
        tb = tb_mods[0]

        dut_mods = self.parser.parse_file(renamed_file)
        dut = dut_mods[0]

        matcher = DUTTestbenchMatcher(all_modules={dut.name: dut}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all([dut], [tb])

        # Must be classified as an interface error because module name is 'adder'
        # but port widths do not match testbench requirement
        self.assertEqual(len(valid), 0, "Renamed file should not match validly")
        self.assertEqual(len(iface_err), 1, "Renamed bad ports file must be in interface_error_matches")
        self.assertEqual(iface_err[0].dut.file_path, renamed_file)
        self.assertIn("bit-width mismatch", iface_err[0].compatibility.reason)

    def test_renaming_cla_file_preserves_wrapper_compatible(self):
        """Renaming adder_cla.v to custom_cla.v preserves WRAPPER_COMPATIBLE match."""
        orig_file = _find_fixture("designs/adder_cla.v")
        renamed_file = self.temp_dir / "custom_lookahead_adder_impl.v"
        shutil.copy2(orig_file, renamed_file)

        tb_mods = self.parser.parse_file(_find_fixture("testbenches/tb_adder.v"))
        tb = tb_mods[0]

        dut_mods = self.parser.parse_file(renamed_file)
        dut = dut_mods[0]

        matcher = DUTTestbenchMatcher(all_modules={dut.name: dut}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all([dut], [tb])

        self.assertEqual(len(valid), 1, "Renamed CLA file must still match")
        self.assertTrue(valid[0].compatibility.wrapper_needed)
        self.assertEqual(valid[0].compatibility.match_type, "WRAPPER_COMPATIBLE")

    def test_renaming_behavioral_preserves_exact_name(self):
        """Renaming adder_behavioral.v to test_123.v preserves EXACT_NAME match."""
        orig_file = _find_fixture("designs/adder_behavioral.v")
        renamed_file = self.temp_dir / "test_123.v"
        shutil.copy2(orig_file, renamed_file)

        tb_mods = self.parser.parse_file(_find_fixture("testbenches/tb_adder.v"))
        tb = tb_mods[0]

        dut_mods = self.parser.parse_file(renamed_file)
        dut = dut_mods[0]

        matcher = DUTTestbenchMatcher(all_modules={dut.name: dut}, supporting_modules={})
        valid, iface_err, unmatched = matcher.match_all([dut], [tb])

        self.assertEqual(len(valid), 1)
        self.assertFalse(valid[0].compatibility.wrapper_needed)
        self.assertEqual(valid[0].compatibility.match_type, "EXACT_NAME")

if __name__ == "__main__":
    unittest.main()
