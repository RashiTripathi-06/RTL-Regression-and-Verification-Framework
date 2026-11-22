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
from planner import VerificationPlanner, RegressionPlanner
from auditor import parse_reference_file
from dependency_resolver import DependencyResolver

def _find_fixture(rel_path: str) -> Path:
    cand = FIXTURES_DIR / rel_path
    if cand.exists():
        return cand
    cand2 = ROOT / rel_path
    if cand2.exists():
        return cand2
    return Path(rel_path)

class LUTAssociationTests(unittest.TestCase):
    """
    Validates that:
    1. Unrelated LUT files are not associated with a testbench.
    2. Missing reference files are reported.
    3. Multiple LUT formats (.mem, .hex, .dat, .csv) are parsed cleanly.
    """

    def setUp(self):
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_test_lut_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_unrelated_lut_files_not_associated(self):
        """tb_counter references 'counter_ref.mem'. It must NOT be given 'adder_lut.mem'."""
        tb_mods = self.parser.parse_file(_find_fixture("testbenches/tb_counter.v"))
        dut_mods = self.parser.parse_file(_find_fixture("designs/counter_updown_4bit.v"))

        all_mods = {m.name: m for m in [*tb_mods, *dut_mods]}
        dep_resolver = DependencyResolver(all_mods)
        matcher = DUTTestbenchMatcher(all_modules=all_mods, supporting_modules={})

        valid, _, _ = matcher.match_all(dut_mods, tb_mods)
        self.assertEqual(len(valid), 1)

        available_data = [
            _find_fixture("testbenches/adder_lut.mem"),
            _find_fixture("testbenches/counter_ref.mem"),
            Path("tb/unrelated_noise.hex")
        ]

        planner = VerificationPlanner(
            build_root=self.temp_dir / "build",
            all_modules=all_mods,
            data_files={f.name: f for f in available_data}
        )

        plan = planner.create_plan(valid[0])

        # Verify only counter_ref.mem is associated
        associated_names = [f.name for f in plan.data_files]
        self.assertIn("counter_ref.mem", associated_names)
        self.assertNotIn("adder_lut.mem", associated_names, "Unrelated adder_lut.mem must not be attached to tb_counter")
        self.assertIn("adder_lut.mem", plan.unused_reference_files)

    def test_missing_lut_file_reported(self):
        """If a testbench references a non-existent file, it must appear in missing_reference_files."""
        tb_code = """
        module tb_missing_mem;
            reg [7:0] memory [0:15];
            initial begin
                $readmemh("completely_nonexistent_table.mem", memory);
            end
        endmodule
        """
        tb_file = self.temp_dir / "tb_missing_mem.v"
        tb_file.write_text(tb_code)

        planner = VerificationPlanner(
            build_root=self.temp_dir / "build",
            all_modules={},
            data_files={}
        )

        resolved, missing = planner.extract_testbench_reference_files(tb_file)
        self.assertEqual(len(resolved), 0, "No actual file exists")
        self.assertIn("completely_nonexistent_table.mem", missing)

    def test_parse_reference_file_formats(self):
        """Tests parsing hex, binary, and csv reference formats."""
        # 1. Hex format (.hex / .mem)
        hex_file = self.temp_dir / "test.hex"
        hex_file.write_text("@00 1A 2B 3C // comment\n4D 5E")
        rows = parse_reference_file(hex_file)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["val"], 0x1A)
        self.assertEqual(rows[4]["val"], 0x5E)

        # 2. Binary format (.dat)
        bin_file = self.temp_dir / "test.dat"
        bin_file.write_text("1010\n1100\n0001\n")
        rows = parse_reference_file(bin_file)
        self.assertEqual(len(rows), 3)

        # 3. CSV format (.csv)
        csv_file = self.temp_dir / "test.csv"
        csv_file.write_text("a,b,sum\n1,2,3\n4,5,9\n")
        rows = parse_reference_file(csv_file)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["sum"], "3")

if __name__ == "__main__":
    unittest.main()
