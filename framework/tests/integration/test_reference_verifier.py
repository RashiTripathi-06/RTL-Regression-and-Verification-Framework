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
    STATUS_INCOMPLETE,
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
    ReferenceHarnessGenerator,
    ReferenceScoreboard,
    ParsedVector,
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

    def test_reject_missing_configured_input_field(self):
        """Reference vectors with missing configured input fields must be rejected."""
        csv_file = self.build_dir / "missing_input.csv"
        # Config expects operand_a, operand_b, cin. Header omits cin.
        csv_file.write_text("operand_a,operand_b,expected_sum,expected_cout\n0,1,1,0\n", encoding="utf-8")
        cfg = ReferenceConfig(
            file=csv_file,
            format="csv",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"}
        )
        with self.assertRaises(ValueError) as cm:
            ReferenceDataLoader.load(cfg, strict=True)
        self.assertIn("cin", str(cm.exception))

    def test_reject_missing_configured_expected_output_field(self):
        """Reference vectors with missing configured expected output fields must be rejected."""
        csv_file = self.build_dir / "missing_output.csv"
        csv_file.write_text("operand_a,operand_b,cin,expected_sum\n0,1,0,1\n", encoding="utf-8")
        cfg = ReferenceConfig(
            file=csv_file,
            format="csv",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"}
        )
        with self.assertRaises(ValueError) as cm:
            ReferenceDataLoader.load(cfg, strict=True)
        self.assertIn("cout", str(cm.exception))

    def test_reject_invalid_numeric_values(self):
        """Invalid non-numeric values must be rejected."""
        csv_file = self.build_dir / "invalid_numeric.csv"
        csv_file.write_text("operand_a,operand_b,cin,expected_sum,expected_cout\nNOT_A_NUM,1,0,1,0\n", encoding="utf-8")
        cfg = ReferenceConfig(
            file=csv_file,
            format="csv",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"}
        )
        with self.assertRaises(ValueError) as cm:
            ReferenceDataLoader.load(cfg, strict=True)
        self.assertIn("NOT_A_NUM", str(cm.exception))

    def test_reject_values_outside_dut_port_width(self):
        """Values exceeding configured DUT port bitwidth must be rejected."""
        csv_file = self.build_dir / "overflow_width.csv"
        # 0x20 = 32 decimal, which cannot fit in a 4-bit port (max 15)
        csv_file.write_text("operand_a,operand_b,cin,expected_sum,expected_cout\n20,1,0,1,0\n", encoding="utf-8")
        cfg = ReferenceConfig(
            file=csv_file,
            format="csv",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"}
        )
        dut_file = _find_fixture("designs/adder_behavioral.v")
        dut = self.parser.parse_file(dut_file)[0]
        with self.assertRaises(ValueError) as cm:
            ReferenceDataLoader.load(cfg, dut=dut, strict=True)
        self.assertIn("exceeds configured port width", str(cm.exception))

    def test_generator_rejects_missing_inputs_without_silent_zero(self):
        """ReferenceHarnessGenerator must never silently substitute 0 for missing inputs."""
        dut_file = _find_fixture("designs/adder_behavioral.v")
        dut = self.parser.parse_file(dut_file)[0]
        cfg = ReferenceConfig(
            file=self.csv_ref,
            format="csv",
            input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
            output_mapping={"expected_sum": "sum", "expected_cout": "cout"}
        )
        # Vector is missing input port 'b' and 'cin'
        bad_vec = ParsedVector(
            index=0,
            inputs={"a": 5},
            expected_outputs={"sum": 5, "cout": 0},
            source_line=1,
            raw_row={}
        )
        with self.assertRaises(ValueError) as cm:
            ReferenceHarnessGenerator.generate(dut, cfg, [bad_vec], self.build_dir / "bad_harness")
        self.assertIn("Missing inputs must not be silently replaced with zero", str(cm.exception))

    def test_scoreboard_captured_output_count_mismatch(self):
        """Scoreboard must require actual output rows to equal expected vector count."""
        act_csv = self.build_dir / "short_outputs.csv"
        # Only 1 row output for 2 expected vectors
        act_csv.write_text("idx,sum,cout\n0,5,0\n", encoding="utf-8")
        exp_vectors = [
            ParsedVector(index=0, inputs={"a": 5, "b": 0, "cin": 0}, expected_outputs={"sum": 5, "cout": 0}, source_line=1, raw_row={}),
            ParsedVector(index=1, inputs={"a": 5, "b": 1, "cin": 0}, expected_outputs={"sum": 6, "cout": 0}, source_line=2, raw_row={}),
        ]
        status, passed, total, failed, mismatches, diag = ReferenceScoreboard.audit(
            act_csv, exp_vectors, self.config_csv
        )
        self.assertEqual(status, STATUS_INCOMPLETE)
        self.assertIn("Simulation terminated early", diag)

        # More actual rows than expected
        long_csv = self.build_dir / "long_outputs.csv"
        long_csv.write_text("idx,sum,cout\n0,5,0\n1,6,0\n2,7,0\n", encoding="utf-8")
        status2, passed2, total2, failed2, mismatches2, diag2 = ReferenceScoreboard.audit(
            long_csv, exp_vectors, self.config_csv
        )
        self.assertEqual(status2, STATUS_INVALID_RESULTS)
        self.assertIn("exceeds expected vector count", diag2)

    def test_scoreboard_rejects_missing_output_column(self):
        """Scoreboard must reject actual outputs missing configured output columns."""
        act_csv = self.build_dir / "missing_col_outputs.csv"
        act_csv.write_text("idx,sum\n0,5\n", encoding="utf-8")
        exp_vectors = [
            ParsedVector(index=0, inputs={"a": 5, "b": 0, "cin": 0}, expected_outputs={"sum": 5, "cout": 0}, source_line=1, raw_row={}),
        ]
        status, passed, total, failed, mismatches, diag = ReferenceScoreboard.audit(
            act_csv, exp_vectors, self.config_csv
        )
        self.assertEqual(status, STATUS_INVALID_RESULTS)
        self.assertIn("missing configured output column", diag)

    def test_scoreboard_rejects_malformed_duplicate_out_of_order_indices(self):
        """Scoreboard must reject malformed, duplicate, or out-of-order indices."""
        # 1. Malformed index
        mal_csv = self.build_dir / "malformed_idx.csv"
        mal_csv.write_text("idx,sum,cout\nnot_an_int,5,0\n", encoding="utf-8")
        exp_vectors = [
            ParsedVector(index=0, inputs={"a": 5, "b": 0, "cin": 0}, expected_outputs={"sum": 5, "cout": 0}, source_line=1, raw_row={}),
        ]
        status1, _, _, _, _, diag1 = ReferenceScoreboard.audit(mal_csv, exp_vectors, self.config_csv)
        self.assertEqual(status1, STATUS_INVALID_RESULTS)
        self.assertIn("Malformed vector index", diag1)

        # 2. Duplicate index
        dup_csv = self.build_dir / "dup_idx.csv"
        dup_csv.write_text("idx,sum,cout\n0,5,0\n0,6,0\n", encoding="utf-8")
        exp2 = [
            ParsedVector(index=0, inputs={"a": 5, "b": 0, "cin": 0}, expected_outputs={"sum": 5, "cout": 0}, source_line=1, raw_row={}),
            ParsedVector(index=1, inputs={"a": 5, "b": 1, "cin": 0}, expected_outputs={"sum": 6, "cout": 0}, source_line=2, raw_row={}),
        ]
        status2, _, _, _, _, diag2 = ReferenceScoreboard.audit(dup_csv, exp2, self.config_csv)
        self.assertEqual(status2, STATUS_INVALID_RESULTS)
        self.assertIn("Duplicate vector index", diag2)

        # 3. Out-of-order index
        ooo_csv = self.build_dir / "ooo_idx.csv"
        ooo_csv.write_text("idx,sum,cout\n1,6,0\n0,5,0\n", encoding="utf-8")
        status3, _, _, _, _, diag3 = ReferenceScoreboard.audit(ooo_csv, exp2, self.config_csv)
        self.assertEqual(status3, STATUS_INVALID_RESULTS)
        self.assertIn("Out-of-order vector index", diag3)

    def test_scoreboard_never_pass_partially_unchecked_vector(self):
        """Vectors with uncompared/missing expected output ports must never be classified as passed."""
        act_csv = self.build_dir / "unchecked_output.csv"
        act_csv.write_text("idx,sum,cout\n0,5,0\n", encoding="utf-8")
        # Expected outputs has 'sum' but is missing 'cout'
        exp_vectors = [
            ParsedVector(index=0, inputs={"a": 5, "b": 0, "cin": 0}, expected_outputs={"sum": 5}, source_line=1, raw_row={}),
        ]
        status, passed, total, failed, mismatches, diag = ReferenceScoreboard.audit(
            act_csv, exp_vectors, self.config_csv
        )
        self.assertEqual(status, STATUS_FUNCTIONAL_FAIL)
        self.assertEqual(passed, 0)
        self.assertEqual(failed, 1)


if __name__ == "__main__":
    unittest.main()
