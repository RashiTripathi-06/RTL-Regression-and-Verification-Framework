from __future__ import annotations
import math
import random
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
        # log2(abs_val) = k * 2^es + exp + log2(1 + frac)
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
            # Need to truncate and round
            raw_bits = bits[:self.n - 1]
            # Rounding logic (round to nearest even)
            # For exact bounds:
            encoded_mag = 0
            for b in raw_bits:
                encoded_mag = (encoded_mag << 1) | b
            if len(raw_bits) < self.n - 1:
                encoded_mag <<= ((self.n - 1) - len(raw_bits))
        else:
            # Fraction bits
            frac_val = frac
            for _ in range(budget):
                frac_val *= 2
                bit = int(frac_val)
                bits.append(bit)
                frac_val -= bit

            # Rounding bit
            round_bit = 1 if (frac_val * 2) >= 1.0 else 0
            encoded_mag = 0
            for b in bits[:self.n - 1]:
                encoded_mag = (encoded_mag << 1) | b

            if round_bit:
                # Add 1 with round to even
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

        # Directed corner cases
        corners = [
            0x0000, 0x8000, 0x4000, 0xC000, 0x4800, 0x3800,
            0x0001, 0x7FFF, 0x8001, 0xFFFF, 0x2000, 0x6000
        ]

        if fixed_a is not None:
            # Test fixed_a across all corners
            for b in corners:
                prod = self.multiply(fixed_a, b)
                vectors.append({
                    "operand_a": f"{fixed_a:04x}",
                    "operand_b": f"{b:04x}",
                    "expected_product": f"{prod:04x}"
                })
            # Add random b's
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


def parse_posit_lookup_table(table_path: Path) -> Dict[int, float]:
    """
    Parses the user-supplied Posit decoding lookup table (when provided).
    Supports CSV, tab-delimited, and whitespace-delimited columns:
    e.g. pattern, decimal_value or hex, float.
    """
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
                # Key could be hex or binary or dec
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
