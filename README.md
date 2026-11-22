# Automated RTL Regression and Verification Framework

A modular, reproducible, project-independent RTL regression and verification framework for supported Verilog/SystemVerilog digital designs.

---

## 1. Project Overview and Problem Statement

Modern digital design verification frequently suffers from fragile, ad-hoc regression scripts tightly coupled to specific Device Under Test (DUT) interfaces and custom testbench conventions. Traditional verification flows in academic and exploratory research environments often exhibit critical shortcomings:
- **Conflation of Execution and Verification**: A testbench completing with returncode 0 is often reported as a "pass," even if it contained zero self-checking assertions or only checked for non-`X` values.
- **Intrusive Test Harnesses**: Modifying original RTL or hand-editing testbenches to fit regression harnesses introduces synthetic artifacts, risks introducing testbench bugs, and violates project-independence.
- **Lack of Independent Reference Oracles**: Self-checking testbenches often share assumptions with the RTL author. Independent verification requires external golden references (Path B) evaluated alongside native testbenches (Path A).
- **Brittle Caching and Reproducibility**: Changes to nested submodules, include headers, or simulator versions often go undetected by naive timestamp-based build systems, causing stale verification results.

This framework solves these challenges by providing an automated, non-invasive intake pipeline that discovers Verilog/SystemVerilog modules, resolves AST-level submodule dependencies, infers non-invasive port adapters where necessary, executes native testbenches (Path A), and independently evaluates DUT outputs against external golden references (Path B).

---

## 2. Supported Scope and Explicit Limitations

### Supported Scope
> **Project-independent RTL verification for supported Verilog/SystemVerilog project structures, with external configuration for project-specific verification requirements.**

The framework operates strictly on discovered HDL metadata and declarative JSON configuration. The universal `src/` framework contains zero domain-specific or project-specific hardcoding (e.g., no Posit arithmetic, no ALU opcodes, and no hardcoded module names).

### Explicit Limitations
- **HDL Language Subset**: Fully supports Verilog (IEEE 1364-2001/2005) and synthesizable subsets of SystemVerilog (IEEE 1800) discoverable via Tree-Sitter AST parsing. Advanced SystemVerilog OOP constructs, complex randomized class-based testbenches (e.g., full UVM VIP environments), and encrypted IP cores are outside current parsing scope.
- **Project Structure**: Designed for modular, file-discoverable Verilog/SystemVerilog hierarchies. Non-standard proprietary build flows, external C/C++ DPI wrappers, or mixed VHDL/Verilog hierarchies require custom external wrappers or plugin extensions.
- **Sequential Reference Verification**: Path B dynamic sequential harness generation currently supports synchronous single-clock, single-reset designs with deterministic latency. Multi-clock domain (CDC) architectures, asynchronous handshake protocols, and non-deterministic bus interfaces require custom testbenches (evaluated via Path A).
- **Universal HDL Compatibility Not Claimed**: The framework does NOT claim compatibility with all possible arbitrary HDL codebases without configuration.

---

## 3. Architecture and Execution Flow

The regression engine operates across an automated multi-stage pipeline:

```text
[HDL Sources & TBs] ──> 1. Scanner (Recursive Discovery)
                              │
                        2. AST Parser (Ports, Parameters, Instances)
                              │
                        3. Dependency Resolver (Topological Ordering & Cycle Detection)
                              │
                        4. Matcher & Wrapper Generator (Compatibility Scoring)
                              │
                        5. Planner (Data Binding & Plan Creation)
                              │
         ┌────────────────────┴────────────────────┐
         ▼                                         ▼
   [Path A: Native TB]                       [Path B: Independent Reference]
   - Isolated simulation                     - Multi-Source Reference Resolver
   - Log auditing (sentinels, UVM, X/Z)      - Dynamic SV harness generation
   - Assertion qualification                 - Stimulus drive & output sampling
         │                                   - Python vector scoreboard
         └────────────────────┬────────────────────┘
                              ▼
                        6. Auditor & Classifier (Strict Status Assignment)
                              ▼
                        7. Merkle Cache Manager (SHA-256 Incremental Replay)
                              ▼
                        8. Report Generator (HTML Dashboard, CSV, JSON, History)
```

