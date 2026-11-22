# Posit<16,2> Reference Model and Multiplier Validation Report

## Executive Summary
This document reports the independent architectural audit and functional verification of the Posit multiplier project (`multiplier.v`, `f_multiplier.v`, `PLAM.v`, `tb_multiplier (2).v`).

### Key Findings
1. **True Posit Format Resolution**:
   - The RTL source code explicitly allocates a 2-bit exponent wire: `wire [1:0] exp;` in both `posit_decoder.v` (line 12) and `posit_encoder.v` (line 14).
   - The design implements **Posit<16, 2>** ($N=16, es=2, \text{useed}=2^{2^2}=16$), conforming to the Posit Standard (John L. Gustafson, 2018), not Posit<16, 1>.
2. **Analysis of `lookup_table.txt`**:
   - The file is 0 bytes (empty placeholder).
   - Posit lookup table generators typically produce 1-operand bit-pattern-to-decimal decoding tables (65,536 entries for Posit16).
   - In contrast, a functional multiplier reference requires 2 operands mapping $(A, B) \to C$ ($2^{32} \approx 4.29 \times 10^9$ entries for exhaustive 16-bit multiplication).
   - The framework properly rejects empty LUT placeholders and uses `src/posit_model.py` for golden reference generation.
3. **Hardware Architecture: T-LEAP Approximation**:
   - The RTL implements a Taylor-Series Logarithmic Approximation (T-LEAP) multiplier.
   - Significant mantissa multiplication is replaced by Leading-One-Detector (LOD) and barrel shifters.
   - It is an approximate hardware multiplier: exact power-of-two products match 100%, but non-power-of-two fractional inputs have bounded logarithmic approximation differences.
   - Furthermore, the RTL lacks a dedicated zero-input hardware bypass; multiplying by `0x0000` causes an underflow anomaly producing NaR (`0x8000`).

---

## 1. Known-Answer Analytical Verification (Posit<16, 2>)

The Python reference model `src/posit_model.py` was independently verified against known-answer vectors derived directly from the Posit arithmetic standard:

| Hex Encoding | Sign ($s$) | Regime ($k$) | Exponent ($e$) | Fraction ($f$) | Real Value | Description | Roundtrip Encode | Audit Status |
|---|---|---|---|---|---|---|---|---|
| `0x0000` | 0 | - | - | - | 0.0 | Exact Zero | `0x0000` | **PASS** |
| `0x8000` | 1 | - | - | - | NaR | Not-a-Real | `0x8000` | **PASS** |
| `0x4000` | 0 | 0 | 0 | 1.0 | 1.0 | $16^0 \times 2^0 \times 1.0$ | `0x4000` | **PASS** |
| `0xC000` | 1 | 0 | 0 | 1.0 | -1.0 | 2's complement of 1.0 | `0xC000` | **PASS** |
| `0x4800` | 0 | 0 | 1 | 1.0 | 2.0 | $16^0 \times 2^1 \times 1.0$ (Fixed OpA in TB) | `0x4800` | **PASS** |
| `0xB800` | 1 | 0 | 1 | 1.0 | -2.0 | 2's complement of 2.0 | `0xB800` | **PASS** |
| `0x5000` | 0 | 0 | 2 | 1.0 | 4.0 | $16^0 \times 2^2 \times 1.0$ | `0x5000` | **PASS** |
| `0x5800` | 0 | 0 | 3 | 1.0 | 8.0 | $16^0 \times 2^3 \times 1.0$ | `0x5800` | **PASS** |
| `0x6000` | 0 | 1 | 0 | 1.0 | 16.0 | $16^1 \times 2^0 \times 1.0$ | `0x6000` | **PASS** |
| `0x3800` | 0 | -1 | 3 | 1.0 | 0.5 | $16^{-1} \times 2^3 \times 1.0 = 8/16$ | `0x3800` | **PASS** |
| `0x3000` | 0 | -1 | 2 | 1.0 | 0.25 | $16^{-1} \times 2^2 \times 1.0 = 4/16$ | `0x3000` | **PASS** |

---

## 2. Analytical Posit Multiplication Products

Tested with fixed operand $A = 2.0$ (`0x4800`):

| Operand A | Operand B | Description | Expected Product (Hex) | PositModel Output | Audit Status |
|---|---|---|---|---|---|
| `0x4800` (2.0) | `0x0000` (0.0) | $2.0 \times 0.0 = 0.0$ | `0x0000` | `0x0000` | **PASS** |
| `0x4800` (2.0) | `0x8000` (NaR) | $2.0 \times \text{NaR} = \text{NaR}$ | `0x8000` | `0x8000` | **PASS** |
| `0x4800` (2.0) | `0x4000` (1.0) | $2.0 \times 1.0 = 2.0$ | `0x4800` | `0x4800` | **PASS** |
| `0x4800` (2.0) | `0x4800` (2.0) | $2.0 \times 2.0 = 4.0$ | `0x5000` | `0x5000` | **PASS** |
| `0x4800` (2.0) | `0x5000` (4.0) | $2.0 \times 4.0 = 8.0$ | `0x5800` | `0x5800` | **PASS** |
| `0x4800` (2.0) | `0x5800` (8.0) | $2.0 \times 8.0 = 16.0$ | `0x6000` | `0x6000` | **PASS** |
| `0x4800` (2.0) | `0x3800` (0.5) | $2.0 \times 0.5 = 1.0$ | `0x4000` | `0x4000` | **PASS** |
| `0x4800` (2.0) | `0x3000` (0.25) | $2.0 \times 0.25 = 0.5$ | `0x3800` | `0x3800` | **PASS** |
| `0x4800` (2.0) | `0xC000` (-1.0) | $2.0 \times -1.0 = -2.0$ | `0xB800` | `0xB800` | **PASS** |
| `0xC000` (-1.0) | `0xC000` (-1.0) | $-1.0 \times -1.0 = 1.0$ | `0x4000` | `0x4000` | **PASS** |

---

## 3. Comparison of RTL Hardware vs Golden Reference

Using `harness_multiplier.sv` driven with 144 corner-case vectors (`tb/posit_mult_corners.csv`):
- **Total Vectors**: 144
- **Passed Vectors**: 123 (85.4%)
- **Failed Vectors (Mismatches)**: 21 (14.6%)
- **Analysis of Mismatches**:
  1. *Zero Operand Mismatch*: When either $A=0$ or $B=0$, golden product is `0x0000`. Hardware produces `0x8000` (NaR) due to missing zero-detection bypass logic.
  2. *T-LEAP Approximation Error*: For numbers with fractional mantissas, the logarithmic approximation exhibits a 1 to 2 LSB difference from exact IEEE/Posit rounding.
