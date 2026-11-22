# Standalone RTL Regression & Verification Framework (`rtl_framework`)

A reusable, simulator-agnostic verification engine for digital hardware designs in Verilog (IEEE 1364) and synthesizable SystemVerilog (IEEE 1800).

---

## 1. What the Framework Does

The `rtl_framework` package automates the repetitive, error-prone manual stages of RTL regression testing:
- **Zero-Annotation Discovery**: Scans project directories to discover Verilog/SystemVerilog RTL and testbenches without requiring code comments, pragmas, or special naming conventions.
- **AST Parsing**: Analyzes Verilog ASTs (via Tree-Sitter) to extract modules, ANSI and non-ANSI port declarations, parameters, and hierarchical submodule instantiations.
- **Submodule Dependency Resolution**: Resolves hierarchical module trees, computes topological compilation order, and flags circular dependency loops.
- **DUT-to-Testbench Matching**: Compares DUT and testbench port interfaces structurally to match compatible pairs and generates non-invasive port adapters where appropriate.
- **Dual-Path Verification**:
  - **Path A**: Executes native testbenches and audits simulation logs for self-checking assertions, UVM report markers, completion sentinels, and uninitialized (`x`/`z`) states.
  - **Path B**: Generates standalone dynamic SystemVerilog test harnesses (`harness_<dut>.sv`), applies input vectors from external golden reference tables, captures outputs, and compares each vector against expected outputs.
- **Cryptographic Merkle Caching**: Builds SHA-256 Merkle trees of design files, dependencies, include headers, reference tables, and compiler flags to provide instant, byte-accurate cache replay.
- **Deterministic Reporting**: Emits interactive HTML visual dashboards, machine-readable CSV and JSON summaries, and append-only historical runlogs (`history.jsonl`).

---

## 2. What is Generic and Reusable

The code inside this directory (`framework/`) is completely generic. It contains:
- No hardcoded arithmetic operations (no ALU opcodes, no Posit arithmetic, no adder logic).
- No hardcoded module names, port names, or signal widths.
- No hardcoded file paths or assumptions about the surrounding directory structure.
- All algorithms operate dynamically on discovered AST metadata, declarative configuration files, and standard input/output reference tables.

---

## 3. What is Outside the Framework

The generic framework does **not** include:
- Specific research hardware designs (e.g., benchmark ALUs, MAC units, or Posit multipliers).
- Benchmark-specific golden reference datasets.
- Domain-specific numerical arithmetic models (e.g., Posit floating-point decoders).
- Proprietary commercial simulator licenses.

Researchers supply their own RTL, testbenches, reference tables, and configurations as described in Section 8.

---

## 4. Python Requirements

- **Python Version**: `>= 3.9` (fully tested and verified on Python 3.10, 3.11, 3.12, 3.13, and 3.14).
- **Core Dependencies**:
  - `tree-sitter>=0.25.0`
  - `tree-sitter-verilog>=1.0.3`
  - `networkx>=3.0`

---

## 5. Simulator Requirements

At least one supported simulator must be installed and accessible on your system `PATH`:
- **Icarus Verilog** (`iverilog`, `vvp`): Recommended open-source simulator (v11.0 or v12.0). Active default engine.
- **Siemens Questa / ModelSim** (`vlib`, `vlog`, `vsim`): Commercial IEEE 1800 SystemVerilog simulator. Supported with automated license serialization.
- **Edalize**: Tool-agnostic EDAM build configuration manifest generator (`edam.json`).
- **Verilator**: Supported for cycle-accurate C++ simulation and static linting.

---

## 6. Installation Guide

Extract or copy only the `framework/` folder to your target environment, create a clean virtual environment, and install:

```powershell
# 1. Create a clean virtual environment
python -m venv .venv

# 2. Activate virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# (On Linux / macOS: source .venv/bin/activate)

# 3. Install framework in editable mode
pip install -e .
```

Verify the installation:
```powershell
rtl-framework --version
# Output: rtl-framework 1.0.0
```

---

## 7. Quick Start