1. **Discovery (`scanner.py`)**: Recursively discovers HDL sources (`.v`, `.sv`), includes (`.vh`, `.svh`), and reference data files (`.csv`, `.json`, `.mem`, `.hex`, `.dat`).
2. **Parsing & Analysis (`parser.py`, `static_analyzer.py`)**: Extracts module interfaces, port directions, bit-widths, parameters, and checks for latches or multi-driven nets.
3. **Dependency Resolution (`dependency_resolver.py`)**: Builds a directed acyclic graph (DAG) of submodule instantiations to ensure correct compile-order.
4. **Matching & Wrapping (`matcher.py`, `wrapper_generator.py`)**: Matches DUTs to testbenches using exact-name, interface-compatibility, and heuristic scoring. Synthesizes non-invasive wrappers if port naming or ANSI conventions differ.
5. **Planning (`planner.py`)**: Binds required reference memory files and stages files in isolated execution directories.
6. **Execution (`executor.py`)**: Runs simulations in isolated worker directories with watchdog timeout enforcement.
7. **Reference Verification (`reference_manager.py`, `reference_verifier.py`)**: Resolves hierarchical references (Case 1–4) and executes Path B scoreboard verification.
8. **Auditing (`auditor.py`)**: Categorizes outcomes into strict status classifications based on exit codes, sentinels, and vector matching.
9. **Caching (`cache_manager.py`)**: Computes cryptographic Merkle hashes covering all source files, include trees, datasets, compiler flags, and simulator versions.
10. **Reporting (`report_generator.py`)**: Outputs unified HTML dashboard, CSV summaries, JSON diagnostics, and appends to run history.

---

## 4. Repository Directory Tree

The repository strictly separates universal framework logic, project-specific plugins, external configurations, and standalone demonstration examples:

