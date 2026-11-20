# Automated RTL Regression and Verification Framework

A production-grade, reproducible, generic RTL verification and regression automation system built for Verilog and SystemVerilog research and ASIC/FPGA digital design projects.

---

## 1. Key Capabilities

- **Zero-Modification Project Intake**: Point the framework at any directory containing HDL sources (`.v`, `.sv`, `.vh`, `.svh`), testbenches, and data files. It automatically discovers modules, resolves submodule dependencies, matches testbenches to DUTs, synthesizes non-invasive compatibility wrappers where needed, compiles, simulates, audits, and generates rich dashboards without altering original source code.
- **Native Siemens Questa 2025.3 Integration**:
  - Full adapter for **Questa Altera Starter FPGA Edition 2025.3** (`vlib`, `vlog`, `vsim -c`).
  - Strict single-session license concurrency control (`threading.Lock()`) for node-locked, uncounted FlexNet/SALT licenses (`SALT_LICENSE_SERVER=LR-213236_License.dat`).
  - Transparent fallback to **Icarus Verilog** (`iverilog`, `vvp`).
- **Dual Verification Paths**:
  - **Path A (Existing Testbenches)**: Executes researcher-provided testbenches as-is, captures stdout/stderr, detects timeouts, and audits self-checking assertions. Testbenches that only assert non-X outputs (such as `tb_multiplier (2).v`) are strictly classified as `PASS_TESTBENCH_ONLY` or `NOT_VERIFIED`, never falsely conflated with golden reference verification.
  - **Path B (Independent Golden Reference Verification)**: Generic reference harness engine supporting CSV, JSON, HEX, and `.mem` datasets. Dynamically generates isolated test harnesses (`harness_<dut>.sv`), applies stimulus with configurable settling time or clock cycles, samples DUT outputs, and independently scores vectors in Python.
- **Cryptographic SHA-256 Merkle-Tree Incremental Caching**:
  - Automatically invalidates cache when DUT source, submodule dependencies, includes, testbenches, reference datasets, compiler flags, simulator version, or license files change.
  - 100% cache hits on clean re-runs, completing regression in <0.01s.
- **Immutable Execution History & Replay CLI**:
  - Appends structured run records to `reports/history.jsonl` with unique `run_id`s.
  - CLI command `python src/engine.py --replay <run_id>` re-executes historic runs and compares current simulation against historic results to verify reproducibility.
- **Testbench Quality & Mutation Analysis (MANTRA2 Evaluation)**:
  - Syntactic fault injection engine introducing single-fault mutants (AOR, ROR, COR, SOR, SA0, SA1).
  - Calculates Mutation Score ($MS$) to expose testbench blind spots (e.g., demonstrating that X-only checking has ~0% MS whereas reference verification achieves high MS).

---

## 2. Directory Structure

```text
D:\dop2\
├── src/
│   ├── models.py                  # Core data classes (VerificationPlan, TestResult, PortSpec, etc.)
│   ├── scanner.py                 # Recursive HDL, include, and reference file discovery
│   ├── parser.py                  # IEEE 1364/1800 AST parser (Tree-Sitter Verilog)
│   ├── matcher.py                 # Confidence-based DUT-TB matching & wrapper decision
│   ├── dependency_resolver.py     # Hierarchical dependency ordering & cycle detection
│   ├── planner.py                 # Multi-DUT verification planning & reference binding
│   ├── executor.py                # Native Questa 2025.3, Icarus, Edalize, Verilator adapters
│   ├── reference_verifier.py      # Path B: Generic harness generator & reference scoreboard
│   ├── posit_model.py             # IEEE draft standard Posit<N, es> arithmetic model
│   ├── mutator.py                 # MANTRA2-compliant RTL fault injector & mutation scorer
│   ├── auditor.py                 # Log analyzer, UVM/assertion audit, sentinel validation
│   ├── static_analyzer.py         # Linting: latches, multi-driven nets, port width mismatches
│   ├── cache_manager.py           # SHA-256 Merkle tree regression cache
│   ├── report_generator.py        # Dashboard synthesis (HTML, CSV, JSON, history.jsonl)
│   └── engine.py                  # Top-level regression CLI and orchestration engine
├── designs/                       # Benchmark DUTs (RCA, CLA, CSLA, ALU, Posit submodules)
├── tb/                            # Testbenches and reference datasets (golden CSV, JSON, MEM)
├── tests/                         # 80 comprehensive automated unit tests
├── examples/                      # Generic sample projects
│   └── generic_alu/               # Standalone 8-bit ALU with CSV golden reference
├── reports/                       # Generated dashboards, CSV summaries, and history.jsonl
├── run_demo.ps1                   # One-command demonstration PowerShell script
├── requirements.txt               # Bounded dependencies
└── AUDIT_BASELINE.md              # Initial architectural audit report
```

