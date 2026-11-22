# Path A: Existing Testbench Execution and Semantic Auditing Report

## 1. Overview
Path A automates the execution and deep semantic auditing of legacy, researcher-provided testbenches without altering original RTL or testbench source files.

### Core Separation of Statuses
The framework strictly decouples simulation exit codes from functional verification truth:
- **`execution_status`**: `EXEC_COMPLETED`, `EXEC_COMPILE_ERROR`, `EXEC_TIMEOUT`, `EXEC_RUNTIME_ERROR`, `EXEC_SKIPPED`
- **`testbench_status`**: `TB_PASS_ASSERTIONS`, `TB_FAIL_ASSERTIONS`, `TB_UNCHECKED`, `TB_INCOMPLETE`
- **`audit_status`**:
  - `PASS_TESTBENCH_ONLY`: All internal self-checking assertions passed, but no external golden reference was verified.
  - `EXECUTED / NOT VERIFIED`: Simulation completed with returncode 0, but the testbench performed zero assertion checks or only non-functional sentinels.
  - `INVALID_RESULTS`: Testbench checked only that signals were not unknown (`'x'` / `'z'`). Does not establish functional correctness.
  - `FUNCTIONAL_FAIL`: Testbench assertion or UVM error fired.
  - `COMPILE_ERROR`: Compiler rejected the code.
  - `TIMEOUT`: Simulation exceeded watchdog timer.

---

## 2. Posit Multiplier Path A Demonstration (`multiplier` with `tb_multiplier (2).v`)

### Execution Details
- **DUT**: `multiplier` (`designs/multiplier.v` with submodules `f_multiplier.v`, `PLAM.v`, `lod.v`, etc.)
- **Testbench**: `tb/tb_multiplier (2).v` (Unmodified legacy testbench)
- **Execution Command**:
  ```bash
  python src/engine.py --duts multiplier --timeout 120 --simulator icarus
  ```
- **Simulator**: Icarus Verilog 12.0
- **Elapsed Simulation Time**: 75.1 seconds (65,536 simulation cycles)

### Simulator Log Snippet
```text
=== TESTBENCH_START ===
VCD info: dumpfile dump.vcd opened for output.
opd_a = 0100100000000000, opd_b = 0000000000000000, product = 1000000000000000
opd_a = 0100100000000000, opd_b = 0000000000000001, product = 0000000000000000
...
opd_a = 0100100000000000, opd_b = 1111111111111111, product = 1011100000000000
Total cases checked: 65536
Testbench completed with 0 errors detected.
=== TESTBENCH_DONE ===
```

### Static and Semantic Audit Analysis
```python
# Extracted from tb/tb_multiplier (2).v
always @(product) begin
    if (product === 16'bxxxxxxxxxxxxxxxx) begin
        $display("ERROR: Product is all X at time %0t", $time);
        error_count = error_count + 1;
    end
end
```
- **Audit Findings**:
  1. The testbench fixes operand A to `0x4800` (2.0) and sweeps operand B across all 65,536 16-bit values.
  2. The only assertion present is a check against `16'bxxxxxxxxxxxxxxxx`.
  3. No mathematical comparison of the product against expected Posit logarithmic multiplication is performed.
- **Classification**:
  - `execution_status`: `EXEC_COMPLETED`
  - `testbench_status`: `TB_PASS_ASSERTIONS` (Weak check passed)
  - `audit_status`: **`PASS_TESTBENCH_ONLY`** (Explicitly flagged that non-X does not imply mathematical accuracy)

---

## 3. Generic ALU Path A Demonstration (`alu_core` with `tb_alu.v`)

### Execution Details
- **DUT**: `alu_core` (`examples/generic_alu/rtl/alu_core.v`)
- **Testbench**: `examples/generic_alu/tb/tb_alu.v`
- **Execution Command**:
  ```bash
  python src/engine.py --project-dir examples/generic_alu --config examples/generic_alu/config.json
  ```
- **Simulator**: Icarus Verilog 12.0
- **Elapsed Simulation Time**: 0.124 seconds

### Simulator Log Snippet
```text
=== TESTBENCH_START ===
Applying ALU Vector 0: op=ADD, a=0x05, b=0x03 -> result=0x08, zero=0, ovf=0
Applying ALU Vector 1: op=SUB, a=0x08, b=0x02 -> result=0x06, zero=0, ovf=0
Applying ALU Vector 2: op=AND, a=0x0F, b=0x0A -> result=0x0A, zero=0, ovf=0
Applying ALU Vector 3: op=OR,  a=0x0C, b=0x03 -> result=0x0F, zero=0, ovf=0
Applying ALU Vector 4: op=XOR, a=0x0A, b=0x05 -> result=0x0F, zero=0, ovf=0
All 5 stimulus vectors executed successfully.
=== TESTBENCH_DONE ===
```

### Semantic Audit Analysis
- The legacy testbench `tb_alu.v` applies 5 vectors and displays the outputs, but contains no `$fatal`, no `assert`, and no mismatch counters.
- **Classification**:
  - `execution_status`: `EXEC_COMPLETED`
  - `testbench_status`: `TB_UNCHECKED`
  - `audit_status`: **`EXECUTED / NOT VERIFIED`** (Simulation exited with 0, but no functional assertions exist in the testbench).