```text
RTL-Regression-and-Verification-Framework/
│
├── src/                                  # Universal, Project-Independent Core Framework (16 modules)
│   ├── __init__.py                       # Package initializer
│   ├── auditor.py                        # Semantic log audit, UVM/assertion detection, sentinel check
│   ├── cache_manager.py                  # Cryptographic SHA-256 Merkle regression cache
│   ├── dependency_resolver.py            # AST-driven dependency DAG and topological compilation order
│   ├── engine.py                         # Top-level regression engine & CLI runner
│   ├── executor.py                       # Simulator adapters (Icarus, Questa, Edalize EDAM, Verilator)
│   ├── matcher.py                        # Confidence-based DUT-to-testbench compatibility matcher
│   ├── models.py                         # Core data classes (VerificationPlan, TestResult, PortSpec, etc.)
│   ├── mutator.py                        # MANTRA2-compliant Verilog AST mutation engine
│   ├── parser.py                         # Tree-sitter Verilog/SystemVerilog AST parser
│   ├── planner.py                        # Test plan generation & testbench reference file binding
│   ├── reference_manager.py              # Multi-source reference resolver & conflict arbiter
│   ├── reference_verifier.py             # Path B independent simulation harness & scoreboard
│   ├── report_generator.py               # Dashboard synthesis (HTML, CSV, JSON, history.jsonl)
│   ├── scanner.py                        # Recursive project & module discovery
│   ├── static_analyzer.py                # Static RTL checks (latches, multi-driven nets, width mismatches)
│   └── wrapper_generator.py              # Non-ANSI / port adapter wrapper synthesis
│
├── plugins/                              # Optional Project-Specific Plugins (External to src/)
│   ├── adder/                            # Adder demonstration reference generator
│   │   ├── __init__.py
│   │   └── generate_lut.py               # Golden adder lookup-table generator
│   └── posit/                            # Posit arithmetic model plugin
│       ├── __init__.py
│       └── posit_model.py                # Standalone Posit<16, 2> reference model & LUT parser
│
├── examples/                             # Standalone Demonstration Subprojects
│   ├── generic_alu/                      # Benchmark 1: Combinational 8-bit ALU
│   │   ├── alu8.v, tb_alu8.v, golden_alu8.csv, config.json
│   ├── synthetic_mac/                    # Benchmark 2: Sequential MAC Unit
│   │   ├── rtl/mac_unit.v, tb/tb_mac_unit.v, ref/golden_mac.csv, config.json
│   └── posit_multiplier/                 # Benchmark 3: 16-bit Posit Multiplier
│       ├── rtl/                          # 18 Modular Verilog RTL files (T-LEAP architecture)
│       ├── tb/tb_multiplier.v           # 65,536-cycle sweep testbench
│       ├── ref/posit_mult_corners.csv    # 144 corner test vectors
│       ├── docs/T_LEAP code.txt          # Architectural documentation
│       ├── README.md
│       └── config.json
│
├── configs/                              # External Declarative Configurations
│   ├── generic_alu.json                  # Generic ALU configuration
│   ├── synthetic_mac.json                # Synthetic sequential MAC configuration
│   └── posit_multiplier.json             # Posit multiplier benchmark configuration
│
├── references/                           # Authoritative Reference Datasets
│   ├── golden/                           # Primary verification datasets (Path B oracles)
│   │   ├── golden_adder.csv              # 512-entry comprehensive full-adder truth table
│   │   ├── golden_adder.json
│   │   ├── posit_mult_corners.csv        # 144 corner test vectors for Posit<16, 2>
│   │   └── posit_mult_sample.csv         # 256 representative sweep points
│   └── secondary/                        # Secondary reference material (LUTs, documentation)
│       ├── adder_lut.mem                 # Verilog memory file ($readmemh)
│       ├── counter_ref.mem               # 4-bit up/down counter reference sequence
│       └── lookup_table.txt              # Official Posit<16, 2> bit-to-float decoding table
│
├── tests/                                # Multi-Tier Automated Test Suite (99 tests)
│   ├── unit/                             # Component isolation tests (10 modules)
│   ├── integration/                      # Cross-module feature tests (9 modules)
│   └── regression/                       # End-to-end regression & cache replay (2 modules)
│
├── scripts/                              # Reproducibility, Mutation, and Audit Utilities
│   ├── audit_mutation_testing.py         # MANTRA2 mutation analysis & score comparison
│   ├── audit_posit_21_mismatches.py      # Posit 21-mismatch hardware root-cause auditor
│   ├── evaluate_tools.py                 # Toolchain evaluation utility
│   ├── generate_posit_references.py      # Reference vector generation script
│   ├── legacy_regression_prototype.py    # Archived legacy prototype
│   ├── reorganize_tests.py               # Test categorization utility
│   ├── show_diagnostics.py               # CLI failing-vector inspector
│   ├── validate_cache_and_replay.py      # Cryptographic cache validation script
│   ├── validate_path_a_and_b.py          # Dual-path verification demonstration
│   ├── validate_posit_model_independent.py # Plugin isolation verifier
│   ├── validate_questa_adapter.py        # Siemens Questa toolchain verifier
│   └── verify_project_independence_manifest.py # SHA-256 bit-for-bit source invariance verifier
│
├── docs/                                 # Technical Documentation & Architectural Specifications
│   ├── architecture/                     # System design, LUT pipeline, repository structure
│   ├── validation/                       # Baseline audits and validation reports
│   ├── demonstrations/                   # Step-by-step reproduction guide
│   └── research/                         # Technical reports and tool evaluations
│
├── reports/
│   └── final/                            # Preserved Validation Evidence, Logs & Manifests
│       ├── cache_replay_validation.md
│       ├── cross_project_reproducibility.md
│       ├── full_test_suite.log
│       ├── mutation_analysis.json
│       ├── mutation_analysis.md
│       ├── path_a_demonstration.md
│       ├── path_b_demonstration.md
│       ├── posit_reference_validation.md
│       ├── project_independence_validation.md
│       ├── questa_validation.log
│       ├── source_integrity_manifest.json
│       └── source_integrity_manifest.md
│
├── designs/                              # Built-in Generic RTL Test Family
│   ├── adder_behavioral.v, adder_buggy.v, adder_cla.v, adder_rca.v
│   ├── alu_4bit.v, counter_updown_4bit.v, counter_faulty.v, multiplier_4bit.v
│   └── ...
│
├── tb/                                   # Built-in Generic Testbenches
│   ├── tb_adder.v, tb_adder_random.v, tb_counter.v, tb_alu.v
│
├── .gitignore                            # Clean git exclusion rules
├── README.md                             # High-level project entry point
├── requirements.txt                      # Minimum package dependencies
└── run_demo.ps1                          # PowerShell demonstration runner
```

> **Note on Implementation Structure:**
> - There is no separate `src/edalize_adapter.py`; Edalize EDAM integration is implemented in `src/executor.py`.
> - History recording is handled directly by `engine.py` and `report_generator.py`.
> - All project-specific models (`posit_model.py`, `generate_lut.py`) reside strictly in `plugins/`.

---

## 5. Responsibilities of Universal `src/` Modules

