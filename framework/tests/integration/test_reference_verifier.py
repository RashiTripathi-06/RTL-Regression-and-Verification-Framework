import csv
import json
import unittest
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT))

def _find_fixture(rel_path: str) -> Path:
    cand = FIXTURES_DIR / rel_path
    if cand.exists():
        return cand
    cand2 = WORKSPACE_ROOT / rel_path
    if cand2.exists():
        return cand2
    return Path(rel_path)

from models import (
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_INVALID_RESULTS,
    STATUS_LICENSE_ERROR,
    ModuleInfo,
    PortSpec,
)
from parser import VerilogASTParser
from reference_verifier import (
    ReferenceConfig,
    ReferenceTiming,
    ReferenceDataLoader,
    ReferenceVerificationEngine,
)
from executor import IcarusSimulatorAdapter, QuestaSimulatorAdapter


class ReferenceVerifierTests(unittest.TestCase):

    def setUp(self):
        self.parser = VerilogASTParser()
        self.csv_ref = _find_fixture("references/golden/golden_adder.csv")
        if not self.csv_ref.exists():
            self.csv_ref = _find_fixture("testbenches/golden_adder.csv")
        self.json_ref = _find_fixture("references/golden/golden_adder.json")
        if not self.json_ref.exists():
            self.json_ref = _find_fixture("testbenches/golden_adder.json")
        self.build_dir = WORKSPACE_ROOT / "build" / "test_ref_verifier"
        self.build_dir.mkdir(parents=True, exist_ok=True)

        self.config_csv = ReferenceConfig(
            file=self.csv_ref,
            format="csv",
            radix="hex",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"},
            timing=ReferenceTiming(mode="combinational", settling_time_ns=1.0)
        )

        self.config_json = ReferenceConfig(
            file=self.json_ref,
            format="json",
            radix="hex",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"},
            timing=ReferenceTiming(mode="combinational", settling_time_ns=1.0)
        )

    def test_load_csv_vectors(self):
        vectors = ReferenceDataLoader.load(self.config_csv)
        self.assertEqual(len(vectors), 512)
        v0 = vectors[0]
        self.assertEqual(v0.inputs["a"], 0)
        self.assertEqual(v0.inputs["b"], 0)
        self.assertEqual(v0.inputs["cin"], 0)
        self.assertEqual(v0.expected_outputs["sum"], 0)
        self.assertEqual(v0.expected_outputs["cout"], 0)

    def test_load_json_vectors(self):
        vectors = ReferenceDataLoader.load(self.config_json)
        self.assertEqual(len(vectors), 512)

    def test_behavioral_adder_reference_pass(self):
        dut_file = _find_fixture("designs/adder_behavioral.v")
        mods = self.parser.parse_file(dut_file)
        self.assertTrue(len(mods) > 0)
        dut = mods[0]

        engine = ReferenceVerificationEngine(adapter=IcarusSimulatorAdapter())
        res = engine.verify(
            dut=dut,
            config=self.config_csv,
            dependencies=[],
            build_dir=self.build_dir / "dut_behavioral"
        )

        self.assertEqual(res.status, STATUS_PASS_REFERENCE_VERIFIED)
        self.assertEqual(res.passed_vectors, 512)
        self.assertEqual(res.failed_vectors, 0)
        self.assertEqual(len(res.failing_vectors), 0)

    def test_buggy_adder_reference_fail(self):
        dut_file = _find_fixture("designs/adder_buggy.v")
        mods = self.parser.parse_file(dut_file)
        self.assertTrue(len(mods) > 0)
        dut = mods[0]

        engine = ReferenceVerificationEngine(adapter=IcarusSimulatorAdapter())
        res = engine.verify(
            dut=dut,
            config=self.config_csv,
            dependencies=[],
            build_dir=self.build_dir / "dut_buggy"
        )

        self.assertEqual(res.status, STATUS_FUNCTIONAL_FAIL)
        self.assertTrue(res.failed_vectors > 0)
        self.assertTrue(len(res.failing_vectors) > 0)
        # Check first mismatch structure
        m0 = res.failing_vectors[0]
        self.assertIn("inputs", m0)
        self.assertIn("actual_outputs", m0)
        self.assertIn("expected_outputs", m0)

    def test_x_output_adder_detection(self):
        dut_file = _find_fixture("designs/adder_x_output.v")
        mods = self.parser.parse_file(dut_file)
        self.assertTrue(len(mods) > 0)
        dut = mods[0]

        engine = ReferenceVerificationEngine(adapter=IcarusSimulatorAdapter())
        res = engine.verify(
            dut=dut,
            config=self.config_csv,
            dependencies=[],
            build_dir=self.build_dir / "dut_x"
        )

        self.assertEqual(res.status, STATUS_INVALID_RESULTS)
        self.assertIn("x", res.diagnostic_summary.lower())

    def test_questa_reference_verification(self):
        adapter = QuestaSimulatorAdapter()
        if not adapter.is_available():
            self.skipTest("Questa not available")

        dut_file = _find_fixture("designs/adder_cla.v")
        mods = self.parser.parse_file(dut_file)
        self.assertTrue(len(mods) > 0)
        dut = mods[0]

        engine = ReferenceVerificationEngine(adapter=adapter)
        res = engine.verify(
            dut=dut,
            config=self.config_csv,
            dependencies=[],
            build_dir=self.build_dir / "dut_cla_questa"
        )

        if res.status == STATUS_LICENSE_ERROR and ("WinError 623" in res.diagnostic_summary or "DLL Relocation" in res.diagnostic_summary):
            self.skipTest("Questa execution blocked by Windows sandbox DLL relocation (WinError 623); requires execution outside sandbox")

        self.assertEqual(res.status, STATUS_PASS_REFERENCE_VERIFIED)
        self.assertEqual(res.passed_vectors, 512)


if __name__ == "__main__":
    unittest.main()
