import os
import shutil
import unittest
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT))

from models import (
    VerificationPlan,
    CompatibilityEvidence,
    EXEC_SUCCESS,
    EXEC_LICENSE_ERROR,
    STATUS_LICENSE_ERROR,
)
from executor import QuestaSimulatorAdapter, IsolatedSimulatorExecutor
from auditor import VerificationAuditor


class QuestaSimulatorAdapterTests(unittest.TestCase):

    def setUp(self):
        self.adapter = QuestaSimulatorAdapter()
        self.build_dir = WORKSPACE_ROOT / "build" / "test_questa_adapter"
        self.build_dir.mkdir(parents=True, exist_ok=True)

    def test_discovery_and_version(self):
        if not self.adapter.is_available():
            self.skipTest("Questa binaries (vlib/vlog/vsim) not available on this system.")
        version_str = self.adapter.get_version()
        self.assertTrue(len(version_str) > 0)
        self.assertTrue("Questa" in version_str or "2025" in version_str)

    def test_license_environment_configured(self):
        lic_env = os.environ.get("SALT_LICENSE_SERVER") or os.environ.get("LM_LICENSE_FILE")
        self.assertIsNotNone(lic_env, "License environment variable must be set.")
        lic_path = Path(lic_env)
        self.assertTrue(lic_path.exists(), f"License file at {lic_path} must exist.")

    def test_license_error_detection_strings(self):
        self.assertTrue(self.adapter.is_license_error("Fatal license error: License checkout failed."))
        self.assertTrue(self.adapter.is_license_error("WinError 623: Illegal System DLL Relocation"))
        self.assertTrue(self.adapter.is_license_error("Unable to checkout license feature"))
        self.assertFalse(self.adapter.is_license_error("Errors: 0, Warnings: 0"))
        self.assertFalse(self.adapter.is_license_error("QUESTA LICENSE TEST PASSED"))

    def test_compile_and_simulate_license_test(self):
        if not self.adapter.is_available():
            self.skipTest("Questa not available")

        license_test_file = WORKSPACE_ROOT / "license_test.v"
        self.assertTrue(license_test_file.exists())

        plan = VerificationPlan(
            plan_id="questa_license_test",
            dut_name="license_test",
            dut_module="license_test",
            dut_file=license_test_file,
            tb_name="license_test",
            tb_module="license_test",
            tb_file=license_test_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct test",
                match_type="EXACT_NAME",
                expected_module_name="license_test",
                actual_module_name="license_test"
            ),
            required_sources=[license_test_file],
            data_files=[],
            build_dir=self.build_dir,
            timeout_seconds=15.0,
            questa_flags=["-sv"]
        )

        executor = IsolatedSimulatorExecutor(adapter=self.adapter)
        res = executor.execute(plan)

        if res.is_license_error and ("WinError 623" in res.compile_stderr or "DLL Relocation" in res.compile_stderr):
            self.skipTest("Questa execution blocked by Windows sandbox DLL relocation (WinError 623); requires execution outside sandbox")

        self.assertEqual(res.compile_returncode, 0, f"Compilation failed: {res.compile_stderr}")
        self.assertEqual(res.sim_returncode, 0, f"Simulation failed: {res.sim_stderr}")
        self.assertFalse(res.timed_out)
        self.assertFalse(res.is_license_error)
        self.assertIn("QUESTA LICENSE TEST PASSED", res.sim_stdout)

        auditor = VerificationAuditor()
        audit_res = auditor.audit(res)
        self.assertEqual(audit_res.execution_status, EXEC_SUCCESS)


if __name__ == "__main__":
    unittest.main()
