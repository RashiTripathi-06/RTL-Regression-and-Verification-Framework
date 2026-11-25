# Posit<16,2> Multiplier Verification Modes & NaR/Zero Root-Cause Analysis

## 1. Verification Modes Overview

The RTL Regression and Verification Framework supports four distinct verification modes for `examples/posit_multiplier`, each reported independently in CSV, JSON, and HTML reports:

| Mode | Identifier | Scope & Coverage | Reference Oracle | Exhaustive? |
| :--- | :--- | :--- | :--- | :--- |
| **Path A Baseline** | `path_a_testbench` (`tb_multiplier`) | 65,536 cases with `opd_a = 16'h4800` fixed and `opd_b` swept `0x0000..0xFFFF` | None (X/Z check only -> `PASS_TESTBENCH_ONLY`) | Single-input only |
| **Path B Golden Reference** | `path_b_reference` (`harness_multiplier`) | 144 corner vectors from `ref/posit_mult_corners.csv` | `PositModel(16, 2)` golden CSV | Corner cases only |
| **Directed Special-Value Suite** | `special_values` | Directed Zero (`0x0000`), NaR (`0x8000`), sign, and boundary pairs | `PositModel(16, 2)` | Targeted special values |
| **Large-Scale Directed/Random** | `directed_random` | Configurable `10,000`, `20,000`, or `30,000` (default) independently varying `(opd_a, opd_b)` pairs | `PositModel(16, 2)` | **No** (samples $2^{32}$ space) |

> **Important Distinction**: Neither the 65,536-case single-input sweep nor the 30,000-pair directed/random suite constitutes full $2^{32}$ ($4,294,967,296$-pair) exhaustive verification. Full $2^{32}$ pairwise exhaustive testing is not run automatically due to simulation runtime.

---

## 2. NaR (`0x8000`) and Zero (`0x0000`) RTL Root-Cause Investigation

Inspection of `multiplier.v`, `posit_decoder.v`, `posit_encoder.v`, `PLAM.v`, and `f_multiplier.v` confirms:

1. **Zero is NOT explicitly recognized**: `posit_decoder.v` contains a comment (`// LeadingOne[0] tells if all 0's or all 1's was detected`), but `LeadingOne[0]` is never connected or used.
2. **NaR is NOT explicitly recognized**: `0x8000` is decoded as `sign = 1`, `opd_neg = 15'h0000`, `reg_ep = -60` (all-zero regime), `frac = 0`.
3. **No pre-multiplication special-case bypass**: All operands flow unconditionally through `decoder_A`, `decoder_B`, `PLAM`, exponent addition, and `encoder_Out`.
4. **Why `0x0000 * 0xC000` produces `0x8000` (NaR) instead of `0x0000` (Zero)**:
   - `multiplier.v` computes `sign_c = sign_a ^ sign_b = 0 ^ 1 = 1`.
   - `reg_ep_a = -60` (from `0x0000`) and `reg_ep_b = 0` (from `0xC000`), so `reg_ep_c = -60`.
   - `encoder_Out` right-shifts `R_shift_in` by 14 via `R_Shifter`, underflowing `posit_pd` to `15'h0000`.
   - `posit_encoder.v` lines 25–26 compute `twoscompliment(15'h0000, sign_c=1) = 15'h0000` and unconditionally assign `product[15] = sign_c = 1`.
   - Thus `{1'b1, 15'h0000} = 16'h8000` (NaR) is emitted instead of `0x0000` (Zero).
5. **NaR propagation failures**:
   - Because `sign_c = sign_a ^ sign_b`, `NaR (0x8000) * Negative (0xC000)` produces `sign_c = 1 ^ 1 = 0`, yielding `0x0000` (Zero) instead of `0x8000` (NaR).
   - Similarly, `NaR (0x8000) * NaR (0x8000)` produces `0x0000` instead of `0x8000`.

---

## 3. Configuration (`examples/posit_multiplier/config.json`)

```json
"verification_strategy": {
  "mode": "directed_random",
  "test_count": 30000,
  "random_seed": 12345,
  "special_value_tests": true,
  "boundary_tests": true,
  "structured_tests": true,
  "random_tests": true,
  "preserve_original_testbench": true,
  "run_special_value_suite": true,
  "target_dut": "multiplier",
  "generator": "extensions.posit.posit_model:generate_posit_vectors",
  "nar_bit_pattern": "0x8000"
}
```

- Change `"test_count"` to `10000`, `20000`, or `30000`.
- Change `"random_seed"` for reproducible random sampling.
- Full mismatches are preserved in `build/strategy_<mode>__multiplier/all_mismatches.csv`.
