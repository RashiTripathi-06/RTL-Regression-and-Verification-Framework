import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from models import VerificationPlan, CompatibilityEvidence, TestResult
from cache_manager import CacheManager

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = ROOT / "build" / "cache_test"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.temp_dir / "test_cache.json"
        if self.cache_file.exists():
            self.cache_file.unlink()

        self.dut_file = self.temp_dir / "mock_dut.v"
        self.tb_file = self.temp_dir / "mock_tb.v"
        self.dut_file.write_text("module dut; endmodule", encoding="utf-8")
        self.tb_file.write_text("module tb; endmodule", encoding="utf-8")

        self.plan = VerificationPlan(
            plan_id="mock_dut__mock_tb",
            dut_name="mock_dut",
            dut_module="mock_dut",
            dut_file=self.dut_file,
            tb_name="mock_tb",
            tb_module="mock_tb",
            tb_file=self.tb_file,
            compatibility=CompatibilityEvidence(
                matched=True, reason="", match_type="EXACT_NAME",
                expected_module_name="mock_dut", actual_module_name="mock_dut"
            ),
            required_sources=[self.dut_file, self.tb_file],
            data_files=[],
            include_dirs=[],
            build_dir=self.temp_dir
        )

    def test_cache_miss_put_and_hit(self):
        mgr = CacheManager(self.cache_file)
        self.assertIsNone(mgr.get(self.plan))

        result = TestResult(
            plan_id=self.plan.plan_id,
            dut_name=self.plan.dut_name,
            tb_name=self.plan.tb_name,
            status="PASS",
            passed_vectors=512,
            total_vectors=512
        )
        mgr.put(self.plan, result)

        cached = mgr.get(self.plan)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.cached)
        self.assertEqual(cached.status, "PASS")

    def test_cache_invalidation_on_dut_change(self):
        mgr = CacheManager(self.cache_file)
        result = TestResult(
            plan_id=self.plan.plan_id,
            dut_name=self.plan.dut_name,
            tb_name=self.plan.tb_name,
            status="PASS"
        )
        mgr.put(self.plan, result)
        self.assertIsNotNone(mgr.get(self.plan))

        # Modify DUT source file -> should invalidate cache!
        self.dut_file.write_text("module dut; /* modified */ endmodule", encoding="utf-8")
        self.assertIsNone(mgr.get(self.plan))

if __name__ == "__main__":
    unittest.main()
