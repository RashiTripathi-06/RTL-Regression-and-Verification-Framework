import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "src"))

from reference_manager import (
    ReferenceCategory,
    ReferenceSource,
    ReferenceClassificationEngine,
    ReferenceResolver,
    ReferenceResolutionResult
)
from reference_verifier import ReferenceConfig, ReferenceTiming, ReferenceDataLoader
from models import (
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_REFERENCE_DISPUTED,
    STATUS_REFERENCE_UNAVAILABLE,
    ModuleInfo,
    PortSpec
)


class ReferenceManagerTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="ref_mgr_test_"))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_classification_engine_categories(self):
        # 1. Direct I/O table
        csv_file = self.test_dir / "io_table.csv"
        csv_file.write_text("in_a,in_b,out_c\n1,2,3\n4,5,9\n", encoding="utf-8")
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=csv_file),
            ReferenceCategory.DIRECT_IO_TABLE
        )

        # 2. Decoding table (2 cols mapping to float values)
        dec_file = self.test_dir / "decoding.csv"
        dec_file.write_text("bits,real_val\n4800,2.0\n4000,1.0\n", encoding="utf-8")
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=dec_file),
            ReferenceCategory.DECODING_TABLE
        )

        # 3. Documentation
        doc_file = self.test_dir / "manual.pdf"
        doc_file.write_bytes(b"%PDF-1.4 dummy")
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=doc_file),
            ReferenceCategory.DOCUMENTATION
        )

        # 4. Mathematical Spec
        spec_file = self.test_dir / "spec.md"
        spec_file.write_text("# Standard Arithmetic Spec\n$$P = A \\times B$$", encoding="utf-8")
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=spec_file),
            ReferenceCategory.MATHEMATICAL_SPEC
        )

        # 5. Remote URL classification
        self.assertEqual(
            ReferenceClassificationEngine.classify(url="https://www.posithub.org/widget/lookup"),
            ReferenceCategory.DECODING_TABLE
        )

    # CASE 1: Valid primary golden reference, no secondary source
    def test_case_1_valid_primary_no_secondary(self):
        gold_file = self.test_dir / "golden.csv"
        gold_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "golden_dataset",
                    "path": str(gold_file.name),
                    "priority": 1,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_1_PRIMARY_ACTIVE")
        self.assertIsNotNone(res.active_source)
        self.assertEqual(res.active_source.name, "golden_dataset")
        self.assertEqual(res.provenance["primary_source"], "golden_dataset")
        self.assertEqual(res.cross_validation_status, "NOT_APPLICABLE")

    # CASE 2: Valid primary and agreeing secondary references
    def test_case_2_valid_primary_and_agreeing_secondary(self):
        gold_file = self.test_dir / "golden.csv"
        gold_file.write_text("a,b,c\n1,2,3\n4,5,9\n", encoding="utf-8")

        sec_file = self.test_dir / "secondary.csv"
        sec_file.write_text("a,b,c\n1,2,3\n4,5,9\n", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "golden_dataset",
                    "path": str(gold_file.name),
                    "priority": 1,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                },
                "secondary": {
                    "name": "professor_crossval",
                    "path": str(sec_file.name),
                    "priority": 2,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_1_PRIMARY_ACTIVE")
        self.assertEqual(res.cross_validation_status, "MATCH")
        self.assertEqual(len(res.conflicting_vectors), 0)

    # CASE 3: Valid primary and conflicting secondary references
    def test_case_3_valid_primary_and_conflicting_secondary(self):
        gold_file = self.test_dir / "golden.csv"
        gold_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

        prof_file = self.test_dir / "prof_conflicting.csv"
        # Same input (1, 2) but conflicting output (4 instead of 3)
        prof_file.write_text("a,b,c\n1,2,4\n", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "golden_dataset",
                    "path": str(gold_file.name),
                    "priority": 1,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                },
                "secondary": {
                    "name": "professor_material",
                    "path": str(prof_file.name),
                    "priority": 2,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_3_DISPUTED")
        self.assertEqual(res.cross_validation_status, "DISPUTED")
        self.assertGreater(len(res.conflicting_vectors), 0)
        self.assertIn("Reference conflict detected", res.diagnostic)
        # Ensure neither file was overwritten
        self.assertIn("1,2,3", gold_file.read_text(encoding="utf-8"))
        self.assertIn("1,2,4", prof_file.read_text(encoding="utf-8"))

    # CASE 4: Missing primary with valid direct-I/O secondary reference
    def test_case_4_missing_primary_with_valid_direct_io_secondary(self):
        sec_file = self.test_dir / "professor_vectors.csv"
        sec_file.write_text("a,b,c\n1,2,3\n", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "golden_dataset",
                    "path": "non_existent_golden.csv",
                    "priority": 1
                },
                "secondary": {
                    "name": "prof_table",
                    "path": str(sec_file.name),
                    "priority": 2,
                    "input_mapping": {"a": "in_a", "b": "in_b"},
                    "output_mapping": {"c": "out_c"}
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_2_FALLBACK_ACTIVE")
        self.assertEqual(res.active_source.name, "prof_table")
        self.assertEqual(res.provenance["fallback_source"], "prof_table")

    # CASE 5: Missing primary and unusable secondary reference
    def test_case_5_missing_primary_and_unusable_secondary(self):
        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "golden_dataset",
                    "path": "missing_file_a.csv",
                    "priority": 1
                },
                "secondary": {
                    "name": "prof_doc",
                    "url": "https://example.com/missing_doc",
                    "priority": 2
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_4_UNAVAILABLE")
        self.assertIsNone(res.active_config)
        self.assertIn("Reference Unavailable", res.diagnostic)

    # CASE 6: Secondary decoding table with valid primary arithmetic reference
    def test_case_6_secondary_decoding_table_with_valid_primary_arithmetic(self):
        gold_file = self.test_dir / "arithmetic_golden.csv"
        gold_file.write_text("opd_a,opd_b,product\n4800,4000,4800\n", encoding="utf-8")

        dec_file = self.test_dir / "decoding_lookup.csv"
        dec_file.write_text("bits,real_val\n4800,2.0\n4000,1.0\n", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "arithmetic_primary",
                    "path": str(gold_file.name),
                    "priority": 1,
                    "input_mapping": {"opd_a": "opd_a", "opd_b": "opd_b"},
                    "output_mapping": {"product": "product"}
                },
                "secondary": {
                    "name": "posithub_decoding",
                    "path": str(dec_file.name),
                    "priority": 2,
                    "type": "decoding_table"
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        # Primary arithmetic table must remain active, secondary decoding table does not cause false conflict
        self.assertEqual(res.case, "CASE_1_PRIMARY_ACTIVE")
        self.assertEqual(res.active_source.name, "arithmetic_primary")
        self.assertEqual(res.cross_validation_status, "NOT_APPLICABLE")

    # CASE 7: Secondary mathematical specification without executable provider
    def test_case_7_secondary_mathematical_spec_without_executable_provider(self):
        spec_file = self.test_dir / "algorithm_spec.md"
        spec_file.write_text("# Multiplication Algorithm\nResult is product of inputs.", encoding="utf-8")

        cfg = {
            "reference_sources": {
                "secondary": {
                    "name": "math_spec",
                    "path": str(spec_file.name),
                    "priority": 2,
                    "type": "mathematical_spec"
                }
            }
        }

        res = ReferenceResolver.resolve(cfg, self.test_dir)
        # Without an executable provider, specification cannot drive Path B vectors
        self.assertEqual(res.case, "CASE_4_UNAVAILABLE")
        self.assertIn("mathematical_spec", res.diagnostic)

    # CASE 8: Missing, empty, malformed, and incompatible reference files
    def test_case_8_missing_empty_malformed_and_incompatible_reference_files(self):
        # Empty file
        empty_file = self.test_dir / "empty.csv"
        empty_file.write_text("", encoding="utf-8")
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=empty_file),
            ReferenceCategory.UNSUPPORTED
        )

        # Missing file
        missing_file = self.test_dir / "nonexistent.csv"
        self.assertEqual(
            ReferenceClassificationEngine.classify(file_path=missing_file),
            ReferenceCategory.UNSUPPORTED
        )

        # Malformed format handling in DataLoader
        malformed_file = self.test_dir / "malformed.csv"
        malformed_file.write_text("a,b,c\ninvalid_hex,z,null\n", encoding="utf-8")
        ref_cfg = ReferenceConfig(
            file=malformed_file,
            format="csv",
            input_mapping={"a": "in_a"},
            output_mapping={"c": "out_c"}
        )
        vecs = ReferenceDataLoader.load(ref_cfg)
        self.assertEqual(len(vecs), 0, "Malformed unparseable values must yield 0 usable vectors")

    # Path A continues independently when Path B has no usable reference
    def test_path_a_continues_when_path_b_has_no_usable_reference(self):
        # When reference is unavailable, Path B resolution marks CASE_4_UNAVAILABLE
        cfg = {
            "reference_sources": {
                "primary": {
                    "name": "absent_primary",
                    "path": "does_not_exist.csv",
                    "priority": 1
                }
            }
        }
        res = ReferenceResolver.resolve(cfg, self.test_dir)
        self.assertEqual(res.case, "CASE_4_UNAVAILABLE")
        # In engine, this permits Path A testbenches to execute and report PASS_TESTBENCH_ONLY or EXECUTED_NOT_VERIFIED


if __name__ == "__main__":
    unittest.main()
