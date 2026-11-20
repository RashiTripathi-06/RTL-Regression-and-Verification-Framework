from __future__ import annotations
import shutil
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cache_manager import CacheManager
from models import VerificationPlan, CompatibilityEvidence, TestResult, STATUS_PASS

class ComprehensiveCacheInvalidationTests(unittest.TestCase):
    """
    Tests rigorous SHA-256 Merkle cache invalidation across every independent factor:
    1. DUT source change
    2. Submodule dependency change
    3. Testbench source change
    4. Reference / LUT data change
    5. Wrapper mapping change
    6. Compiler flags / configuration change
    """

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="merkle_cache_test_"))
        self.cache_file = self.temp_dir / ".test_cache.json"
        self.cache_mgr = CacheManager(self.cache_file)

        # Base fixtures
        self.dut_file = self.temp_dir / "my_dut.v"
        self.dut_file.write_text("module my_dut(input a, output y); assign y = a; endmodule")

        self.sub_file = self.temp_dir / "sub_leaf.v"
        self.sub_file.write_text("module sub_leaf(input a, output y); assign y = a; endmodule")

        self.tb_file = self.temp_dir / "my_tb.v"
        self.tb_file.write_text("module my_tb; reg a; wire y; my_dut dut(a, y); endmodule")

        self.lut_file = self.temp_dir / "golden_ref.mem"
        self.lut_file.write_text("00\n01\n02\n03\n")

        self.wrapper_file = self.temp_dir / "wrapper.v"
        self.wrapper_file.write_text("module wrapper(input a, output y); my_dut uut(a, y); endmodule")

        self.base_plan = VerificationPlan(
            plan_id="test_plan",
            dut_name="my_dut",
            dut_module="my_dut",
            dut_file=self.dut_file,
            tb_name="my_tb",
            tb_module="my_tb",
            tb_file=self.tb_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Match",
                match_type="WRAPPER_COMPATIBLE",
                expected_module_name="my_dut",
                actual_module_name="my_dut",
                port_mapping={"a": "a", "y": "y"},
                wrapper_needed=True
            ),
            required_sources=[self.sub_file, self.dut_file, self.wrapper_file, self.tb_file],
            data_files=[self.lut_file],
            wrapper_path=self.wrapper_file,
            iverilog_flags=["-g2012", "-Wall"],
            timeout_seconds=5.0
        )

        # Baseline hash
        self.base_hash = self.cache_mgr.compute_hash(self.base_plan)
        dummy_result = TestResult(
            plan_id="test_plan",
            dut_name="my_dut",
            tb_name="my_tb",
            status=STATUS_PASS,
            passed_vectors=4,
            total_vectors=4
        )
        self.cache_mgr.put(self.base_plan, dummy_result)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_hits_when_unchanged(self):
        res = self.cache_mgr.get(self.base_plan)
        self.assertIsNotNone(res)
        self.assertTrue(res.cached)
        self.assertEqual(res.status, STATUS_PASS)

    def test_invalidation_on_dut_source_change(self):
        self.dut_file.write_text("module my_dut(input a, output y); assign y = ~a; endmodule")
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing DUT must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "DUT modification must invalidate cache")

    def test_invalidation_on_submodule_change(self):
        self.sub_file.write_text("module sub_leaf(input a, output y); assign y = a ^ 1; endmodule")
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing submodule dependency must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "Submodule modification must invalidate cache")

    def test_invalidation_on_testbench_change(self):
        self.tb_file.write_text("module my_tb; reg a; wire y; /* extra check */ my_dut dut(a, y); endmodule")
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing testbench must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "Testbench modification must invalidate cache")

    def test_invalidation_on_lut_reference_change(self):
        self.lut_file.write_text("00\n01\n02\nFF\n")
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing LUT reference file must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "LUT modification must invalidate cache")

    def test_invalidation_on_wrapper_mapping_change(self):
        self.base_plan.compatibility.port_mapping = {"a": "different_port", "y": "y"}
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing wrapper port mapping must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "Wrapper mapping change must invalidate cache")

    def test_invalidation_on_compiler_flags_change(self):
        self.base_plan.iverilog_flags = ["-g2012", "-Wall", "-DEXTRA_DEF=1"]
        new_hash = self.cache_mgr.compute_hash(self.base_plan)
        self.assertNotEqual(self.base_hash, new_hash, "Changing compiler flags must alter Merkle hash")
        self.assertIsNone(self.cache_mgr.get(self.base_plan), "Compiler flags change must invalidate cache")

if __name__ == "__main__":
    unittest.main()
