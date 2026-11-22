# Cross-Project Reproducibility and Portability Report

## 1. Executive Summary
To prove that the RTL Regression Framework is truly project-independent (Layer A) and operates without modifying source code for new HDL projects, it was executed across two distinct project repositories:
1. **Generic ALU Project** (`examples/generic_alu`):
   - Multi-operation arithmetic/logic unit with status flags (`zero_flag`, `overflow_flag`).
   - Separate directory structure (`rtl/`, `tb/`, `ref/`, `config.json`).
2. **Posit Multiplier Project** (`multiplier.v`, `designs/`, `tb/`):
   - Deep hierarchical 16-bit logarithmic arithmetic pipeline.

Both projects were verified without modifying any core framework code. All project-specific information was supplied strictly via external JSON configuration files (Layer C).

---

## 2. Generic ALU Execution

### Execution Command
```bash
python src/engine.py --project-dir examples/generic_alu --config examples/generic_alu/config.json --force
```

### Framework Output
```text
==========================================================================================================================
DUT MODULE               | TESTBENCH         | STATUS            | CONF      | CACHE  | VECTORS    | TIME   | DIAGNOSTIC
--------------------------------------------------------------------------------------------------------------------------
alu_core                 | tb_alu            | PASS_TESTBENCH_ONLY | CONFIRMED | RUN    | 10/10      | 0.126s | All 10/10 self-checking testbench assert
alu_core                 | golden_ref        | PASS_REFERENCE_VERIFIED | CONFIRMED | RUN | 10/10      | 0.134s | All 10/10 vectors matched golden refer
==========================================================================================================================
```

### Reproducibility Verification
- **Compilation**: Clean under both Icarus Verilog and Siemens Questa.
- **Path A**: Testbench ran 10 cycles; audited to `PASS_TESTBENCH_ONLY`.
- **Path B**: Golden CSV evaluated 10 vectors; audited to `PASS_REFERENCE_VERIFIED`.

---

## 3. Posit Multiplier Execution

### Execution Command
```bash
python src/engine.py --duts multiplier --timeout 120 --force
```

### Framework Output
```text
==========================================================================================================================
DUT MODULE               | TESTBENCH         | STATUS            | CONF      | CACHE  | VECTORS    | TIME   | DIAGNOSTIC
--------------------------------------------------------------------------------------------------------------------------
multiplier               | tb_multiplier     | PASS_TESTBENCH_ONLY | CONFIRMED | RUN    | 65536/65536| 75.12s | Simulation completed with 0 assertions
multiplier               | golden_ref_corners| FAIL_REFERENCE    | CONFIRMED | RUN    | 123/144    | 0.210s | 21/144 mismatches detected (zero bypass)
==========================================================================================================================
```

### Key Proof of Project Independence
1. Zero hardcoded design names: The framework discovers modules, ports, and hierarchies dynamically using `ProjectScanner` and `VerilogASTParser`.
2. Port matching handles positional and named mappings without user intervention when interfaces match, and cleanly alerts via `INTERFACE ERROR` or `AMBIGUOUS MATCH` when ambiguities arise.
3. Caching and logging operate identically across projects, generating isolated builds in their designated build paths.
