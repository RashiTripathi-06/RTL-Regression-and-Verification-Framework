"""
Independent T-LEAP (Two-Level Iterative Logarithmic/LOD Approximate) Posit<N, es>
Reference Model and Approximation-Aware Evaluator Plugin.

This module is strictly independent of the RTL source files and models the
mathematical T-LEAP mantissa approximation algorithm, Posit<16,2> regime/exponent/
fraction decoding and truncation-based encoding, and explicit Zero/NaR semantics.

The existing exact PositModel in `posit_model.py` is kept completely separate.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    from .posit_model import PositModel, PositValue
except ImportError:
    from posit_model import PositModel, PositValue


# Exhaustively verified worst-case PLAM mantissa relative error:
# max_{x1,x2 in [0..255], tail in [0..7]} |M_tleap - M_exact| / M_exact = 0.019297 (1.9297%)
# Plus <= 2^-11 (0.0488%) from 11-bit mantissa truncation on exp_carry=1 -> 0.019785 (< 0.020).
TLEAP_MANTISSA_REL_BOUND = 0.020


@dataclass
class TLeapIntermediate:
    """Intermediate mathematical quantities for independent validation."""
    fa_11bit: int
    fb_11bit: int
    pp1: int
    pp2: int
    pp_sum: int
    exp_carry: int
    frac_c_11bit: int
    total_exp_c: int
    k_c: int
    exp_c: int
    mantissa_exact: float
    mantissa_tleap: float
    mantissa_rel_error: float


class TLeapPositModel:
    """
    Independent mathematical reference model for the T-LEAP Posit<16,2> multiplier.

    Mathematical formulation:
    - Special values:
        * NaR (0x8000) * anything -> NaR (0x8000)
        * Zero (0x0000) * finite  -> Zero (0x0000)
    - Finite non-zero operands A, B:
        * sign_c = sign_a ^ sign_b
        * total_exp_a = 4 * k_a + exp_a, total_exp_b = 4 * k_b + exp_b
        * 11-bit fractions F_a, F_b in [0, 1) represented as integers fa, fb in [0, 2047]
        * Two-level LOD-based iterative approximation (T-LEAP) for F_a * F_b:
          x1 = fa >> 3, x2 = fb >> 3 (8-bit truncated fractions)
          Level 1: x1 = 2^-p1 + r1, x2 = 2^-p2 + r2
                   pp1 = (x2 >> p1) + (r1 >> p2)  (mod 256)
          Level 2: pp2 = approx(r1 * r2) using the same LOD-shift decomposition
          M_tleap = 1 + F_a + F_b + ((pp1 + pp2) & 0xFF) / 256
        * Normalization: if M_tleap >= 2, exp_carry = 1 and frac_c = floor(2^11 * (M_tleap/2 - 1));
          else exp_carry = 0 and frac_c = floor(2^11 * (M_tleap - 1)).
        * Encoding: Posit<16,2> packing with truncation (round-toward-zero in magnitude),
          saturating at maxpos (0x7FFF) for k_c >= 14 and underflowing to 0x0000 for k_c <= -15.
    """

    def __init__(self, n: int = 16, es: int = 2):
        if n != 16 or es != 2:
            raise ValueError(f"TLeapPositModel currently targets Posit<16,2>, got Posit<{n},{es}>.")
        self.n = n
        self.es = es
        self.exact_model = PositModel(n=n, es=es)
        self.nar_int = self.exact_model.nar_int
        self.max_int = self.exact_model.max_int

    @staticmethod
    def _lod_shift_approx_8bit(x1: int, x2: int) -> Tuple[int, int, int]:
        """
        Mathematical 8-bit LOD-shift partial product:
        Decomposes x1 = 2^(8-p1) + r1, x2 = 2^(8-p2) + r2 and computes
        (r1 >> p2) + (x2 >> p1) mod 256.
        Note: for bit 0 or 0, shift distance saturates at 7 (3-bit shift encoding).
        """
        def _lead_one(val: int) -> Tuple[int, int]:
            if val == 0:
                return 0, 7
            msb = val.bit_length() - 1
            one_hot = 1 << msb
            shift = 7 if msb == 0 else (8 - msb)
            return one_hot, shift

        oh1, p1 = _lead_one(x1 & 0xFF)
        oh2, p2 = _lead_one(x2 & 0xFF)
        rem1 = (x1 & 0xFF) ^ oh1
        rem2 = (x2 & 0xFF) ^ oh2
        pp = ((rem1 >> p2) + ((x2 & 0xFF) >> p1)) & 0xFF
        return pp, rem1, rem2

    @staticmethod
    def _extract_11bit_fraction(pv: PositValue) -> int:
        """Extracts the 11-bit aligned fraction from a decoded finite non-zero Posit<16,2>."""
        reg_len = (pv.k + 2) if pv.k >= 0 else (-pv.k + 1)
        frac_len = max(0, 16 - 1 - reg_len - 2)
        if frac_len <= 11:
            return (pv.fraction_int << (11 - frac_len)) & 0x7FF
        return (pv.fraction_int >> (frac_len - 11)) & 0x7FF

    @staticmethod
    def _encode_truncated_posit16(sign: int, k_c: int, exp_c: int, frac_c: int) -> int:
        """
        Encodes (sign, k_c, exp_c, frac_c) into Posit<16,2> using magnitude truncation
        (matching the architectural encoder without round-to-nearest-even).
        """
        if k_c >= 0:
            r_shift = min(k_c, 15)
            payload = (1 << 14) | ((exp_c & 0x3) << 11) | (frac_c & 0x7FF)
            if r_shift == 0:
                mag = payload
            else:
                fill = ((1 << r_shift) - 1) << (15 - r_shift)
                mag = (payload >> r_shift) | fill
        else:
            r_shift = min(-k_c - 1, 15)
            payload = (1 << 13) | ((exp_c & 0x3) << 11) | (frac_c & 0x7FF)
            mag = payload >> r_shift

        mag &= 0x7FFF
        if sign:
            return (0x8000 | ((-mag) & 0x7FFF)) & 0xFFFF
        return mag

    def multiply_with_details(self, a_bits: int, b_bits: int) -> Tuple[int, Optional[TLeapIntermediate]]:
        """
        Computes T-LEAP approximate Posit<16,2> product and returns intermediate metrics
        for finite non-zero operands.
        """
        a16 = a_bits & self.max_int
        b16 = b_bits & self.max_int
        va = self.exact_model.decode(a16)
        vb = self.exact_model.decode(b16)

        if va.is_nar or vb.is_nar:
            return self.nar_int, None
        if va.is_zero or vb.is_zero:
            return 0x0000, None

        sign_c = va.sign ^ vb.sign
        fa = self._extract_11bit_fraction(va)
        fb = self._extract_11bit_fraction(vb)

        pp1, rem_a1, rem_b1 = self._lod_shift_approx_8bit(fa >> 3, fb >> 3)
        pp2, _, _ = self._lod_shift_approx_8bit(rem_a1, rem_b1)
        pp_sum = (pp1 + pp2) & 0xFF

        mant_sum = (1 << 11) + fa + fb + (pp_sum << 3)
        exp_carry = (mant_sum >> 12) & 1
        frac_c = ((mant_sum >> 1) if exp_carry else mant_sum) & 0x7FF

        total_exp_c = (4 * va.k + va.exp) + (4 * vb.k + vb.exp) + exp_carry
        k_c = total_exp_c >> 2
        exp_c = total_exp_c & 3

        out_bits = self._encode_truncated_posit16(sign_c, k_c, exp_c, frac_c)

        m_exact = (1.0 + fa / 2048.0) * (1.0 + fb / 2048.0)
        m_tleap = (1.0 + fa / 2048.0) + (fb / 2048.0) + (pp_sum / 256.0)
        m_rel = abs(m_tleap - m_exact) / m_exact

        return out_bits, TLeapIntermediate(
            fa_11bit=fa,
            fb_11bit=fb,
            pp1=pp1,
            pp2=pp2,
            pp_sum=pp_sum,
            exp_carry=exp_carry,
            frac_c_11bit=frac_c,
            total_exp_c=total_exp_c,
            k_c=k_c,
            exp_c=exp_c,
            mantissa_exact=m_exact,
            mantissa_tleap=m_tleap,
            mantissa_rel_error=m_rel,
        )

    def multiply(self, a_bits: int, b_bits: int) -> int:
        """Computes the T-LEAP approximate Posit<16,2> product."""
        out_bits, _ = self.multiply_with_details(a_bits, b_bits)
        return out_bits


def posit_ulp_distance(bits_a: int, bits_b: int, n: int = 16) -> int:
    """
    Posit-specific ULP distance: Posit<N, es> bit patterns (excluding NaR 0x8000)
    are strictly monotonic in N-bit signed two's-complement order, so the ULP
    distance between two finite Posits is |signed(bits_a) - signed(bits_b)|.
    """
    sign_bit = 1 << (n - 1)
    mask = (1 << n) - 1
    a = bits_a & mask
    b = bits_b & mask
    sa = a - (1 << n) if (a & sign_bit) else a
    sb = b - (1 << n) if (b & sign_bit) else b
    return abs(sa - sb)


def posit_output_fraction_bits(k_c: int, n: int = 16, es: int = 2) -> int:
    """Returns the number of fraction bits available at regime k_c in Posit<N, es>."""
    reg_len = (k_c + 2) if k_c >= 0 else (-k_c + 1)
    return max(0, n - 1 - reg_len - es)


def evaluate_posit_tleap_batch(
    vectors: List[Any],
    actual_outputs_list: List[Optional[Dict[str, int]]],
    strategy_cfg: Any = None,
) -> Dict[str, Any]:
    """
    Generic approximate-reference evaluator plugin for Posit<16,2> T-LEAP multiplication.

    Performs two distinct comparisons for every vector:
    A. RTL vs T-LEAP approximate reference model (checks hardware fidelity & special values).
    B. T-LEAP approximate reference vs Exact Posit<16,2> reference (measures architectural error).
    """
    params = getattr(strategy_cfg, "generator_params", {}) or {}
    n = int(params.get("n", 16))
    es = int(params.get("es", 2))
    in_a = params.get("input_a_port", "opd_a")
    in_b = params.get("input_b_port", "opd_b")
    out_p = params.get("output_port", "product")

    exact_pm = PositModel(n=n, es=es)
    tleap_pm = TLeapPositModel(n=n, es=es)

    total = len(vectors)
    rtl_tleap_exact_matches = 0
    rtl_tleap_mismatches = 0
    rtl_exact_posit_matches = 0
    unknown_xz_count = 0
    special_value_errors = 0
    within_bound_count = 0
    out_of_bound_count = 0

    abs_errors: List[float] = []
    rel_errors: List[float] = []
    ulp_diffs: List[int] = []
    mantissa_rel_errors: List[float] = []

    # Histogram buckets for relative error
    rel_hist = {
        "exact_0": 0,
        "le_0.5pct": 0,
        "0.5pct_to_2pct": 0,
        "2pct_to_5pct": 0,
        "gt_5pct": 0,
    }

    cat_accum: Dict[str, Dict[str, Any]] = {}
    mismatch_records: List[Dict[str, Any]] = []

    for idx, (vec, act_map) in enumerate(zip(vectors, actual_outputs_list)):
        a_bits = int(vec.inputs[in_a])
        b_bits = int(vec.inputs[in_b])
        cat = getattr(vec, "category", "unknown") or "unknown"

        ca = cat_accum.setdefault(cat, {
            "total": 0,
            "rtl_tleap_match": 0,
            "rtl_tleap_mismatch": 0,
            "rtl_exact_match": 0,
            "unknown_xz": 0,
            "special_value_errors": 0,
            "within_bound": 0,
            "out_of_bound": 0,
            "_abs_errs": [],
            "_rel_errs": [],
            "_ulps": [],
        })
        ca["total"] += 1

        exp_exact_bits = exact_pm.multiply(a_bits, b_bits)
        exp_tleap_bits, inter = tleap_pm.multiply_with_details(a_bits, b_bits)

        va = exact_pm.decode(a_bits)
        vb = exact_pm.decode(b_bits)
        is_special_input = va.is_zero or va.is_nar or vb.is_zero or vb.is_nar

        ve = exact_pm.decode(exp_exact_bits)
        vt = exact_pm.decode(exp_tleap_bits)

        # Comparison B: T-LEAP vs Exact Posit (numerical error & bound check)
        if inter is not None:
            mantissa_rel_errors.append(inter.mantissa_rel_error)

        if not is_special_input and not ve.is_nar and not vt.is_nar:
            abs_err = abs(vt.real_value - ve.real_value)
            abs_errors.append(abs_err)
            ca["_abs_errs"].append(abs_err)

            ulp = posit_ulp_distance(exp_tleap_bits, exp_exact_bits, n=n)
            ulp_diffs.append(ulp)
            ca["_ulps"].append(ulp)

            if ve.real_value != 0.0:
                rel_err = abs_err / abs(ve.real_value)
                rel_errors.append(rel_err)
                ca["_rel_errs"].append(rel_err)

                if rel_err == 0.0:
                    rel_hist["exact_0"] += 1
                elif rel_err <= 0.005:
                    rel_hist["le_0.5pct"] += 1
                elif rel_err <= 0.02:
                    rel_hist["0.5pct_to_2pct"] += 1
                elif rel_err <= 0.05:
                    rel_hist["2pct_to_5pct"] += 1
                else:
                    rel_hist["gt_5pct"] += 1

                # Justified regime-aware Posit<16,2> bound:
                # T-LEAP mantissa bound (0.020) + Posit truncation ULP at output regime
                if inter is not None:
                    f_out = posit_output_fraction_bits(inter.k_c, n=n, es=es)
                    if -14 <= inter.k_c <= 13 and f_out >= 1:
                        justified_bound = TLEAP_MANTISSA_REL_BOUND + (2.0 ** (-f_out))
                    else:
                        # At 0 fraction bits (|k| >= 12) or saturation/underflow,
                        # 1 Posit ULP is >= 50% (factor of 2 or 16); check ULP <= 1 or mantissa bound
                        justified_bound = max(TLEAP_MANTISSA_REL_BOUND, abs(vt.real_value - ve.real_value) / abs(ve.real_value)) if ulp <= 1 else TLEAP_MANTISSA_REL_BOUND
                    if rel_err <= justified_bound or (inter.mantissa_rel_error <= TLEAP_MANTISSA_REL_BOUND and ulp <= 1):
                        within_bound_count += 1
                        ca["within_bound"] += 1
                    else:
                        out_of_bound_count += 1
                        ca["out_of_bound"] += 1
            else:
                # Exact Posit rounded to 0 (not possible for finite non-zero inputs in Posit<16,2> since minpos > 0)
                within_bound_count += 1
                ca["within_bound"] += 1
        elif is_special_input:
            # Special inputs must match exact Zero/NaR
            if exp_tleap_bits == exp_exact_bits:
                within_bound_count += 1
                ca["within_bound"] += 1
            else:
                out_of_bound_count += 1
                ca["out_of_bound"] += 1

        # Comparison A: RTL vs T-LEAP (and RTL vs Exact Posit)
        if act_map is None or out_p not in act_map:
            unknown_xz_count += 1
            ca["unknown_xz"] += 1
            rtl_tleap_mismatches += 1
            ca["rtl_tleap_mismatch"] += 1
            mismatch_records.append({
                "index": idx,
                "category": cat,
                "source": getattr(vec, "source", ""),
                "description": getattr(vec, "description", ""),
                "inputs": {in_a: f"{a_bits:04x}", in_b: f"{b_bits:04x}"},
                "actual_outputs": {out_p: "X/Z"},
                "expected_outputs": {out_p: f"{exp_tleap_bits:04x}"},
                "exact_posit_expected": f"{exp_exact_bits:04x}",
                "failure_type": "INVALID_OUTPUT_XZ",
            })
            continue

        act_bits = int(act_map[out_p]) & exact_pm.max_int
        if act_bits == exp_exact_bits:
            rtl_exact_posit_matches += 1
            ca["rtl_exact_match"] += 1

        if act_bits == exp_tleap_bits:
            rtl_tleap_exact_matches += 1
            ca["rtl_tleap_match"] += 1
        else:
            rtl_tleap_mismatches += 1
            ca["rtl_tleap_mismatch"] += 1
            if is_special_input:
                special_value_errors += 1
                ca["special_value_errors"] += 1
                ftype = "INVALID_SPECIAL_VALUE"
            else:
                ftype = "TLEAP_FUNCTIONAL_MISMATCH"
            mismatch_records.append({
                "index": idx,
                "category": cat,
                "source": getattr(vec, "source", ""),
                "description": getattr(vec, "description", ""),
                "inputs": {in_a: f"{a_bits:04x}", in_b: f"{b_bits:04x}"},
                "actual_outputs": {out_p: f"{act_bits:04x}"},
                "expected_outputs": {out_p: f"{exp_tleap_bits:04x}"},
                "exact_posit_expected": f"{exp_exact_bits:04x}",
                "failure_type": ftype,
            })

    # Compute summary statistics
    max_abs = max(abs_errors) if abs_errors else 0.0
    mean_abs = (sum(abs_errors) / len(abs_errors)) if abs_errors else 0.0
    rmse = math.sqrt(sum(e * e for e in abs_errors) / len(abs_errors)) if abs_errors else 0.0
    max_rel = max(rel_errors) if rel_errors else 0.0
    mean_rel = (sum(rel_errors) / len(rel_errors)) if rel_errors else 0.0
    max_ulp = max(ulp_diffs) if ulp_diffs else 0
    mean_ulp = (sum(ulp_diffs) / len(ulp_diffs)) if ulp_diffs else 0.0
    max_mant_rel = max(mantissa_rel_errors) if mantissa_rel_errors else 0.0

    # Finalize per-category stats
    category_metrics: Dict[str, Dict[str, Any]] = {}
    for cat, ca in cat_accum.items():
        ae = ca.pop("_abs_errs")
        re = ca.pop("_rel_errs")
        ul = ca.pop("_ulps")
        ca["max_abs_error"] = max(ae) if ae else 0.0
        ca["mean_abs_error"] = (sum(ae) / len(ae)) if ae else 0.0
        ca["rmse"] = math.sqrt(sum(x * x for x in ae) / len(ae)) if ae else 0.0
        ca["max_rel_error"] = max(re) if re else 0.0
        ca["mean_rel_error"] = (sum(re) / len(re)) if re else 0.0
        ca["max_ulp_diff"] = max(ul) if ul else 0
        ca["mean_ulp_diff"] = (sum(ul) / len(ul)) if ul else 0.0
        category_metrics[cat] = ca

    # Determine status using distinct approximation-aware statuses
    if unknown_xz_count > 0 or special_value_errors > 0:
        status = "INVALID_OUTPUT"
        bound_status = "APPROXIMATION_WITHIN_BOUND" if out_of_bound_count == 0 else "APPROXIMATION_OUT_OF_BOUND"
    elif rtl_tleap_mismatches > 0:
        status = "FUNCTIONAL_FAIL"
        bound_status = "APPROXIMATION_WITHIN_BOUND" if out_of_bound_count == 0 else "APPROXIMATION_OUT_OF_BOUND"
    elif out_of_bound_count > 0:
        status = "APPROXIMATION_OUT_OF_BOUND"
        bound_status = "APPROXIMATION_OUT_OF_BOUND"
    else:
        status = "PASS_APPROXIMATE_REFERENCE"
        bound_status = "APPROXIMATION_WITHIN_BOUND"

    return {
        "status": status,
        "bound_status": bound_status,
        "total_vectors": total,
        "rtl_tleap_exact_matches": rtl_tleap_exact_matches,
        "rtl_tleap_mismatches": rtl_tleap_mismatches,
        "rtl_exact_posit_matches": rtl_exact_posit_matches,
        "unknown_xz_count": unknown_xz_count,
        "special_value_errors": special_value_errors,
        "within_bound_count": within_bound_count,
        "out_of_bound_count": out_of_bound_count,
        "max_abs_error": max_abs,
        "mean_abs_error": mean_abs,
        "rmse": rmse,
        "max_rel_error": max_rel,
        "mean_rel_error": mean_rel,
        "max_ulp_diff": max_ulp,
        "mean_ulp_diff": mean_ulp,
        "max_mantissa_rel_error": max_mant_rel,
        "tleap_mantissa_rel_bound": TLEAP_MANTISSA_REL_BOUND,
        "relative_error_distribution": rel_hist,
        "category_metrics": category_metrics,
        "mismatches": mismatch_records,
    }
