import unittest
import tempfile
import json
import shutil
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT))

from models import (
    VerificationPlan,
    CompatibilityEvidence,
    TestResult,
    STATUS_PASS,
)
from cache_manager import CacheManager
from report_generator import ReportGenerator
from engine import RegressionEngine


class ReproducibilityTests(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.dut_file = self.tmp_dir / "dut.v"
        self.dut_file.write_text("module dut(input a, output y); assign y = a; endmodule\n", encoding="utf-8")
        
        self.tb_file = self.tmp_dir / "tb.v"
        self.tb_file.write_text("module tb; reg a; wire y; dut uut(a, y); initial $finish; endmodule\n", encoding="utf-8")

        self.plan = VerificationPlan(
            plan_id="dut__tb",
            dut_name="dut",
            dut_module="dut",
            dut_file=self.dut_file,
            tb_name="tb",
            tb_module="tb",
            tb_file=self.tb_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct instantiation",
                match_type="EXACT_NAME",
                expected_module_name="dut",
                actual_module_name="dut"
            ),
            required_sources=[self.dut_file, self.tb_file],
            data_files=[],
            simulator_name="icarus"
        )
        self.cache_file = self.tmp_dir / "cache.json"
        self.cache_mgr = CacheManager(self.cache_file)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_merkle_hash_invalidation_dut(self):
        h1 = self.cache_mgr.compute_hash(self.plan)
        # Modify DUT
        self.dut_file.write_text("module dut(input a, output y); assign y = ~a; endmodule\n", encoding="utf-8")
        h2 = self.cache_mgr.compute_hash(self.plan)
        self.assertNotEqual(h1, h2, "Modifying DUT source must invalidate Merkle root hash")

    def test_merkle_hash_invalidation_tb(self):
        h1 = self.cache_mgr.compute_hash(self.plan)
        # Modify TB
        self.tb_file.write_text("module tb; reg a; wire y; dut uut(a, y); initial #10 $finish; endmodule\n", encoding="utf-8")
        h2 = self.cache_mgr.compute_hash(self.plan)
        self.assertNotEqual(h1, h2, "Modifying TB source must invalidate Merkle root hash")

    def test_merkle_hash_invalidation_compiler_flags(self):
        h1 = self.cache_mgr.compute_hash(self.plan)
        self.plan.iverilog_flags.append("-DEXTRA_MACRO=1")
        h2 = self.cache_mgr.compute_hash(self.plan)
        self.assertNotEqual(h1, h2, "Modifying compiler flags must invalidate Merkle root hash")

    def test_merkle_hash_invalidation_simulator(self):
        h1 = self.cache_mgr.compute_hash(self.plan)
        self.plan.simulator_name = "questa"
        h2 = self.cache_mgr.compute_hash(self.plan)
        self.assertNotEqual(h1, h2, "Changing simulator adapter must invalidate Merkle root hash")

    def test_cache_hit_and_retrieval(self):
        res = TestResult(
            plan_id=self.plan.plan_id,
            dut_name="dut",
            tb_name="tb",
            status=STATUS_PASS,
            passed_vectors=10,
            total_vectors=10
        )
        self.cache_mgr.put(self.plan, res)
        cached = self.cache_mgr.get(self.plan)
        self.assertIsNotNone(cached)
        self.assertTrue(cached.cached)
        self.assertEqual(cached.passed_vectors, 10)

    def test_history_logging_and_replay(self):
        reports_dir = self.tmp_dir / "reports"
        history_file = reports_dir / "verification_history.jsonl"
        rep_gen = ReportGenerator(reports_dir, history_file)

        res = TestResult(
            plan_id="dut__tb",
            dut_name="dut",
            tb_name="tb",
            status=STATUS_PASS,
            passed_vectors=1,
            total_vectors=1,
            diagnostic_summary="Simulation passed."
        )
        csv_p, json_p, html_p = rep_gen.generate([res], project_name="UnitTestSuite")

        # Verify history file created and contains run_id
        self.assertTrue(history_file.exists())
        lines = history_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertIn("run_id", record)
        self.assertTrue(record["run_id"].startswith("run_"))
        self.assertEqual(record["total_plans"], 1)

        # Verify alternate history.jsonl also written
        alt_history = reports_dir / "history.jsonl"
        self.assertTrue(alt_history.exists())


if __name__ == "__main__":
    unittest.main()
