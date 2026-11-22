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
- **Icarus Verilog** (`iverilog`, `vvp`): Primary supported open-source simulator (v11.0 or v12.0). Active default engine for simulation.
- **Siemens Questa / ModelSim** (`vlib`, `vlog`, `vsim`): Commercial IEEE 1800 SystemVerilog simulator. Supported with automated license serialization.
- **Edalize** (Experimental): Generates standardized EDAM build configuration manifests (`edam.json`); simulation execution falls back to native Icarus Verilog.
- **Verilator** (Extension Stub): Adapter interface stub defined in `executor.py` for future integration; not currently implemented for active simulation.

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

## 14. Reference Data Formats & The LUT/Reference Distinction

### The Critical Architectural Distinction: Simulation Dependencies vs. Reference Oracles

The framework maintains a strict architectural boundary between two distinct categories of data files:

1. **Category A: Simulation Dependencies (Testbench LUTs / Memory Files)**:
   - When an existing Verilog testbench loads a data table or memory via `$readmemh` or `$readmemb` (e.g., `$readmemh("counter_ref.mem", memory);`), that file is a **simulation dependency**.
   - The framework automatically discovers and attaches these files to the compilation directory so the testbench executes under Path A without missing file errors.
   - **Integrity Rule**: A testbench memory dependency does **NOT** automatically become an independent reference oracle. It does not provide external differential verification.

2. **Category B: Independent Golden Reference Oracles (Path B Reference Tables)**:
   - A Path B reference table is explicitly declared in `config.json` under `reference_sources`.
   - It defines explicit port bindings (`input_mapping` and `output_mapping`), is loaded by `ReferenceDataLoader`, driven into the DUT via a generated dynamic test harness, and independently audited bit-for-bit against captured hardware outputs by the Python scoreboard.

### Supported Reference Table Formats for Path B
Path B strictly supports structured tabular formats with direct input/output column mappings:
1. **CSV Tables (`.csv`)**:
   - Header row must contain the column names specified in `input_mapping` and `output_mapping`.
   - Each row defines one test vector. Missing columns, empty cells, non-numeric literals, negative values, and numbers exceeding configured DUT port bitwidths are strictly rejected.
2. **JSON Datasets (`.json`)**:
   - Array of vector objects (or `{"vectors": [...]}`) where each object contains the exact keys mapped in `input_mapping` and `output_mapping`.
3. **Columnar Memory / Table Files (`.mem`, `.hex`, `.table`)**:
   - Space- or tab-delimited text files where tokens on each data line correspond in order to all configured inputs followed by all configured expected outputs: `<in_0> <in_1> ... <out_0> <out_1> ...`.
   - Lines beginning with `//` (comments) and `@` (memory address offsets) are skipped.
   - **Exact Column Format**: Path B expects direct column-to-port alignment. The framework does **NOT** claim arbitrary interpretation of arbitrary internal testbench ROM structures, state tables, or microcode memories.
4. **Radix Options**: `hex` (default, hex strings like `1A`, `0x1A`), `dec` (decimal integers), or `bin` (binary strings).

---

## 15. Generic External Lookup-Table & URL Reference Integration

Researchers can supply external URLs containing reference data. The framework automatically retrieves, validates, caches, and connects supported reference sources into the verification pipeline.

### Supported URL Reference Formats
- **Direct CSV Download URLs**: Static CSV files fetched via `http://`, `https://`, or `file://`.
- **Direct JSON Download URLs**: JSON vector lists or objects with a `"vectors"` array.
- **Static HTML Tables**: HTML specification documents parsed via `HTMLTableExtractor` (zero third-party dependencies) selecting tables by `table_id` or 0-based `table_index`.
- **Downloadable Reference Files**: Memory and hex vector files.

### Configuration Schema
In `config.json` under `reference_sources`:
```json
{
  "reference_sources": {
    "primary": {
      "priority": 1,
      "type": "direct_io_table",
      "url": "http://127.0.0.1:8080/truth_table.html",
      "format": "html_table",
      "table_id": "priority_encoder_table",
      "radix": "hex",
      "input_mapping": {
        "req_in": "req"
      },
      "output_mapping": {
        "grant_out": "grant",
        "valid_out": "valid"
      },
      "offline": false
    }
  }
}
```