| Module | Core Responsibility |
|---|---|
| `auditor.py` | Audits simulation stdout/stderr for explicit pass/fail sentinels, UVM errors, SystemVerilog assertions, and unknown (`x`/`z`) states. |
| `cache_manager.py` | Constructs SHA-256 Merkle trees of design files, dependencies, includes, references, and compiler options for instant replay. |
| `dependency_resolver.py` | Resolves hierarchical module instantiations, detects circular dependencies, and computes top-level elaboration order. |
| `engine.py` | Main orchestration engine coordinating scanning, matching, execution, reference verification, and reporting. |
| `executor.py` | Subprocess abstraction managing Icarus Verilog, Siemens Questa, Edalize EDAM generation, and Verilator execution. |
| `matcher.py` | Determines compatibility between DUTs and testbenches via exact name, port signature matching, and heuristic alignment. |
| `models.py` | Typed dataclasses defining plans, results, port specifications, evidence tokens, and status enumerations. |
| `mutator.py` | Implements MANTRA2 mutation operators (AOR, BOR, OI, CS, COA, ROR, SOR) on Verilog ASTs to evaluate testbench effectiveness. |
| `parser.py` | Tree-Sitter AST parser extracting module declarations, ANSI/non-ANSI ports, parameters, and hierarchical instantiations. |
| `planner.py` | Synthesizes verified execution plans, binds relevant data/LUT files, and flags missing or unused reference files. |
| `reference_manager.py` | Evaluates multi-source reference configurations (Case 1–4), performs cross-validation, and flags disputed or unavailable oracles. |
| `reference_verifier.py` | Dynamically constructs standalone SystemVerilog test harnesses (`harness_<dut>.sv`) for Path B golden reference verification. |
| `report_generator.py` | Synthesizes structured HTML visual dashboards, summary CSV files, JSON diagnostics, and JSONL run history records. |
| `scanner.py` | Recursively walks workspace directories discovering RTL sources, header includes, and reference tables while ignoring license/cache files. |
| `static_analyzer.py` | AST-level static linter checking for unintended latch inference in combinational blocks, multi-driven nets, and port width mismatches. |
| `wrapper_generator.py` | Generates non-invasive SystemVerilog wrapper modules to adapt port naming, packing, or directional discrepancies between DUT and TB. |

---

## 6. Plugin Architecture and Project-Specific Separation

To preserve universal framework independence, all project-specific arithmetic, analytical models, and specialized test vector generators are decoupled into standalone plugins:
- **`plugins/posit/`**: Contains `posit_model.py`, a pure Python model of $\text{Posit}\langle 16, 2\rangle$ arithmetic, rounding, regime decoding, and numerical lookup table parsing.
- **`plugins/adder/`**: Contains `generate_lut.py`, a utility for generating full-adder truth tables.

The universal `src/` framework never imports, requires, or executes code from `plugins/` during ordinary operation. The framework interacts with projects solely through discovered HDL interfaces and external configuration files.

---

## 7. Configuration and Reference Dataset Structure

Projects declare their verification parameters via declarative JSON configurations:

```json
{
  "project_name": "Synthetic_MAC_Unit",
  "build_dir": "build",
  "reports_dir": "reports",
  "simulator": "icarus",
  "timeout_seconds": 5.0,
  "reference_sources": {
    "primary": {
      "name": "golden_mac",
      "path": "ref/golden_mac.csv",
      "priority": 1,
      "type": "direct_io_table",
      "format": "csv",
      "radix": "hex",
      "input_mapping": { "en": "en", "val_a": "val_a", "val_b": "val_b", "acc_base": "acc_base" },
      "output_mapping": { "expected_out": "mac_out", "expected_ovf": "ovf" },
      "timing": {
        "mode": "sequential",
        "clock_signal": "clk",
        "reset_signal": "rst_n",
        "reset_active_level": 0,
        "reset_duration_cycles": 2,
        "latency_cycles": 1,
        "clock_period_ns": 10.0
      }
    }
  }
}
```

### Deterministic Multi-Source Resolution Cases
1. **Case 1 (Primary Active)**: An authoritative direct I/O table is available and drives Path B verification. If a secondary direct table exists, cross-validation is performed.
2. **Case 2 (Fallback Active)**: The primary reference is missing or empty, but an executable secondary reference is elevated to active status.
3. **Case 3 (Disputed References)**: Primary and secondary references disagree on expected outputs. Status is flagged as `STATUS_REFERENCE_DISPUTED`, execution is halted, and conflicting vectors are logged.
4. **Case 4 (Unavailable Reference)**: References are non-executable (e.g., 1-D numerical decoding tables, mathematical specifications, or documentation PDFs) without external model adapters. Status is flagged as `STATUS_REFERENCE_UNAVAILABLE`, preventing erroneous test passes.