---

## 3. Quickstart

### Prerequisites
- Python 3.10+ (Standard library + `tree-sitter>=0.25.0`, `tree-sitter-verilog>=1.0.3`, `networkx>=3.0`)
- Simulator: Siemens Questa Altera Starter FPGA Edition 2025.3 and/or Icarus Verilog (`iverilog`).
- Windows license environment variable:
  ```powershell
  $env:SALT_LICENSE_SERVER = "D:\dop2\LR-213236_License.dat"
  ```

### Install Dependencies
```bash
pip install -r requirements.txt
```

### One-Command Demonstration
Execute the full automated demonstration covering toolchain detection, unit tests, benchmark regression, caching, replay, and reference harness synthesis:
```powershell
.\run_demo.ps1
```

### Manual CLI Usage

#### 1. Run full regression suite (Icarus backend)
```bash
python src/engine.py
```

#### 2. Run regression using native Questa 2025.3 backend
```bash
python src/engine.py --simulator questa --workers 1
```
*(Note: Questa worker count is strictly locked to 1 to respect the single-session node-locked license).*

#### 3. Point framework at an arbitrary project directory
```bash
python src/engine.py --project-dir examples/generic_alu --config examples/generic_alu/config.json
```

#### 4. Replay a historic execution run
```bash
python src/engine.py --replay run_20261121_021155_abc123
```

#### 5. Force clean re-run bypassing cache
```bash
python src/engine.py --force
```

#### 6. Filter specific DUTs
```bash
python src/engine.py --duts adder_rca adder_cla
```

---

## 4. Benchmark Verification Matrix (Scenarios A through N)

| Scenario | Scenario Name | DUT Module | Testbench | Expected Status | Actual Status | Time |
|:---:|:---|:---|:---|:---:|:---:|:---:|
| **A** | Exact 1-to-1 Match | `adder_rca` | `tb_adder` | `PASS_REF_VERIF` | `PASS_REFERENCE_VERIFIED` | 0.206s |
| **B** | Name Mismatch (Wrapper) | `adder_cla` | `tb_adder` | `PASS_REF_VERIF` | `PASS_REFERENCE_VERIFIED` | 0.176s |
| **C** | Ambiguous Match Rejection | `mask` | `tb_multiplier` | `AMBIGUOUS_MATCH` | `AMBIGUOUS_MATCH` | 0.001s |
| **D** | Multi-Level Dependency Tree | `adder_rca` | `tb_adder` | `PASS_REF_VERIF` | `PASS_REFERENCE_VERIFIED` | 0.206s |
| **E** | Self-Checking TB | `alu_4bit` | `tb_alu` | `PASS_TB_ONLY` | `PASS_TESTBENCH_ONLY` | 0.127s |
| **F** | Functional Bug Caught | `adder_buggy` | `tb_adder` | `FUNCTIONAL_FAIL` | `FUNCTIONAL_FAIL` | 0.201s |
| **G** | X/Z Output State Reported | `adder_x_output`| `tb_adder` | `INVALID_RESULTS` | `INVALID_RESULTS` | 0.193s |
| **H** | Premature Termination | `adder_incomplete`| `tb_adder` | `INCOMPLETE` | `INCOMPLETE` | 0.186s |
| **I** | Watchdog Timeout | `adder_infinite_loop`| `tb_adder` | `TIMEOUT` | `TIMEOUT` | 5.173s |
| **J** | Compilation Syntax Error | `adder_syntax_error`| `tb_adder`| `COMPILE_ERROR` | `COMPILE_ERROR` | 0.137s |
| **K** | Missing Submodule Dep | `adder_missing_sub`| `tb_adder`| `COMPILE_ERROR` | `COMPILE_ERROR` | 0.110s |
| **L** | Merkle Tree Cache Hit | Clean Re-run | Any | `CACHE_HIT` | `CACHE_HIT` (100%) | 0.000s |
| **M** | Cache Invalidation | Mutated Source | Any | `RUN` (Invalidated) | `RUN` (Re-simulated) | 0.150s |
| **N** | Questa Sequential Queue | Multi-DUT Run | Questa | Sequential Run | Sequential OK (No crash) | 5.496s |

