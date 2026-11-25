import sys
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
POSIT_EXT = WORKSPACE_ROOT / "extensions" / "posit"
if str(POSIT_EXT) not in sys.path:
    sys.path.insert(0, str(POSIT_EXT))

from posit_model import PositModel
from tleap_posit_model import (
    TLEAP_MANTISSA_REL_BOUND,
    TLeapPositModel,
    evaluate_posit_tleap_batch,
    posit_ulp_distance,
)


class _DummyVec:
    def __init__(self, a: int, b: int, cat: str = "random", source: str = "test", desc: str = ""):
        self.inputs = {"opd_a": a, "opd_b": b}
        self.category = cat
        self.source = source
        self.description = desc


class _DummyCfg:
    def __init__(self):
        self.generator_params = {
            "n": 16,
            "es": 2,
            "input_a_port": "opd_a",
            "input_b_port": "opd_b",
            "output_port": "product",
        }


class TLeapPositModelTests(unittest.TestCase):
    def setUp(self):
        self.exact = PositModel(n=16, es=2)
        self.tleap = TLeapPositModel(n=16, es=2)

    def test_special_values_explicit(self):
        zero = 0x0000
        nar = 0x8000
        for val in (0x0000, 0x4000, 0xC000, 0x7FFF, 0x8001, 0x0001, 0xFFFF):
            self.assertEqual(self.tleap.multiply(nar, val), nar)
            self.assertEqual(self.tleap.multiply(val, nar), nar)
            if val != nar:
                self.assertEqual(self.tleap.multiply(zero, val), zero)
                self.assertEqual(self.tleap.multiply(val, zero), zero)

    def test_manual_intermediate_equations(self):
        # 1.0 (0x4000) * 1.0 (0x4000) -> 1.0 (0x4000), pp1=0, pp2=0, exp_carry=0
        out, inter = self.tleap.multiply_with_details(0x4000, 0x4000)
        self.assertEqual(out, 0x4000)
        self.assertIsNotNone(inter)
        self.assertEqual(inter.pp_sum, 0)
        self.assertEqual(inter.exp_carry, 0)
        self.assertEqual(inter.k_c, 0)
        self.assertEqual(inter.mantissa_rel_error, 0.0)

        # 1.5 (0x4400: k=0, exp=0, fa=0.5 -> 0x400) * 1.5 (0x4400)
        # x1=x2=128 (0.5): p1=p2=1, rem1=rem2=0 -> pp1 = 128>>1 = 64 (0.25), pp2=0 -> exact!
        out2, inter2 = self.tleap.multiply_with_details(0x4400, 0x4400)
        self.assertIsNotNone(inter2)
        self.assertEqual(inter2.pp1, 64)
        self.assertEqual(inter2.pp2, 0)
        self.assertEqual(inter2.exp_carry, 1)  # 1 + 0.5 + 0.5 + 0.25 = 2.25 >= 2
        self.assertAlmostEqual(inter2.mantissa_exact, 2.25, places=6)
        self.assertAlmostEqual(inter2.mantissa_tleap, 2.25, places=6)
        self.assertEqual(self.exact.decode(out2).real_value, 2.25)

    def test_sign_symmetry_and_commutativity(self):
        samples = [0x4000, 0x4400, 0x4800, 0x3800, 0x5678, 0x2345, 0x7001, 0x0123]
        # Commutativity holds whenever both 8-bit truncated fractions are non-zero (or both zero);
        # when one is 0 and the other >= 128, encoder_8bit's pos=7 for 0 introduces a 1-LSB asymmetry.
        non_zero_frac_samples = [0x4400, 0x5678, 0x2345, 0x4C00]
        for a in non_zero_frac_samples:
            for b in non_zero_frac_samples:
                self.assertEqual(self.tleap.multiply(a, b), self.tleap.multiply(b, a))

        for a in samples:
            neg_a = (-a) & 0xFFFF
            for b in samples:
                neg_b = (-b) & 0xFFFF
                # Sign symmetry: tleap(-a, b) == -tleap(a, b)
                p_pos = self.tleap.multiply(a, b)
                p_neg = self.tleap.multiply(neg_a, b)
                self.assertEqual(p_neg, (-p_pos) & 0xFFFF)
                # Double negation: tleap(-a, -b) == tleap(a, b)
                self.assertEqual(self.tleap.multiply(neg_a, neg_b), p_pos)

    def test_extreme_values_and_regime_transitions(self):
        # maxpos * maxpos saturates to maxpos (0x7FFF)
        self.assertEqual(self.tleap.multiply(0x7FFF, 0x7FFF), 0x7FFF)
        # -maxpos * maxpos saturates to -maxpos (0x8001)
        self.assertEqual(self.tleap.multiply(0x8001, 0x7FFF), 0x8001)
        # minpos * minpos underflows to 0x0000 under truncation
        self.assertEqual(self.tleap.multiply(0x0001, 0x0001), 0x0000)
        # Regime/exp transition: 2.0 (0x4800) * 8.0 (0x5800) = 16.0 (0x6000, k=1, exp=0)
        self.assertEqual(self.tleap.multiply(0x4800, 0x5800), 0x6000)

    def test_ulp_distance_posit_ordinal(self):
        self.assertEqual(posit_ulp_distance(0x4000, 0x4001), 1)
        self.assertEqual(posit_ulp_distance(0xFFFF, 0x0001), 2)
        self.assertEqual(posit_ulp_distance(0xC000, 0xC000), 0)

    def test_evaluator_statuses(self):
        cfg = _DummyCfg()
        vecs = [_DummyVec(0x4400, 0x4400, "structured"), _DummyVec(0x4000, 0xC000, "boundary")]
        act_pass = [
            {"product": self.tleap.multiply(0x4400, 0x4400)},
            {"product": self.tleap.multiply(0x4000, 0xC000)},
        ]
        res_pass = evaluate_posit_tleap_batch(vecs, act_pass, cfg)
        self.assertEqual(res_pass["status"], "PASS_APPROXIMATE_REFERENCE")
        self.assertEqual(res_pass["bound_status"], "APPROXIMATION_WITHIN_BOUND")
        self.assertLessEqual(res_pass["max_mantissa_rel_error"], TLEAP_MANTISSA_REL_BOUND)

        # Unknown X/Z -> INVALID_OUTPUT
        res_xz = evaluate_posit_tleap_batch(vecs, [None, act_pass[1]], cfg)
        self.assertEqual(res_xz["status"], "INVALID_OUTPUT")
        self.assertEqual(res_xz["unknown_xz_count"], 1)

        # Special value error -> INVALID_OUTPUT
        vecs_sp = [_DummyVec(0x0000, 0xC000, "special_value")]
        res_sp = evaluate_posit_tleap_batch(vecs_sp, [{"product": 0x8000}], cfg)
        self.assertEqual(res_sp["status"], "INVALID_OUTPUT")
        self.assertEqual(res_sp["special_value_errors"], 1)

        # Finite functional mismatch -> FUNCTIONAL_FAIL
        res_fail = evaluate_posit_tleap_batch(vecs, [{"product": 0x4000}, act_pass[1]], cfg)
        self.assertEqual(res_fail["status"], "FUNCTIONAL_FAIL")


if __name__ == "__main__":
    unittest.main()
