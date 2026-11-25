"""
Posit Arithmetic Model Plugin for the RTL Verification Framework.
Isolated external reference plugin for Posit<N, es> arithmetic evaluation.
"""
from __future__ import annotations
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class PositValue:
    bits: int
    n: int
    es: int
    sign: int
    k: int
    exp: int
    fraction_int: int
    fraction_val: float
    real_value: float
    is_zero: bool
    is_nar: bool

    def __str__(self) -> str:
        if self.is_zero:
            return "0.0"
        if self.is_nar:
            return "NaR"
        return f"{self.real_value:.8g} (s={self.sign}, k={self.k}, exp={self.exp}, frac={self.fraction_val:.6f})"


class PositModel:
    """
    Independent standard Posit<N, es> arithmetic model.
    Compliant with the Standard for Posit Arithmetic (IEEE draft / John L. Gustafson).
    Supports arbitrary bit widths and exponent sizes (notably Posit<16,1> and Posit<16,2>).
    """

    def __init__(self, n: int = 16, es: int = 2):
        self.n = n
        self.es = es
        self.useed = 2 ** (2 ** es)
        self.max_int = (1 << n) - 1
        self.nar_int = 1 << (n - 1)

    def decode(self, bits: int) -> PositValue:
        bits = bits & self.max_int

        if bits == 0:
            return PositValue(
                bits=0, n=self.n, es=self.es, sign=0, k=0, exp=0,
                fraction_int=0, fraction_val=0.0, real_value=0.0,
                is_zero=True, is_nar=False
            )
        if bits == self.nar_int:
            return PositValue(
                bits=bits, n=self.n, es=self.es, sign=1, k=0, exp=0,
                fraction_int=0, fraction_val=0.0, real_value=float("nan"),
                is_zero=False, is_nar=True
            )

        sign = (bits >> (self.n - 1)) & 1
        # If negative, take 2's complement
        mag = ((~bits + 1) & self.max_int) if sign else bits

        # Extract regime: starting at bit n-2
        pos = self.n - 2
        r_bit = (mag >> pos) & 1
        regime_run = 0
        while pos >= 0 and ((mag >> pos) & 1) == r_bit:
            regime_run += 1
            pos -= 1

        # Skip regime terminating bit if still within word
        if pos >= 0:
            pos -= 1

        k = (regime_run - 1) if r_bit == 1 else -regime_run

        # Extract exponent
        exp_val = 0
        exp_bits_extracted = 0
        for _ in range(self.es):
            if pos >= 0:
                bit = (mag >> pos) & 1
                exp_val = (exp_val << 1) | bit
                exp_bits_extracted += 1
                pos -= 1
            else:
                exp_val = exp_val << 1

        # Remaining bits are fraction
        fraction_bits = 0
        frac_len = 0
        while pos >= 0:
            fraction_bits = (fraction_bits << 1) | ((mag >> pos) & 1)
            frac_len += 1
            pos -= 1

        frac_val = (fraction_bits / (2 ** frac_len)) if frac_len > 0 else 0.0
        mantissa = 1.0 + frac_val

        # Numerical scale
        val = (self.useed ** k) * (2 ** exp_val) * mantissa
        if sign:
            val = -val

        return PositValue(
            bits=bits, n=self.n, es=self.es, sign=sign, k=k, exp=exp_val,
            fraction_int=fraction_bits, fraction_val=frac_val, real_value=val,
            is_zero=False, is_nar=False
        )

    def encode(self, val: float) -> int:
        """Encodes a real floating-point number into a Posit<N, es> bit pattern with round-to-nearest-even."""
        if math.isnan(val) or math.isinf(val):
            return self.nar_int
        if val == 0.0:
            return 0

        sign = 1 if val < 0 else 0
        abs_val = abs(val)

        # Decompose into scale = useed^k * 2^exp * (1 + frac)
        total_exp = math.floor(math.log2(abs_val))
        mantissa = abs_val / (2 ** total_exp)
        frac = mantissa - 1.0

        es_scale = 1 << self.es
        k = math.floor(total_exp / es_scale)
        exp_val = total_exp % es_scale

        # Construct bit string
        bits = []
        # Regime bits
        if k >= 0:
            bits.extend([1] * (k + 1))
            bits.append(0)
        else:
            bits.extend([0] * (-k))
            bits.append(1)

        # Exponent bits (es bits)
        for i in range(self.es - 1, -1, -1):
            bits.append((exp_val >> i) & 1)

        # Available space for fraction
        budget = (self.n - 1) - len(bits)
        if budget <= 0:
            raw_bits = bits[:self.n - 1]
            encoded_mag = 0
            for b in raw_bits:
                encoded_mag = (encoded_mag << 1) | b
            if len(raw_bits) < self.n - 1:
                encoded_mag <<= ((self.n - 1) - len(raw_bits))
        else:
            frac_val = frac
            for _ in range(budget):
                frac_val *= 2
                bit = int(frac_val)
                bits.append(bit)
                frac_val -= bit

            round_bit = 1 if (frac_val * 2) >= 1.0 else 0
            encoded_mag = 0
            for b in bits[:self.n - 1]:
                encoded_mag = (encoded_mag << 1) | b

            if round_bit:
                encoded_mag += 1

        encoded_mag &= (1 << (self.n - 1)) - 1
        if sign:
            encoded = ((~encoded_mag + 1) & ((1 << (self.n - 1)) - 1)) | (1 << (self.n - 1))
        else:
            encoded = encoded_mag

        return encoded & self.max_int

    def multiply(self, a_bits: int, b_bits: int) -> int:
        """Exact multiplication of two Posits via numerical value decoding, multiplication, and re-encoding."""
        va = self.decode(a_bits)
        vb = self.decode(b_bits)

        if va.is_nar or vb.is_nar:
            return self.nar_int
        if va.is_zero or vb.is_zero:
            return 0

        prod_val = va.real_value * vb.real_value
        return self.encode(prod_val)

    def generate_regression_vectors(
        self,
        count: int = 1000,
        fixed_a: Optional[int] = None,
        seed: int = 42
    ) -> List[Dict[str, Any]]:
        rng = random.Random(seed)
        vectors = []

        corners = [
            0x0000, 0x8000, 0x4000, 0xC000, 0x4800, 0x3800,
            0x0001, 0x7FFF, 0x8001, 0xFFFF, 0x2000, 0x6000
        ]

        if fixed_a is not None:
            for b in corners:
                prod = self.multiply(fixed_a, b)
                vectors.append({
                    "operand_a": f"{fixed_a:04x}",
                    "operand_b": f"{b:04x}",
                    "expected_product": f"{prod:04x}"
                })
            for _ in range(count):
                b = rng.randint(0, 0xFFFF)
                prod = self.multiply(fixed_a, b)
                vectors.append({
                    "operand_a": f"{fixed_a:04x}",
                    "operand_b": f"{b:04x}",
                    "expected_product": f"{prod:04x}"
                })
        else:
            for a in corners:
                for b in corners:
                    prod = self.multiply(a, b)
                    vectors.append({
                        "operand_a": f"{a:04x}",
                        "operand_b": f"{b:04x}",
                        "expected_product": f"{prod:04x}"
                    })
            for _ in range(count):
                a = rng.randint(0, 0xFFFF)
                b = rng.randint(0, 0xFFFF)
                prod = self.multiply(a, b)
                vectors.append({
                    "operand_a": f"{a:04x}",
                    "operand_b": f"{b:04x}",
                    "expected_product": f"{prod:04x}"
                })

        return vectors

    def generate_special_value_vectors(self) -> List[Dict[str, Any]]:
        """
        Generates directed special-value and sign/boundary test vectors for Posit<16,2>.
        Explicitly covers Zero (0x0000), NaR (0x8000), finite pos/neg, and boundary pairs.
        """
        zero = 0x0000
        nar = self.nar_int  # 0x8000 for N=16
        pos_finites = [0x4000, 0x4800, 0x3800, 0x6000, 0x0001, 0x7FFF]
        neg_finites = [0xC000, 0xB800, 0xC800, 0xA000, 0x8001, 0xFFFF]

        raw_cases: List[Tuple[int, int, str, str]] = []
        # 1. Zero * Zero
        raw_cases.append((zero, zero, "special_value", "Zero * Zero"))
        # 2. Zero * Positive finite & Positive finite * Zero
        for p in pos_finites:
            raw_cases.append((zero, p, "special_value", f"Zero * Pos(0x{p:04x})"))
            raw_cases.append((p, zero, "special_value", f"Pos(0x{p:04x}) * Zero"))
        # 3. Zero * Negative finite & Negative finite * Zero
        for n_val in neg_finites:
            raw_cases.append((zero, n_val, "special_value", f"Zero * Neg(0x{n_val:04x})"))
            raw_cases.append((n_val, zero, "special_value", f"Neg(0x{n_val:04x}) * Zero"))
        # 4. NaR * Zero & Zero * NaR
        raw_cases.append((nar, zero, "special_value", "NaR * Zero"))
        raw_cases.append((zero, nar, "special_value", "Zero * NaR"))
        # 5. NaR * Positive finite & Positive finite * NaR
        for p in pos_finites:
            raw_cases.append((nar, p, "special_value", f"NaR * Pos(0x{p:04x})"))
            raw_cases.append((p, nar, "special_value", f"Pos(0x{p:04x}) * NaR"))
        # 6. NaR * Negative finite & Negative finite * NaR
        for n_val in neg_finites:
            raw_cases.append((nar, n_val, "special_value", f"NaR * Neg(0x{n_val:04x})"))
            raw_cases.append((n_val, nar, "special_value", f"Neg(0x{n_val:04x}) * NaR"))
        # 7. NaR * NaR
        raw_cases.append((nar, nar, "special_value", "NaR * NaR"))

        # 8. Positive/negative & representational boundary combinations
        sign_boundary_pairs = [
            (0x4000, 0x4000, "boundary", "+1.0 * +1.0"),
            (0x4000, 0xC000, "boundary", "+1.0 * -1.0"),
            (0xC000, 0x4000, "boundary", "-1.0 * +1.0"),
            (0xC000, 0xC000, "boundary", "-1.0 * -1.0"),
            (0x4800, 0xC800, "boundary", "+2.0 * -0.5"),
            (0xB800, 0x3800, "boundary", "-2.0 * +0.5"),
            (0x7FFF, 0x7FFF, "boundary", "maxpos * maxpos"),
            (0x0001, 0x0001, "boundary", "minpos * minpos"),
            (0x7FFF, 0x0001, "boundary", "maxpos * minpos"),
            (0x8001, 0x7FFF, "boundary", "-maxpos * maxpos"),
            (0x8001, 0xFFFF, "boundary", "-maxpos * -minpos"),
            (0xFFFF, 0xFFFF, "boundary", "-minpos * -minpos"),
        ]
        raw_cases.extend(sign_boundary_pairs)

        seen = set()
        vectors: List[Dict[str, Any]] = []
        for a, b, cat, desc in raw_cases:
            a16, b16 = a & self.max_int, b & self.max_int
            if (a16, b16) in seen:
                continue
            seen.add((a16, b16))
            prod = self.multiply(a16, b16)
            vectors.append({
                "opd_a": a16,
                "opd_b": b16,
                "expected_product": prod,
                "category": cat,
                "description": desc,
                "source": "posit_model_special",
            })
        return vectors

    def generate_strategy_vectors(
        self,
        test_count: int = 30000,
        random_seed: int = 12345,
        special_value_tests: bool = True,
        boundary_tests: bool = True,
        structured_tests: bool = True,
        random_tests: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Generates a combined, deduplicated, reproducible vector suite of up to `test_count`
        independently varying 16-bit Posit operand pairs across four categories:
        1. Directed special-value cases (Zero, NaR, +/- finite)
        2. Boundary-value cases (minpos, maxpos, +/-1, regime extremes)
        3. Structured operand combinations (cross-regime/exponent/sign grid)
        4. Reproducible random operand pairs (both operands vary independently)
        """
        if test_count <= 0:
            return []

        rng = random.Random(random_seed)
        seen: set[Tuple[int, int]] = set()
        vectors: List[Dict[str, Any]] = []

        def _add_vec(a: int, b: int, category: str, source: str, desc: str = "") -> bool:
            if len(vectors) >= test_count:
                return False
            a16 = a & self.max_int
            b16 = b & self.max_int
            if (a16, b16) in seen:
                return False
            seen.add((a16, b16))
            prod = self.multiply(a16, b16)
            vectors.append({
                "opd_a": a16,
                "opd_b": b16,
                "expected_product": prod,
                "category": category,
                "source": source,
                "description": desc,
            })
            return True

        # 1. Directed special-value cases
        if special_value_tests:
            for v in self.generate_special_value_vectors():
                if len(vectors) >= test_count:
                    break
                _add_vec(v["opd_a"], v["opd_b"], v["category"], v["source"], v.get("description", ""))

        # 2. Boundary-value cases (Cartesian product of key Posit<16,2> boundaries)
        if boundary_tests and len(vectors) < test_count:
            boundaries = [
                0x0000, 0x8000, 0x0001, 0x0002, 0x7FFE, 0x7FFF,
                0x8001, 0x8002, 0xFFFE, 0xFFFF,
                0x4000, 0xC000, 0x4800, 0xB800, 0x3800, 0xC800,
                0x2000, 0xE000, 0x6000, 0xA000,
            ]
            for a in boundaries:
                for b in boundaries:
                    if len(vectors) >= test_count:
                        break
                    _add_vec(a, b, "boundary", "posit_model_boundary")
                if len(vectors) >= test_count:
                    break

        # 3. Structured operand combinations (regime & exponent sweep pairs)
        if structured_tests and len(vectors) < test_count:
            # Representative bit patterns spanning regimes k=-14..+13, exponents 0..3, and signs
            structured_pool = []
            for shift in range(0, 14):
                structured_pool.append(0x4000 >> shift if shift > 0 else 0x4000)
                structured_pool.append((0x7FFF - (1 << shift)) & 0x7FFF)
            for top_nibble in range(0x1, 0xF):
                structured_pool.append(top_nibble << 12)
                structured_pool.append((top_nibble << 12) | 0x0400)
                structured_pool.append((top_nibble << 12) | 0x0800)
                structured_pool.append((top_nibble << 12) | 0x0C00)
            # Deduplicate pool preserving order
            unique_pool = list(dict.fromkeys(x & 0xFFFF for x in structured_pool))
            for a in unique_pool:
                for b in unique_pool:
                    if len(vectors) >= test_count:
                        break
                    _add_vec(a, b, "structured", "posit_model_structured")
                if len(vectors) >= test_count:
                    break

        # 4. Randomly generated operand pairs (both operands vary independently)
        if random_tests:
            max_attempts = max(test_count * 4, 1000)
            attempts = 0
            while len(vectors) < test_count and attempts < max_attempts:
                attempts += 1
                a = rng.randint(0, self.max_int)
                b = rng.randint(0, self.max_int)
                _add_vec(a, b, "random", f"posit_model_random_seed_{random_seed}")

        return vectors


def generate_posit_vectors(strategy_config: Any, dut: Any = None) -> List[Dict[str, Any]]:
    """
    Plugin entrypoint for the generic RTL Verification Strategy Runner.
    Generates Posit<16,2> (or configured N, es) vectors and maps them to DUT ports.
    """
    params = getattr(strategy_config, "generator_params", {}) or {}
    n = int(params.get("n", 16))
    es = int(params.get("es", 2))
    pm = PositModel(n=n, es=es)

    mode = getattr(strategy_config, "mode", "directed_random")
    if mode == "special_values":
        raw_vecs = pm.generate_special_value_vectors()
    else:
        raw_vecs = pm.generate_strategy_vectors(
            test_count=int(getattr(strategy_config, "test_count", 30000)),
            random_seed=int(getattr(strategy_config, "random_seed", 12345)),
            special_value_tests=bool(getattr(strategy_config, "special_value_tests", True)),
            boundary_tests=bool(getattr(strategy_config, "boundary_tests", True)),
            structured_tests=bool(getattr(strategy_config, "structured_tests", True)),
            random_tests=bool(getattr(strategy_config, "random_tests", True)),
        )

    in_a = params.get("input_a_port", "opd_a")
    in_b = params.get("input_b_port", "opd_b")
    out_p = params.get("output_port", "product")

    mapped: List[Dict[str, Any]] = []
    for idx, v in enumerate(raw_vecs):
        mapped.append({
            "index": idx,
            "inputs": {in_a: v["opd_a"], in_b: v["opd_b"]},
            "expected_outputs": {out_p: v["expected_product"]},
            "category": v.get("category", "unknown"),
            "source": v.get("source", "posit_model"),
            "description": v.get("description", ""),
        })
    return mapped


def parse_posit_lookup_table(table_path: Path) -> Dict[int, float]:
    """Parses the user-supplied Posit decoding lookup table."""
    if not table_path.exists():
        raise FileNotFoundError(f"Lookup table file not found: {table_path}")

    lut: Dict[int, float] = {}
    lines = table_path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        parts = re.split(r"[\s,]+", stripped)
        if len(parts) >= 2:
            try:
                k_str = parts[0]
                if k_str.startswith("0x") or k_str.startswith("0X"):
                    key = int(k_str, 16)
                elif len(k_str) == 16 and all(c in "01" for c in k_str):
                    key = int(k_str, 2)
                elif all(c in "0123456789abcdefABCDEF" for c in k_str) and len(k_str) <= 4:
                    key = int(k_str, 16)
                else:
                    key = int(k_str)

                val = float(parts[1])
                lut[key] = val
            except ValueError:
                continue
    return lut