---

## 5. Posit Multiplier Integration Findings

1. **RTL Exponent Discrepancy**: The original specification mentioned Posit<16, 1>, but the actual Verilog RTL (`multiplier.v`, `posit_decoder.v`, `posit_encoder.v`) allocates 2 exponent bits (`reg_ep[1:0]`), making the RTL a **Posit<16, 2>** implementation ($useed = 2^{2^2} = 16$).
2. **Approximate Architecture**: The multiplier implements a logarithmic approximate mantissa multiplier (T-LEAP architecture) using Leading One Detectors (`lod.v`) and barrel shifters (`PLAM.v`, `f_multiplier.v`). Outputs approximate exact products.
3. **Questa 2025.3 Strictness (`shifterR.v`)**:
   - `shifterR.v` declares:
     ```verilog
     module log_shifter_R #(parameter N = 3, parameter t = 8)(
         ...
         output [n-1:0] F
     );
     localparam n = 2**N;
     ```
   - Questa 2025.3 strictly enforces IEEE 1364-2001 / IEEE 1800-2023 ANSI port scoping, throwing non-suppressible compile errors `(vlog-2730)` and `(vlog-13294)` because `n` is referenced in the port header before its definition. Icarus Verilog compiles it due to two-pass parsing. The framework records this diagnostic faithfully without altering original RTL.
4. **Weakness of `tb_multiplier (2).v`**:
   - The testbench fixes $A = \text{16'h4800}$, sweeps $B \in [0, 65535]$, waits 1 timeunit, and only asserts `if (product === 16'hxxxx)`.
   - Mutation analysis proves this checker has a **0% Mutation Score** against arithmetic faults.
   - The framework categorizes this testbench as `PASS_TESTBENCH_ONLY` and provides **Path B** reference verification against `tb/posit_mult_corners.csv`.

---

## 6. Verification Status Hierarchy

The framework reports one of 14 strictly typed execution statuses:
1. `PASS_REFERENCE_VERIFIED`: All outputs matched an external golden reference.
2. `PASS_TESTBENCH_ONLY`: Self-checking assertions passed; no reference verified.
3. `PASS`: Generic legacy pass.
4. `FUNCTIONAL_FAIL`: Output mismatch against reference or assertion failure.
5. `COMPILE_ERROR`: HDL compilation or elaboration syntax failure.
6. `SIMULATION_ERROR`: Runtime simulator crash or non-zero exit.
7. `TIMEOUT`: Watchdog timer terminated infinite loop or simulation hang.
8. `INCOMPLETE`: Simulation ended prematurely or sentinels were missing.
9. `INVALID_RESULTS`: High-impedance `z` or unknown `x` detected on monitored nets.
10. `INTERFACE_ERROR`: Structural port width or direction incompatibility.
11. `NO_MATCH`: No compatible testbench found for candidate DUT.
12. `AMBIGUOUS_MATCH`: Multiple candidate testbenches found; rejected to avoid guessing.
13. `MISSING_REFERENCE`: Testbench expects data file that does not exist.
14. `LICENSE_ERROR`: Simulator license checkout failure (e.g. FlexNet / SALT error).