Run regression on an external project:
```powershell
# Run regression on project directory using its config.json
rtl-framework run --project ./my_rtl_project --config ./my_rtl_project/config.json

# Force re-execution bypassing the Merkle cache
rtl-framework run --project ./my_rtl_project --config ./my_rtl_project/config.json --force

# Filter to verify a specific DUT module
rtl-framework run --project ./my_rtl_project --config ./my_rtl_project/config.json --duts my_alu

# Replay a historical run by Run ID
rtl-framework replay <RUN_ID>
```

---

## 8. Expected Researcher Project Structure

Organize your hardware project following this standard layout:

```text
my_rtl_project/
│
├── rtl/                               # DUT Implementation Sources
│   ├── top.v                          # Top-level module
│   ├── module_a.v                     # Submodules
│   └── module_b.v
│
├── tb/                                # Testbenches for Path A
│   └── tb_top.v                       # Native simulation stimulus & assertions
│
├── references/                        # Golden Reference Datasets for Path B
│   └── golden_vectors.csv             # Direct I/O vector table
│
├── data/                              # Simulation Dependencies (Conditional)
│   └── memory_init.hex                # Optional include files or memory images
│
└── config.json                        # Declarative Project Configuration
```

| Project Input | Status | Description |
|---|---|---|
| **RTL Source Files (`rtl/*.v`)** | **Mandatory** | Synthesizable Verilog or SystemVerilog hardware implementations. |
| **Configuration (`config.json`)** | **Mandatory** | Declares project name, simulator backend, timeouts, and reference mappings. |
| **Testbench (`tb/*.v`)** | **Required for Path A** | Simulation stimulus and self-checking assertions. |
| **Golden References (`references/*`)**| **Required for Path B** | Independent expected input/output tables (`.csv` or `.json`). |
| **Include / Data Files (`data/*`)** | **Conditional** | Memory tables (`.mem`, `.hex`) or header files (`.vh`) needed during simulation. |

---

## 9. Configuration Instructions (`config.json`)

Declare project parameters and reference mappings using JSON:

```json
{
  "project_name": "Custom_ALU_Project",
  "build_dir": "build",
  "reports_dir": "reports",
  "simulator": "icarus",
  "timeout_seconds": 10.0,
  "reference_sources": {
    "primary": {
      "name": "golden_alu",
      "path": "references/golden_vectors.csv",
      "priority": 1,
      "type": "direct_io_table",
      "format": "csv",
      "radix": "hex",
      "input_mapping": {
        "operand_a": "a",
        "operand_b": "b",
        "op_code": "op"
      },
      "output_mapping": {
        "expected_result": "result",
        "expected_zero": "zero_flag"
      },
      "timing": {
        "mode": "combinational",
        "settling_time_ns": 5.0
      }
    }
  }
}
```

### Sequential Clocked Designs
For sequential designs, set `"mode": "sequential"` and specify:
- `"clock_signal"`: Name of DUT clock port (e.g. `"clk"`).
- `"reset_signal"`: Name of DUT reset port (e.g. `"rst_n"`).
- `"reset_active_level"`: Active polarity (`0` for active-low, `1` for active-high).
- `"reset_duration_cycles"`: Number of clock cycles to hold reset during initialization.
- `"latency_cycles"`: Latency in clock cycles between stimulus application and valid output.
- `"clock_period_ns"`: Clock period in nanoseconds (e.g. `10.0`).

---

## 10. DUT and Testbench Discovery

The framework scanner walks the project tree and parses every `.v` and `.sv` file into concrete ASTs using Tree-Sitter. It extracts:
- Module names and parameters.
- Port declarations (name, direction, bit-width range).
- Instantiations of child submodules.
- Testbench markers: top-level modules with 0 ports, initial blocks, `$finish`, `$readmemh`, `$display`.

---

## 11. Dependency Resolution and Cycle Detection