### Automation vs. Researcher Responsibility Boundary
- **What the Framework Does Automatically**:
  - Validates URL syntax and performs HTTP/HTTPS/file retrieval.
  - Automatically isolates and extracts the specified `<table>` element from HTML without external scrapers.
  - Normalizes extracted rows and validates column presence against configured port mappings.
  - Computes SHA-256 cryptographic checksums and stores snapshots in `.reference_cache/` alongside provenance metadata (`.meta.json`).
  - Detects if remote source content changed across runs.
  - Generates the dynamic verification harness, captures actual DUT outputs, and executes the vector scoreboard.
- **What the Researcher Must Configure**:
  - Source URL and expected format (`csv`, `json`, `html_table`).
  - Table identifier (`table_id`) or index (`table_index`) when extracting from HTML.
  - Port column mappings (`input_mapping` and `output_mapping`).
  - Expected numerical radix (`hex`, `dec`, or `bin`).

### Direct I/O Oracle vs. Decoding LUT Semantics
- **Direct I/O Table**: Columns correspond directly to DUT input stimulus and expected output signals. Driven directly through Path B.
- **Decoding Lookup Table (e.g., Posit)**: Maps encoded bitstrings to numeric interpretations. A decoding LUT does not constitute an operational oracle for complex operations (e.g., multiplication). The framework exposes the cached snapshot to an optional project-specific `ReferenceProvider` extension, keeping domain-specific arithmetic outside the generic core.

### Limitations of Arbitrary Websites
The built-in `HTMLTableExtractor` parses standard HTML `<table>` structures. It does **not** execute client-side JavaScript, evaluate Single Page Applications (SPAs), solve CAPTCHAs, or parse dynamic calculators. For interactive or dynamic pages, researchers should export the data or write an explicit `ReferenceProvider` extension.

---

## 16. Optional Extension Interface

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

## 17. CLI Reference

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

## 18. Generated Reports

Every run produces structured artifacts inside the configured `reports/` folder:
- **`regression_report.html`**: Interactive HTML dashboard with status badges, execution metrics, and expandable vector failure diagnostic tables.
- **`regression_summary.csv`**: Tabular CSV export of plan IDs, DUTs, testbenches, status, cache outcomes, vector counts, and elapsed times.
- **`regression_summary.json`**: Machine-readable JSON summary of all plan results, active configurations, and failing vector diagnostics.
- **`history.jsonl`**: Append-only log enabling historical run comparisons and CLI replay.

---

## 19. Result Interpretation

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

## 20. Troubleshooting

- **`iverilog: command not found`**: Ensure Icarus Verilog (`iverilog.exe`, `vvp.exe`) is installed and on your system `PATH`.
- **`Interface Error: Port width mismatch`**: Check DUT and testbench port declarations. The framework enforces strict bit-width matching.
- **`Testbench sentinels missing`**: For Path A, include `$display("=== TESTBENCH_START ===");` and `$display("=== TESTBENCH_DONE ===");` in your testbench.
- **`Unknown 'x' output detected`**: Ensure all registers in sequential designs are properly initialized on reset.

---

## 21. Current Limitations

- **SystemVerilog Language Subset**: Supports synthesizable Verilog (IEEE 1364) and synthesizable SystemVerilog (IEEE 1800). Advanced OOP SystemVerilog class testbenches (e.g., full UVM VIP environments) require pre-compiled execution.
- **Clock Domains for Dynamic Harnesses**: Path B automated harness generation supports single-clock synchronous designs. Multi-clock domain (CDC) architectures require user-provided Path A testbenches.
- **Simulator Backends**: Native simulation execution is fully implemented and tested for Icarus Verilog and Siemens Questa. Edalize is supported for EDAM manifest export with native Icarus fallback, and Verilator is currently an extension stub for future integration.
- **Reference Table Formats**: Path B requires structured CSV, JSON, or strictly column-aligned MEM tables; it does not claim arbitrary reverse-engineering or interpretation of arbitrary internal testbench memories.

---

## 22. Minimal Reproducible Example

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
