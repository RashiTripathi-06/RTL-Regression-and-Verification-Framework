# Final Demonstration & Reproduction Guide
## Automated RTL Verification & Regression Framework

This guide provides exact, copy-pasteable CLI commands to reproduce all verification and validation results across the three independent benchmarks evaluated by the framework.

---

## 1. System Environment Preparation

### Prerequisites
- Python 3.10+ (Standard library + `tree-sitter`, `tree-sitter-verilog`, `networkx`).
- Simulators:
  - **Icarus Verilog 12.0** (`iverilog`, `vvp` on PATH).
  - **Siemens Questa 2025.3** (Optional; required for commercial SystemVerilog and multi-driver/ANSI checks).
- Windows License Setup (when executing Questa outside sandbox):
  ```powershell
  $env:SALT_LICENSE_SERVER = "D:\dop2\LR-213236_License.dat"
  ```

### Install Python Dependencies
```bash
pip install -r requirements.txt
```

---

## 2. Test-Suite Execution & Validation Accounting

Execute the full automated test suite (95 unit and integration tests across 21 modules):
```bash
python -u -m unittest discover -s tests -p "test_*.py" -v
```

### Exact Test-Suite Accounting:
- **Total Tests Discovered**: 95
- **Passed**: 93 (in sandbox) / 95 (outside sandbox with license access)
- **Skipped**: 2 (`test_compile_and_simulate_license_test` and `test_questa_reference_verification` when executing within the restricted Windows sandbox due to DLL relocation security policies).
- **Failed**: 0 (0.0%)
- **Errored**: 0 (0.0%)
- **Execution Time**: ~28.4 seconds

---

## 3. Demonstration of the Three Independent Benchmarks

### Benchmark 1: Generic ALU (`examples/generic_alu/`)
Combinational 8-bit arithmetic-logic unit with opcode decoded arithmetic/bitwise operations.
- **RTL Path**: `examples/generic_alu/rtl/alu_core.v`
- **Testbench Path**: `examples/generic_alu/tb/tb_alu.v`
- **External Configuration**: `configs/generic_alu.json`
- **Execution Command**:
  ```bash
  python src/engine.py --project-dir examples/generic_alu --config configs/generic_alu.json --force
  ```
- **Expected Results**:
  - `alu8 | tb_alu8 | EXECUTED / NOT VERIFIED | 0/0`: Legacy testbench executes to completion (rc=0) but contains zero assertion checks.
  - `alu8 | harness_alu8 | PASS_REFERENCE_VERIFIED | 10/10`: Golden reference CSV verified 10/10 vectors with zero mismatches.

---

### Benchmark 2: Synthetic MAC Unit (`examples/synthetic_mac/`)
Sequential 8-bit Multiply-Accumulate unit with active-low reset (`rst_n`), clock (`clk`), enable (`en`), and overflow detection (`ovf`).
- **RTL Path**: `examples/synthetic_mac/rtl/mac_unit.v`
- **Testbench Path**: `examples/synthetic_mac/tb/tb_mac_unit.v`
- **External Configuration**: `configs/synthetic_mac.json`
- **Execution Command**:
  ```bash
  python src/engine.py --project-dir examples/synthetic_mac --config configs/synthetic_mac.json --force
  ```
- **Expected Results**:
  - `mac_unit | tb_mac_unit | PASS_TESTBENCH_ONLY | 4/4`: Original self-checking testbench asserts 4/4 vectors pass.
  - `mac_unit | harness_mac_unit | PASS_REFERENCE_VERIFIED | 5/5`: Dynamic sequential test harness drives clock/reset/enable and independently scores 5/5 vectors.

---

### Benchmark 3: Posit Multiplier (`multiplier`)
16-bit logarithmic approximate multiplier implementing Posit<16, 2> arithmetic via T-LEAP architecture.
- **RTL Path**: `multiplier.v` (with submodules `f_multiplier.v`, `PLAM.v`, `lod.v`, etc.)
- **Testbench Path**: `tb_multiplier (2).v`
- **External Configuration**: `configs/posit_multiplier.json`
- **Execution Command**:
  ```bash
  python src/engine.py --config configs/posit_multiplier.json --duts multiplier --force
  ```
- **Expected Results**:
  - `multiplier | tb_multiplier | PASS_TESTBENCH_ONLY | 65536/65536`: 65,536-cycle sweep completes in ~75s with zero assertion errors; correctly audited as `PASS_TESTBENCH_ONLY` because it only asserts non-X state.
  - `multiplier | harness_multiplier | FUNCTIONAL FAIL | 123/144`: Golden reference evaluation catches 21/144 mismatches due to missing zero-input bypass and logarithmic approximation bounds.

---

## 4. Verification of Zero Universal Source Modifications

Run the automated manifest verification tool:
```bash
python scripts/verify_project_independence_manifest.py
```
This utility calculates SHA-256 digests for all 18 source files in `src/` before and after running each benchmark and generates `reports/final/source_integrity_manifest.md` confirming **0 file modifications (100% bit-for-bit invariance)**.

---

## 5. Additional Key Demonstrations

### Native Siemens Questa 2025.3 Adapter Validation
```bash
python scripts/validate_questa_adapter.py
```
Validates executable discovery, license environment, error classification, watchdog timeouts, and sequential cross-thread mutex synchronization.

### Systematic RTL Mutation Testing (MANTRA2 Methodology)
```bash
python scripts/audit_mutation_testing.py
```
Generates 7 first-order syntactic mutants (AOR, BOR, OI) and evaluates defect detection between Path A (0% Mutation Score) and Path B (100% Mutation Score).

### Multi-Source Reference Management & PositHub Integration Demo
```bash
python -u -m unittest discover -s tests -p "test_reference_manager.py" -v
```
Demonstrates:
- **Case 1 (Primary Active)**: Selects primary golden dataset for Path B and attempts cross-validation.
- **Case 2 (Fallback Active)**: Elevates secondary material to active fallback when primary dataset is missing.
- **Case 3 (Conflict Disputed)**: Flags `STATUS_REFERENCE_DISPUTED` and logs conflicting vectors when two references disagree.
- **Case 4 (Unavailable / Non-executable)**: Rejects using 1-D decoding tables (like PositHub) as direct arithmetic oracles without external model adapters.
- **Automated Classification**: Distinguishes Direct I/O tables, Numerical Decoding tables, Mathematical specs, and PDF/doc materials.

### Cryptographic Merkle Cache Invalidation & Historical Replay
```bash
python scripts/validate_cache_and_replay.py
```
Verifies cache invalidation against 7 distinct trigger events and deterministically reproduces 45 plans from historical run records.