The dependency resolver constructs a directed graph of module instantiations using NetworkX:
- Computes topological elaboration ordering (leaf modules compiled before parents).
- Detects circular dependency cycles (`ModA -> ModB -> ModA`) and halts with a diagnostic before invoking the simulator compiler.
- Recursively traverses `` `include `` compiler directives (`header_a.vh -> header_b.vh`).

---

## 12. Path A: Native Testbench Execution

- **How It Works**: The framework compiles the DUT and matching testbench and executes the simulation.
- **Auditing**: Scans stdout/stderr for:
  - Explicit testbench sentinels: `=== TESTBENCH_START ===` and `=== TESTBENCH_DONE ===`.
  - Self-checking summaries: `=== TESTBENCH_SUMMARY: total=N pass=P fail=F ===`.
  - Assertion failures, UVM error markers (`UVM_ERROR`, `UVM_FATAL`), and uninitialized (`x`/`z`) states.
- **Integrity Rule**: A testbench that completes with return code 0 but contains **zero assertion checks** is classified as **`EXECUTED / NOT VERIFIED`**, never as a PASS.

---

## 13. Path B: Independent Reference Verification

- **How It Works**: The reference engine generates a dynamic SystemVerilog test harness (`harness_<dut>.sv`), applies inputs from the golden table, samples DUT outputs at the configured settling or clock boundary, and streams actual outputs to `actual_outputs.csv`.
- **Comparison**: An independent Python scoreboard performs bit-exact comparison between actual and expected outputs.
- **Integrity Rule**: Expected reference data is mandatory for Path B. If reference vectors are missing or unmapped, the framework reports **`REFERENCE_UNAVAILABLE`** and will **never** fabricate expected outputs or report `PASS_REFERENCE_VERIFIED`.

---

## 14. Reference Data Formats

The framework supports:
1. **CSV Tables (`.csv`)**: Header row defines column names mapped in `config.json`.
2. **JSON Datasets (`.json`)**: List of vector objects with input and expected output keys.
3. **Memory Files (`.mem`, `.hex`, `.dat`)**: Verilog `$readmemh` / `$readmemb` compatible tables.
4. **Radix Options**: `hex` (default, hex strings like `1A`, `0x1A`) or `dec` (decimal integers).

---

## 15. Optional Extension Interface

Researchers do **NOT** need to write Python code for standard Verilog designs. Custom extensions are required only when dealing with non-standard numerical representations or dynamic algorithmic reference models.

To create an extension, subclass `ReferenceProvider` from `rtl_framework.provider`:

```python
from pathlib import Path
from rtl_framework.provider import ReferenceProvider, register_provider
from rtl_framework.models import ModuleInfo, ParsedVector

class CustomModelProvider(ReferenceProvider):
    @property
    def name(self) -> str:
        return "custom_model"

    def can_handle(self, config_type: str) -> bool:
        return config_type == "custom_model"

    def generate_vectors(self, dut: ModuleInfo, config: dict, workspace_root: Path) -> list[ParsedVector]:
        # Generate stimulus and expected outputs algorithmically
        return [
            ParsedVector(inputs={"a": 3, "b": 2}, expected_outputs={"result": 5})
        ]

# Register provider
register_provider("custom_model", CustomModelProvider())
```

---

## 16. CLI Reference

```text
usage: rtl-framework [-h] [--version] {run,replay} ...

Subcommands:
  run       Run automated RTL regression and verification
  replay    Replay a historic execution run by Run ID

Run Arguments:
  --project, --project-dir PATH   Root directory of HDL project (default: current directory)
  --config PATH                   Path to configuration JSON
  --simulator {icarus,questa,...} Simulator backend adapter
  --force                         Bypass Merkle cache and force re-simulation
  --serial                        Run simulations sequentially
  --workers N                     Worker thread limit (default: 4)
  --duts [NAME ...]               Filter specific DUTs
  --timeout SECONDS               Watchdog timeout in seconds
