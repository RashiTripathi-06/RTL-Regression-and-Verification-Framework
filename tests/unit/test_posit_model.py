import unittest
import tempfile
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE_ROOT / "plugins" / "posit"))
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))
sys.path.insert(0, str(WORKSPACE_ROOT))

from posit_model import PositModel, parse_posit_lookup_table


class PositModelTests(unittest.TestCase):

    def test_posit_special_values(self):
        pm = PositModel(n=16, es=2)
        zero = pm.decode(0x0000)
        self.assertTrue(zero.is_zero)
        self.assertEqual(zero.real_value, 0.0)

        nar = pm.decode(0x8000)
        self.assertTrue(nar.is_nar)

        one = pm.decode(0x4000)
        self.assertEqual(one.real_value, 1.0)
        self.assertEqual(pm.encode(1.0), 0x4000)

        neg_one = pm.decode(0xC000)
        self.assertEqual(neg_one.real_value, -1.0)
        self.assertEqual(pm.encode(-1.0), 0xC000)

    def test_posit_multiplication_properties(self):
        pm = PositModel(n=16, es=2)
        # Zero times anything is zero
        self.assertEqual(pm.multiply(0x0000, 0x4000), 0x0000)
        self.assertEqual(pm.multiply(0x4000, 0x0000), 0x0000)

        # NaR times anything is NaR
        self.assertEqual(pm.multiply(0x8000, 0x4000), 0x8000)
        self.assertEqual(pm.multiply(0x4000, 0x8000), 0x8000)

        # 1.0 * 1.0 = 1.0
        self.assertEqual(pm.multiply(0x4000, 0x4000), 0x4000)

        # 1.0 * -1.0 = -1.0
        self.assertEqual(pm.multiply(0x4000, 0xC000), 0xC000)

        # -1.0 * -1.0 = 1.0
        self.assertEqual(pm.multiply(0xC000, 0xC000), 0x4000)

    def test_posit_vector_generation(self):
        pm = PositModel(n=16, es=2)
        vecs = pm.generate_regression_vectors(count=50, fixed_a=0x4800, seed=123)
        self.assertGreater(len(vecs), 50)
        self.assertEqual(vecs[0]["operand_a"], "4800")

        with tempfile.TemporaryDirectory() as tmp_dir:
            lut_file = Path(tmp_dir) / "sample_lut.txt"
            lut_file.write_text(
                "# Posit Lookup Table sample\n"
                "0000 0.0\n"
                "4000 1.0\n"
                "C000 -1.0\n"
                "4800 2.0\n",
                encoding="utf-8"
            )
            lut = parse_posit_lookup_table(lut_file)
            self.assertEqual(lut[0x0000], 0.0)
            self.assertEqual(lut[0x4000], 1.0)
            self.assertEqual(lut[0xC000], -1.0)
            self.assertEqual(lut[0x4800], 2.0)


if __name__ == "__main__":
    unittest.main()
