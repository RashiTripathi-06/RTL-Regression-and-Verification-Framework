import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_SRC = WORKSPACE_ROOT / "framework" / "src"
POSIT_EXT = WORKSPACE_ROOT / "extensions" / "posit"

if str(FRAMEWORK_SRC) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK_SRC))
if str(POSIT_EXT) not in sys.path:
    sys.path.insert(0, str(POSIT_EXT))

from posit_model import PositModel, generate_posit_vectors
from rtl_framework.dependency_resolver import DependencyResolver
from rtl_framework.executor import IcarusSimulatorAdapter
from rtl_framework.models import (
    STATUS_FUNCTIONAL_FAIL,
    STATUS_INVALID_OUTPUT,
    STATUS_INVALID_RESULTS,
    STATUS_PASS_APPROXIMATE_REFERENCE,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_REFERENCE_UNVALIDATED,
)
from rtl_framework.scanner import ProjectScanner
from rtl_framework.verification_strategy import (
    GeneratedVector,
    StrategyVerificationRunner,
    VerificationStrategyConfig,
)


class PositVerificationStrategyTests(unittest.TestCase):
    def setUp(self):
        self.pm = PositModel(n=16, es=2)
        self.posit_dir = WORKSPACE_ROOT / "examples" / "posit_multiplier"

    def test_01_nar_and_zero_recognition(self):
        zero = self.pm.decode(0x0000)
        self.assertTrue(zero.is_zero)
        self.assertFalse(zero.is_nar)
        self.assertEqual(zero.real_value, 0.0)

        nar = self.pm.decode(0x8000)
        self.assertTrue(nar.is_nar)
        self.assertFalse(nar.is_zero)

    def test_02_all_special_value_multiplication_cases(self):
        pos = 0x4000   # +1.0
        neg = 0xC000   # -1.0
        zero = 0x0000
        nar = 0x8000

        self.assertEqual(self.pm.multiply(zero, zero), zero)
        self.assertEqual(self.pm.multiply(zero, pos), zero)
        self.assertEqual(self.pm.multiply(zero, neg), zero)
        self.assertEqual(self.pm.multiply(pos, zero), zero)
        self.assertEqual(self.pm.multiply(neg, zero), zero)
        self.assertEqual(self.pm.multiply(nar, zero), nar)
        self.assertEqual(self.pm.multiply(zero, nar), nar)
        self.assertEqual(self.pm.multiply(nar, pos), nar)
        self.assertEqual(self.pm.multiply(nar, neg), nar)
        self.assertEqual(self.pm.multiply(nar, nar), nar)

    def test_03_special_value_and_boundary_generation(self):
        vecs = self.pm.generate_special_value_vectors()
        categories = {v["category"] for v in vecs}
        self.assertIn("special_value", categories)
        self.assertIn("boundary", categories)
        pairs = {(v["opd_a"], v["opd_b"]) for v in vecs}
        self.assertIn((0x0000, 0x0000), pairs)
        self.assertIn((0x0000, 0xC000), pairs)
        self.assertIn((0x8000, 0x0000), pairs)
        self.assertIn((0x0000, 0x8000), pairs)
        self.assertIn((0x8000, 0x8000), pairs)

    def test_04_configurable_counts_and_independent_operands(self):
        for count in (10000, 20000, 30000):
            vecs = self.pm.generate_strategy_vectors(test_count=count, random_seed=12345)
            self.assertEqual(len(vecs), count)
            unique_a = {v["opd_a"] for v in vecs}
            unique_b = {v["opd_b"] for v in vecs}
            unique_pairs = {(v["opd_a"], v["opd_b"]) for v in vecs}
            self.assertGreater(len(unique_a), 1000)
            self.assertGreater(len(unique_b), 1000)
            self.assertEqual(len(unique_pairs), count)
            cats = {v["category"] for v in vecs}
            self.assertEqual(cats, {"special_value", "boundary", "structured", "random"})

    def test_05_random_seed_reproducibility(self):
        v1 = self.pm.generate_strategy_vectors(test_count=10000, random_seed=12345)
        v2 = self.pm.generate_strategy_vectors(test_count=10000, random_seed=12345)
        v3 = self.pm.generate_strategy_vectors(test_count=10000, random_seed=99999)
        self.assertEqual(v1, v2)
        self.assertNotEqual(v1, v3)

    def test_06_nar_not_treated_as_failure_and_unknown_classification(self):
        scanner = ProjectScanner(self.posit_dir)
        proj = scanner.scan()
        dut = proj.all_modules["multiplier"]
        dep_res = DependencyResolver(proj.all_modules).resolve_dependencies(dut)
        runner = StrategyVerificationRunner(adapter=IcarusSimulatorAdapter())

        # Case A: Vector whose expected output IS NaR (0x8000 * 0x4000 -> 0x8000)
        # RTL actually outputs 0x8000 here, so it must PASS_REFERENCE_VERIFIED while counting nar_outputs=1
        cfg = VerificationStrategyConfig(mode="special_values", test_count=1, nar_bit_pattern=0x8000)
        vec_nar_pass = [
            GeneratedVector(
                index=0,
                inputs={"opd_a": 0x8000, "opd_b": 0x4000},
                expected_outputs={"product": 0x8000},
                category="special_value",
                source="unit_test",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            res = runner.execute_vectors(dut, cfg, vec_nar_pass, dep_res.required_source_files, Path(tmp))
            self.assertEqual(res.status, STATUS_PASS_REFERENCE_VERIFIED, res.diagnostic_summary)
            self.assertEqual(res.passed_vectors, 1)
            self.assertEqual(res.failed_vectors, 0)
            self.assertEqual(res.nar_outputs, 1)
            self.assertEqual(res.unknown_outputs, 0)

        # Case B: Failure vector replay for 0x0000 * 0xC000 (RTL outputs 0x8000 instead of 0x0000)
        vec_zero_neg = [
            GeneratedVector(
                index=0,
                inputs={"opd_a": 0x0000, "opd_b": 0xC000},
                expected_outputs={"product": 0x0000},
                category="special_value",
                source="replay_test",
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            res_fail = runner.execute_vectors(dut, cfg, vec_zero_neg, dep_res.required_source_files, Path(tmp))
            self.assertEqual(res_fail.status, STATUS_FUNCTIONAL_FAIL, res_fail.diagnostic_summary)
            self.assertEqual(res_fail.failed_vectors, 1)
            self.assertEqual(res_fail.nar_outputs, 1)
            self.assertEqual(res_fail.failing_vectors[0]["actual_outputs"]["product"], "8000")
            self.assertEqual(res_fail.failing_vectors[0]["expected_outputs"]["product"], "0000")

        # Case C: Unknown (X) output classification is distinct from numerical mismatch
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            actual_csv = tmp_path / "actual_outputs.csv"
            actual_csv.write_text("idx,product\n0,xxxx\n", encoding="utf-8")
            from rtl_framework.models import CompatibilityEvidence, VerificationPlan
            plan = VerificationPlan(
                plan_id="test_unk",
                dut_name="multiplier",
                dut_module="multiplier",
                dut_file=dut.file_path,
                tb_name="tb_unk",
                tb_module="tb_unk",
                tb_file=dut.file_path,
                compatibility=CompatibilityEvidence(True, "test", "EXACT_NAME", "multiplier", "multiplier"),
                required_sources=[],
            )
            import time
            res_unk = runner._audit_outputs(
                actual_csv=actual_csv,
                vectors=vec_nar_pass,
                output_ports=["product"],
                dut=dut,
                plan=plan,
                strategy_cfg=cfg,
                build_dir=tmp_path,
                start_ts=time.perf_counter(),
            )
            self.assertEqual(res_unk.status, STATUS_INVALID_RESULTS)
            self.assertEqual(res_unk.unknown_outputs, 1)
            self.assertEqual(res_unk.reference_status, "INVALID_UNKNOWN_OUTPUTS")

    def test_07_original_65536_testbench_preserved(self):
        tb_orig = self.posit_dir / "tb" / "tb_multiplier.v"
        self.assertTrue(tb_orig.exists())
        text = tb_orig.read_text(encoding="utf-8")
        self.assertIn("16'h4800", text)
        self.assertIn("16'hFFFF", text)

        cfg = json.loads((self.posit_dir / "config.json").read_text(encoding="utf-8"))
        self.assertIn("verification_strategy", cfg)
        self.assertEqual(cfg["verification_strategy"]["test_count"], 30000)
        self.assertTrue(cfg["verification_strategy"]["preserve_original_testbench"])

    def test_08_approximate_reference_mode_end_to_end(self):
        scanner = ProjectScanner(self.posit_dir)
        proj = scanner.scan()
        dut = proj.all_modules["multiplier"]
        dep_res = DependencyResolver(proj.all_modules).resolve_dependencies(dut)
        runner = StrategyVerificationRunner(adapter=IcarusSimulatorAdapter())

        # Finite non-zero pairs should PASS_APPROXIMATE_REFERENCE
        cfg_approx = VerificationStrategyConfig(
            mode="approximate_reference",
            test_count=2,
            approximate_evaluator="extensions.posit.tleap_posit_model:evaluate_posit_tleap_batch",
            nar_bit_pattern=0x8000,
        )
        vecs_finite = [
            GeneratedVector(index=0, inputs={"opd_a": 0x5123, "opd_b": 0x4567}, expected_outputs={}, category="random"),
            GeneratedVector(index=1, inputs={"opd_a": 0xD003, "opd_b": 0x37BD}, expected_outputs={}, category="random"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            res = runner.execute_vectors(dut, cfg_approx, vecs_finite, dep_res.required_source_files, Path(tmp))
            self.assertEqual(res.status, STATUS_PASS_APPROXIMATE_REFERENCE, res.diagnostic_summary)
            self.assertEqual(res.passed_vectors, 2)
            self.assertEqual(res.failed_vectors, 0)
            self.assertIsNotNone(res.approximation_metrics)
            self.assertEqual(res.approximation_metrics["bound_status"], "APPROXIMATION_WITHIN_BOUND")

        # Without approximate_evaluator -> REFERENCE_UNVALIDATED
        cfg_unval = VerificationStrategyConfig(mode="approximate_reference", test_count=1)
        with tempfile.TemporaryDirectory() as tmp:
            res_unval = runner.execute_vectors(dut, cfg_unval, vecs_finite[:1], dep_res.required_source_files, Path(tmp))
            self.assertEqual(res_unval.status, STATUS_REFERENCE_UNVALIDATED)


if __name__ == "__main__":
    unittest.main()