```

---

## 17. Generated Reports

Every run produces structured artifacts inside the configured `reports/` folder:
- **`regression_report.html`**: Interactive HTML dashboard with status badges, execution metrics, and expandable vector failure diagnostic tables.
- **`regression_summary.csv`**: Tabular CSV export of plan IDs, DUTs, testbenches, status, cache outcomes, vector counts, and elapsed times.
- **`regression_summary.json`**: Machine-readable JSON summary of all plan results, active configurations, and failing vector diagnostics.
- **`history.jsonl`**: Append-only log enabling historical run comparisons and CLI replay.

---

## 18. Result Interpretation

| Status | Meaning | What It Proves |
|---|---|---|
| `PASS_REFERENCE_VERIFIED` | All DUT outputs matched expected values from external golden dataset (Path B). | Hardware functionally matches independent reference oracle. |
| `PASS_TESTBENCH_ONLY` | Self-checking testbench assertions passed with zero failures (Path A). | Testbench stimulus produced no assertion failures. |
| `EXECUTED / NOT VERIFIED` | Simulation finished with rc=0, but contained 0 assertion checks. | Simulation completed without error; functional correctness is unverified. |
| `FUNCTIONAL FAIL` | Output mismatch against golden reference or failed testbench assertion. | Functional defect detected in RTL or testbench. Mismatches logged. |
| `COMPILE ERROR` | HDL compilation or elaboration syntax failure. | Code does not compile under the target simulator. |
| `INTERFACE ERROR` | Structural port width, count, or direction mismatch between DUT and testbench. | Port connection incompatibility. |
| `TIMEOUT` | Simulation exceeded the watchdog execution limit. | Infinite loop or hung simulation. |
| `INCOMPLETE` | Testbench terminated prematurely before end-of-test sentinel. | Unexpected `$finish` or crashed testbench. |
| `INVALID RESULTS` | High-impedance (`z`) or uninitialized (`x`) states detected on outputs. | Floating nets or reset initialization bug. |
| `REFERENCE_DISPUTED` | Primary and secondary reference sources disagree on expected outputs. | Reference oracle ambiguity; needs resolution. |
| `REFERENCE_UNAVAILABLE` | Declared reference table is missing or non-executable. | Missing golden dataset. |

---

## 19. Troubleshooting

- **`iverilog: command not found`**: Ensure Icarus Verilog (`iverilog.exe`, `vvp.exe`) is installed and on your system `PATH`.
- **`Interface Error: Port width mismatch`**: Check DUT and testbench port declarations. The framework enforces strict bit-width matching.
- **`Testbench sentinels missing`**: For Path A, include `$display("=== TESTBENCH_START ===");` and `$display("=== TESTBENCH_DONE ===");` in your testbench.
- **`Unknown 'x' output detected`**: Ensure all registers in sequential designs are properly initialized on reset.

---

## 20. Current Limitations

- **SystemVerilog Language Subset**: Supports synthesizable Verilog (IEEE 1364) and synthesizable SystemVerilog (IEEE 1800). Advanced OOP SystemVerilog class testbenches (e.g., full UVM VIP environments) require pre-compiled execution.
- **Clock Domains for Dynamic Harnesses**: Path B automated harness generation supports single-clock synchronous designs. Multi-clock domain (CDC) architectures require user-provided Path A testbenches.

---

## 21. Minimal Reproducible Example

Create a directory `my_project` with:

### `rtl/adder.v`
```verilog
module adder (
    input  wire [3:0] a,
    input  wire [3:0] b,
    output wire [3:0] sum,
    output wire       cout
);
    assign {cout, sum} = a + b;
endmodule
```

### `tb/tb_adder.v`
```verilog
`timescale 1ns/1ps
module tb_adder;
    reg  [3:0] a, b;
    wire [3:0] sum;
    wire       cout;

    adder dut (.a(a), .b(b), .sum(sum), .cout(cout));

    initial begin
        $display("=== TESTBENCH_START ===");
        a = 4'd2; b = 4'd3; #10;
        if (sum === 4'd5 && cout === 1'b0) begin
            $display("=== TESTBENCH_SUMMARY: total=1 pass=1 fail=0 ===");
        end else begin
            $display("=== TESTBENCH_SUMMARY: total=1 pass=0 fail=1 ===");
        end
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
```

### `references/golden_adder.csv`
```csv
a,b,expected_sum,expected_cout
2,3,5,0
F,1,0,1
```

### `config.json`
```json
{
  "project_name": "Minimal Adder Example",
  "simulator": "icarus",
  "reference_sources": {
    "primary": {
      "name": "golden_adder",
      "path": "references/golden_adder.csv",
      "priority": 1,
      "type": "direct_io_table",
      "format": "csv",
      "radix": "hex",
      "input_mapping": {"a": "a", "b": "b"},
      "output_mapping": {"expected_sum": "sum", "expected_cout": "cout"},
      "timing": {"mode": "combinational", "settling_time_ns": 5.0}
    }
  }
}
```

Run:
```powershell
rtl-framework run --project ./my_project --config ./my_project/config.json --force
```
Both Path A (`PASS_TESTBENCH_ONLY`) and Path B (`PASS_REFERENCE_VERIFIED`) will verify and report clean passes!
