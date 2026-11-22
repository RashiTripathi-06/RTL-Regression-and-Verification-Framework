# Posit Multiplier Benchmark Example

This example demonstrates the verification of a 16-bit logarithmic approximate Posit multiplier implementing $\text{Posit}\langle 16, 2\rangle$ arithmetic via the T-LEAP (Truncated Logarithmic Exact Approximate Posit) architecture.

## Architecture & Submodules
- `rtl/multiplier.v`: Top-level module integrating decoder, PLAM, and encoder stages.
- `rtl/posit_decoder.v`: Extracts sign, regime, exponent, and fraction fields.
- `rtl/PLAM.v`: Piecewise Linear Approximation Multiplier core.
- `rtl/f_multiplier.v`: Logarithmic core with leading-one detector (LOD).
- `rtl/posit_encoder.v`: Re-packs sign, regime, exponent, and fraction into 16-bit Posit format.
- `rtl/` (Supporting units): `lod.v`, `lod_encoder_15bit.v`, `L_Shifter.v`, `R_Shifter.v`, `shifterR.v`, `mask.v`, `max_ctl.v`, `mux.v`, `adder.v`, `twoscompliment.v`, `not_module.v`, `xor_module.v`, `8bit_encoder.v`.

## Reference Verification
- **Primary Reference**: `ref/posit_mult_corners.csv` (144 corner test vectors including zero, NaR, $\pm 1$, min/max positive/negative, and cross-regime values).
- **Secondary Reference**: PositHub official lookup widget specification (`https://www.posithub.org/widget/lookup`).

## Reproduction Commands
Execute verification using the project-independent framework engine:
```bash
python ../../src/engine.py --project-dir . --config config.json --force
```
Or from the framework root directory:
```bash
python src/engine.py --config configs/posit_multiplier.json --project-dir examples/posit_multiplier --force
```
