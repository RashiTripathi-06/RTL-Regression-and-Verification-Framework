# Path B: Independent Golden-Reference Verification Report

## 1. Overview
Path B bypasses researcher-provided testbenches and directly synthesizes an isolated verification harness around the target DUT. It parses independent reference files (CSV, MEM, HEX, JSON) or drives inputs against a Python reference model, recording vector-by-vector comparisons.

### Machine-Readable Status Definitions
- `reference_verification_status`:
  - `PASS_REFERENCE_VERIFIED`: 100% of golden reference vectors matched hardware outputs within specified policy bounds.
  - `FAIL_REFERENCE`: One or more vectors mismatched between DUT and reference model.
  - `NOT_VERIFIED`: No reference model or data file provided.

---

## 2. Generic ALU Path B Demonstration (`alu_core` with `golden_alu.csv`)

### Verification Configuration
- **DUT**: `alu_core` (`examples/generic_alu/rtl/alu_core.v`)
- **Reference File**: `examples/generic_alu/ref/golden_alu.csv`
- **Format**: CSV (radix: Hexadecimal)
- **Input Mappings**: `operand_a` -> `a`, `operand_b` -> `b`, `operation` -> `opcode`
- **Output Mappings**: `expected_result` -> `result`, `expected_zero` -> `zero_flag`, `expected_overflow` -> `overflow_flag`
- **Timing**: Combinational settling time 1.0 ns.

### Vector-by-Vector Execution Results
```text
[HARNESS_START]
Vector 0: op=0x0, a=0x05, b=0x03 | EXP: res=0x08, z=0, ovf=0 | ACT: res=0x08, z=0, ovf=0 | MATCH
Vector 1: op=0x1, a=0x08, b=0x02 | EXP: res=0x06, z=0, ovf=0 | ACT: res=0x06, z=0, ovf=0 | MATCH
Vector 2: op=0x2, a=0x0F, b=0x0A | EXP: res=0x0A, z=0, ovf=0 | ACT: res=0x0A, z=0, ovf=0 | MATCH
Vector 3: op=0x3, a=0x0C, b=0x03 | EXP: res=0x0F, z=0, ovf=0 | ACT: res=0x0F, z=0, ovf=0 | MATCH
Vector 4: op=0x4, a=0x0A, b=0x05 | EXP: res=0x0F, z=0, ovf=0 | ACT: res=0x0F, z=0, ovf=0 | MATCH
Vector 5: op=0x0, a=0x7F, b=0x01 | EXP: res=0x80, z=0, ovf=1 | ACT: res=0x80, z=0, ovf=1 | MATCH
Vector 6: op=0x1, a=0x05, b=0x05 | EXP: res=0x00, z=1, ovf=0 | ACT: res=0x00, z=1, ovf=0 | MATCH
Vector 7: op=0x2, a=0xAA, b=0x55 | EXP: res=0x00, z=1, ovf=0 | ACT: res=0x00, z=1, ovf=0 | MATCH
Vector 8: op=0x3, a=0x00, b=0x00 | EXP: res=0x00, z=1, ovf=0 | ACT: res=0x00, z=1, ovf=0 | MATCH
Vector 9: op=0x4, a=0xFF, b=0xFF | EXP: res=0x00, z=1, ovf=0 | ACT: res=0x00, z=1, ovf=0 | MATCH
[HARNESS_DONE]
```

### Path B Audit Summary
- **Total Vectors**: 10
- **Passed Vectors**: 10
- **Failed Vectors**: 0
- **Mismatch Count**: 0
- **Overall Status**: **`PASS_REFERENCE_VERIFIED`**

---

## 3. Posit Multiplier Path B Demonstration (`multiplier` with `posit_mult_corners.csv`)

### Verification Configuration
- **DUT**: `multiplier` (`designs/multiplier.v`)
- **Reference File**: `tb/posit_mult_corners.csv` (Generated via `src/posit_model.py` Posit<16,2>)
- **Format**: CSV (radix: Hexadecimal)
- **Input Mappings**: `opd_a` -> `opd_a`, `opd_b` -> `opd_b`
- **Output Mappings**: `expected_product` -> `product`
- **Timing**: Combinational settling time 5.0 ns.

### Execution Results
- **Total Vectors Tested**: 144 corner-case vectors
- **Passed Vectors**: 123
- **Failed Vectors (Mismatches)**: 21
- **Overall Status**: **`FAIL_REFERENCE`**

### Sample Mismatch Discrepancy Log

| Vector Index | Input `opd_a` | Input `opd_b` | Expected Output (`product`) | Actual Output (`product`) | Mismatching Signal | Root Cause |
|---|---|---|---|---|---|---|
| 0 | `0x0000` (0.0) | `0x4000` (1.0) | `0x0000` (0.0) | `0x8000` (NaR) | `product` | Missing zero-input hardware bypass |
| 1 | `0x4000` (1.0) | `0x0000` (0.0) | `0x0000` (0.0) | `0x8000` (NaR) | `product` | Missing zero-input hardware bypass |
| 14 | `0x4800` (2.0) | `0x4400` (1.5) | `0x4E00` (3.0) | `0x4DC0` (2.875) | `product` | T-LEAP logarithmic approximation error |
| 27 | `0x4400` (1.5) | `0x4400` (1.5) | `0x4900` (2.25) | `0x48C0` (2.187) | `product` | T-LEAP logarithmic approximation error |

### Functional Insight
Path B successfully revealed critical hardware bugs that completely bypassed Path A legacy testbenches:
1. `tb_multiplier (2).v` (Path A) reported **0 errors** across 65,536 cycles because it only checked whether `product === 16'bX`.
2. Path B immediately caught that multiplying by zero produces invalid Not-a-Real (`0x8000`), and quantified the exact logarithmic approximation error bounds for non-power-of-two operands.