---

## 8. Test Organization

The automated test suite is partitioned into three directories:
- **`tests/unit/`**: 10 modules validating isolated framework units (`test_parser.py`, `test_matcher.py`, `test_cache.py`, `test_mutator.py`, `test_auditor.py`, `test_dependency.py`, `test_reference_manager.py`, `test_posit_model.py`, `test_questa_adapter.py`, `test_wrapper_validation.py`).
- **`tests/integration/`**: 9 modules evaluating multi-component interactions (`test_generic_family.py`, `test_reference_verifier.py`, `test_lut_association.py`, `test_advanced_features.py`, `test_cache_invalidation_comprehensive.py`, `test_interface_verification.py`, `test_deep_dependencies.py`, `test_adversarial.py`, `test_filename_invariance.py`).
- **`tests/regression/`**: 2 modules validating end-to-end framework execution (`test_end_to_end.py`) and reproducibility replay (`test_reproducibility.py`).

---

## 9. Installation and Dependencies

### Prerequisites
- **Python**: Version 3.10 or higher.
- **Simulators**:
  - **Icarus Verilog** (v11.0 or v12.0): Required for standard simulation (`iverilog`, `vvp` on system PATH).
  - **Siemens Questa / ModelSim** (Optional): Supported for commercial SystemVerilog simulation and strict ANSI port scoping checks.

### Install Python Dependencies
```bash
pip install -r requirements.txt
```
*Dependencies: `tree-sitter>=0.25.0`, `tree-sitter-verilog>=1.0.3`, `networkx>=3.0`.*

---

## 10. How to Run the Framework

### Standard Execution
```bash
# Run regression across default workspace
python src/engine.py

# Force re-execution bypassing cache
python src/engine.py --force

# Run with specific DUT filter
python src/engine.py --duts adder_rca adder_cla

# Run with external project directory and configuration
python src/engine.py --project-dir examples/generic_alu --config configs/generic_alu.json --force
```

### CLI Replay of Historical Runs
```bash
python src/engine.py --replay <RUN_ID>
```

---

## 11. How to Run Tests

### Run Full Test Suite
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run Specific Test Categories
```bash
# Run unit tests only
python -m unittest discover -s tests/unit -p "test_*.py" -v

# Run integration tests only
python -m unittest discover -s tests/integration -p "test_*.py" -v

# Run regression tests only
python -m unittest discover -s tests/regression -p "test_*.py" -v
```

---

## 12. Simulator Support and Integration Status

- **Icarus Verilog (`iverilog`, `vvp`)**: Fully integrated and active as default open-source simulation engine. Supports IEEE 1364-2001 and IEEE 1800-2012 features.
- **Siemens Questa / ModelSim (`vlib`, `vlog`, `vsim`)**: Fully implemented adapter with single-session concurrency mutex (`threading.Lock()`) for node-locked licenses (`SALT_LICENSE_SERVER`). Strictly enforces IEEE ANSI port scoping rules. *(Note: When executing inside restricted Windows sandboxes, direct invocation may be blocked by system DLL relocation security policies; un-sandboxed execution verifies cleanly).*
- **Edalize (`edalize`)**: `EdalizeSimulatorAdapter` in `src/executor.py` generates standard EDAM specification manifests (`edam.json`). Verified via `test_edalize_edam_generation`. *(Note: Successful EDAM generation establishes export compatibility; end-to-end execution through external EDA toolchains depends on local tool installation).*
- **Verilator**: Adapter interface present in `src/executor.py`.

---

## 13. Verification Result Classifications

The framework distinguishes execution status from functional verification:

| Classification | Meaning |
|---|---|
| `PASS_REFERENCE_VERIFIED` | DUT outputs strictly matched expected values from an independent external golden reference (Path B). |
| `PASS_TESTBENCH_ONLY` | Self-checking testbench assertions completed successfully (Path A), but no independent golden reference was evaluated. |
| `EXECUTED / NOT VERIFIED` | Simulation finished with returncode 0, but the testbench contained zero checks/assertions or only non-`X` checks. |
| `FUNCTIONAL FAIL` | Observed DUT outputs disagreed with golden reference vectors, or self-checking assertions reported mismatches. |
| `COMPILE ERROR` | HDL compilation or elaboration syntax failure (e.g., ANSI port re-declaration errors). |
| `INTERFACE ERROR` | Structural port width, port count, or port direction mismatch between DUT and testbench. |
| `TIMEOUT` | Simulation exceeded configured watchdog execution duration (e.g., infinite loop). |
| `INCOMPLETE` | Simulation exited prematurely before encountering expected end-of-test sentinels. |
| `INVALID RESULTS` | Uninitialized (`x`) or high-impedance (`z`) values detected on monitored output signals. |
| `REFERENCE_DISPUTED` | Primary and secondary reference sources disagree on expected outputs (Case 3). |
| `REFERENCE_UNAVAILABLE` | Declared reference is non-executable (e.g., 1-D decoding table or document) without an adapter model (Case 4). |
| `NO MATCH` | No candidate testbench found matching DUT port interface. |
| `AMBIGUOUS MATCH` | Multiple candidate testbenches matched ambiguously; rejected to avoid guessing. |
| `LICENSE ERROR` | Commercial simulator license checkout failure. |

---

## 14. Current Benchmark Demonstrations

### Benchmark 1: Generic 8-Bit ALU (`examples/generic_alu/`)
- **Type**: Combinational logic with opcode-decoded arithmetic and bitwise operations.
- **Path A**: `alu8 | tb_alu8 | EXECUTED / NOT VERIFIED | 0/0` (testbench finishes with rc=0 but has 0 assertion checks).
- **Path B**: `alu8 | harness_alu8 | PASS_REFERENCE_VERIFIED | 10/10` (golden CSV verified with 0 mismatches).

### Benchmark 2: Synthetic Sequential MAC Unit (`examples/synthetic_mac/`)
- **Type**: Synchronous sequential logic with active-low reset (`rst_n`), clock (`clk`), enable (`en`), and overflow (`ovf`).
- **Path A**: `mac_unit | tb_mac_unit | PASS_TESTBENCH_ONLY | 4/4` (self-checking assertions pass).
- **Path B**: `mac_unit | harness_mac_unit | PASS_REFERENCE_VERIFIED | 5/5` (dynamic harness drives clock/reset and independently scores vectors).

### Benchmark 3: 16-Bit Approximate Posit Multiplier (`examples/posit_multiplier/`)
- **Type**: Hierarchical arithmetic design implementing $\text{Posit}\langle 16, 2\rangle$ approximate multiplication via T-LEAP architecture.
- **Path A**: `multiplier | tb_multiplier | PASS_TESTBENCH_ONLY | 65536/65536` (65,536-cycle sweep completes with zero `x` states).
- **Path B**: `multiplier | harness_multiplier | FUNCTIONAL FAIL | 123/144` (catches 21 hardware bugs where RTL outputs deviate from mathematical Posit standards, such as zero-operand bypass failures).

### Proof of Zero Universal Source Modifications
Run [`scripts/verify_project_independence_manifest.py`](file:///d:/dop2/scripts/verify_project_independence_manifest.py) to compute SHA-256 cryptographic hashes for all 16 universal framework modules before and after running each benchmark:
```text
-> Manifest Check for 'Generic ALU':      100% UNCHANGED (0 diffs across all source files).
-> Manifest Check for 'Synthetic MAC':     100% UNCHANGED (0 diffs across all source files).
-> Manifest Check for 'Posit Multiplier':  100% UNCHANGED (0 diffs across all source files).
```

---

## 15. Known Limitations and Future Work

1. **SystemVerilog Interface & Package Support**: Highly complex packages containing parameterized class definitions and virtual interfaces are not fully parsed by the current Tree-Sitter grammar.
2. **Multi-Clock and Asynchronous Handshakes**: Path B harness generation is currently optimized for single-clock synchronous pipelines. Multi-clock domain (CDC) architectures require user-provided Path A testbenches.
3. **Direct Edalize Simulator Execution**: The Edalize integration currently focuses on generating valid EDAM manifests (`edam.json`). Full execution orchestration through Edalize backends requires additional toolchain-specific runtime configuration.
4. **VHDL Integration**: Parsing and dependency analysis for VHDL designs is not currently implemented; VHDL modules require external co-simulation or pre-compiled blackboxes.
