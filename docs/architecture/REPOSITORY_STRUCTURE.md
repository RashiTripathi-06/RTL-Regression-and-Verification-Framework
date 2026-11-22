# Repository Structure & Architectural Reorganization Specification

## 1. Executive Summary & Architectural Motivation

The **RTL Regression and Verification Framework** has evolved from an ad-hoc multi-file project into a clean, modular, project-independent verification system. To ensure high maintainability, professional presentation, and compliance with strict project-independence principles, the repository has been restructured into standardized functional layers.

### Key Architectural Tenets
1. **Universal Framework Isolation (`src/`)**: The core framework code has zero domain-specific or project-specific hardcoding (e.g., no references to Posit, ALU, or MAC specifics). It operates strictly on discovered HDL metadata and declarative JSON configuration.
2. **First-Class Modular Examples (`examples/`)**: Demonstration designs (`generic_alu`, `synthetic_mac`, and `posit_multiplier`) are isolated standalone sub-projects containing their own RTL, testbenches, reference vectors, and documentation.
3. **Formal Reference Hierarchy (`references/`)**: Verification datasets are strictly partitioned into authoritative `references/golden/` (for simulation-driven Path B scoring) and `references/secondary/` (for static lookup tables, memory contents, and specifications).
4. **Categorized Test Engineering (`tests/`)**: Test suites are partitioned into `unit/`, `integration/`, and `regression/` packages, enabling fine-grained CI/CD targets.
5. **Separation of Evidence (`reports/final/`) vs. Ephemeral Artifacts**: Ephemeral simulation outputs and work directories are untracked, while cryptographic validation logs, manifests, and technical reports are preserved.

---

## 2. Before-and-After Repository Layout

### Before Restructuring (Flat & Interleaved)
```
dop2/
├── 8bit_encoder.v, adder.v, f_multiplier.v, ... (19 loose Posit RTL/TB files in root)
├── AUDIT_BASELINE.md, FINAL_DEMO_GUIDE.md, ... (9 loose markdown reports in root)
├── config.posit.json (stale loose configuration)
├── lookup_table.txt, T_LEAP code.txt (loose reference/doc files)
├── tb/
│   ├── adder_lut.mem, counter_ref.mem
│   ├── golden_adder.csv, golden_adder.json
│   ├── posit_mult_corners.csv, posit_mult_sample.csv
│   └── tb_adder.v, tb_counter.v, tb_alu.v
├── tests/
│   └── (21 flat test_*.py files)
├── src/ (18 universal framework modules)
└── configs/ (external json configs)
```

### After Restructuring (Professional, Modular & Clean)
```
RTL-Regression-and-Verification-Framework/
│
├── src/                                  # Universal, Project-Independent Core Framework
│   ├── auditor.py                        # Output validation & mismatch analyzer
│   ├── cache_manager.py                  # Cryptographic SHA-256 Merkle caching
│   ├── dependency_resolver.py            # AST-driven module dependency graph
│   ├── edalize_adapter.py                # Edalize EDAM specification adapter
│   ├── engine.py                         # Top-level regression engine & CLI runner
│   ├── executor.py                       # Simulator adapters (Icarus, Questa, Edalize)
│   ├── matcher.py                        # DUT-to-testbench compatibility matcher
│   ├── models.py                         # Verification plan, result, & status data models
│   ├── mutator.py                        # MANTRA2 Verilog AST mutation engine
│   ├── parser.py                         # Tree-sitter Verilog/SystemVerilog AST parser
│   ├── planner.py                        # Testbench dependency & data file planner
│   ├── reference_manager.py              # Multi-source reference resolver & arbiter
│   ├── reference_verifier.py             # Path B independent simulation harness
│   ├── report_generator.py               # HTML dashboard, CSV, and JSON reporter
│   ├── run_history_recorder.py           # Structured JSONL run history recorder
│   ├── scanner.py                        # Recursive project & module discovery
│   ├── static_analyzer.py                # Synthesizability, latches, & multi-driver checks
│   └── wrapper_generator.py              # Non-ANSI / port adapter wrapper generator
│
├── plugins/                              # Optional Domain-Specific Plugins
│   └── posit/
│       ├── __init__.py
│       └── posit_model.py                # Posit<16, 2> reference model & LUT parser
│
├── examples/                             # Standalone Demonstration Projects
│   ├── generic_alu/                      # Benchmark 1: Combinational 8-bit ALU
│   │   ├── alu8.v
│   │   ├── tb_alu8.v
│   │   ├── golden_alu8.csv
│   │   └── config.json
│   ├── synthetic_mac/                    # Benchmark 2: Sequential MAC Unit
│   │   ├── rtl/mac_unit.v
│   │   ├── tb/tb_mac_unit.v
│   │   ├── ref/golden_mac.csv
│   │   └── config.json
│   └── posit_multiplier/                 # Benchmark 3: 16-bit Posit Multiplier
│       ├── rtl/                          # 18 Modular Verilog RTL files
│       │   ├── multiplier.v              # Top-level logarithmic approximate multiplier
│       │   ├── posit_decoder.v           # Sign/regime/exponent/fraction decoder
│       │   ├── PLAM.v                    # Piecewise Linear Approximation core
│       │   ├── f_multiplier.v            # Logarithmic core with leading-one detector
│       │   ├── posit_encoder.v           # Posit packing unit
│       │   └── (supporting modules)
│       ├── tb/
│       │   └── tb_multiplier.v           # 65,536-cycle sweep testbench
│       ├── ref/
│       │   └── posit_mult_corners.csv    # 144 corner test vectors
│       ├── docs/
│       │   └── T_LEAP code.txt           # Architectural documentation
│       ├── README.md
│       └── config.json
│
├── configs/                              # External Declarative Configuration Files
│   ├── generic_alu.json
│   ├── synthetic_mac.json
│   └── posit_multiplier.json
│
├── references/                           # Authoritative Reference Datasets
│   ├── golden/                           # Primary Verification Datasets (Path B Oracles)
│   │   ├── golden_adder.csv              # Full-adder comprehensive truth table
│   │   ├── golden_adder.json
│   │   ├── posit_mult_corners.csv        # 144 corner test vectors for Posit<16, 2>
│   │   └── posit_mult_sample.csv
│   └── secondary/                        # Secondary References (LUTs, Docs, Memory)
│       ├── adder_lut.mem                 # Verilog $readmemh memory file
│       ├── counter_ref.mem               # 4-bit up/down counter reference sequence
│       └── lookup_table.txt              # Posit<16, 2> 65,536-entry bit-to-float table
│
├── tests/                                # Multi-Tier Automated Test Suite
│   ├── unit/                             # Isolated Component Tests (10 modules)
│   │   ├── test_auditor.py
│   │   ├── test_cache.py
│   │   ├── test_dependency.py
│   │   ├── test_matcher.py
│   │   ├── test_mutator.py
│   │   ├── test_parser.py
│   │   ├── test_posit_model.py
│   │   ├── test_questa_adapter.py
│   │   ├── test_reference_manager.py
│   │   └── test_wrapper_validation.py
│   ├── integration/                      # Feature & Cross-Module Tests (9 modules)
│   │   ├── test_advanced_features.py
│   │   ├── test_adversarial.py
│   │   ├── test_cache_invalidation_comprehensive.py
│   │   ├── test_deep_dependencies.py
│   │   ├── test_filename_invariance.py
│   │   ├── test_generic_family.py
│   │   ├── test_interface_verification.py
│   │   ├── test_lut_association.py
│   │   └── test_reference_verifier.py
│   └── regression/                       # End-to-End Suite & Replay (2 modules)
│       ├── test_end_to_end.py
│       └── test_reproducibility.py
│
├── scripts/                              # Reproducibility & Audit Utilities
│   ├── audit_mutation_testing.py         # MANTRA2 mutation analysis & score comparison
│   ├── audit_posit_21_mismatches.py      # Posit 21-mismatch hardware root cause audit
│   ├── evaluate_tools.py                 # Toolchain evaluation script
│   ├── generate_posit_references.py      # Posit reference vector generator
│   ├── reorganize_tests.py               # Test suite restructuring utility
│   ├── validate_cache_and_replay.py      # Cache invalidation & replay validator
│   ├── validate_path_a_and_b.py          # Dual-path verification demonstration
│   ├── validate_posit_model_independent.py # Plugin isolation verifier
│   ├── validate_questa_adapter.py        # Siemens Questa toolchain verifier
│   └── verify_project_independence_manifest.py # SHA-256 bit-invariance verifier
│
├── docs/                                 # Architectural & Technical Documentation
│   ├── architecture/
│   │   ├── FINAL_REFERENCE_MANAGEMENT_ARCHITECTURE.md
│   │   ├── FINAL_LUT_PIPELINE_AUDIT.md
│   │   └── REPOSITORY_STRUCTURE.md
│   ├── validation/
│   │   ├── AUDIT_BASELINE.md
│   │   ├── FINAL_IMPLEMENTATION_VALIDATION_REPORT.md
│   │   ├── FINAL_REFERENCE_VALIDATION_REPORT.md
│   │   └── FINAL_VALIDATION_REPORT.md
│   ├── demonstrations/
│   │   └── FINAL_DEMO_GUIDE.md
│   └── research/
│       ├── FINAL_TECHNICAL_REPORT.md
│       └── RESEARCH_AND_TOOL_EVALUATION.md
│
├── reports/
│   └── final/                            # Preserved Validation Logs & Manifests
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
│   ├── adder_behavioral.v
│   ├── adder_buggy.v
│   ├── adder_cla.v
│   ├── adder_rca.v
│   ├── alu_4bit.v
│   ├── counter_updown_4bit.v
│   └── ...
│
├── tb/                                   # Built-in Generic Testbenches
│   ├── tb_adder.v
│   ├── tb_counter.v
│   └── tb_alu.v
│
├── .gitignore                            # Clean git exclusion rules
├── README.md                             # High-level project entry point
├── requirements.txt                      # Minimum package dependencies
└── run_demo.ps1                          # Automated one-click demonstration script
```

---

## 3. Directory Roles & Isolation Guarantees

| Directory | Role | Isolation Guarantee |
|---|---|---|
| `src/` | Universal Verification Engine | Contains ZERO hardcoded module names, port names, or benchmark logic. |
| `plugins/` | Optional domain-specific models | Standalone package. Framework runs cleanly if `plugins/` is deleted. |
| `examples/` | Standalone target projects | Each subproject contains all necessary RTL, TB, and configs. |
| `configs/` | Declarative project configurations | Bridges generic engine to specific project parameters. |
| `references/` | Golden vectors & secondary tables | Partitioned between directly verifiable vectors and raw data. |
| `tests/` | Unit, integration & regression tests | Tests run independently via standard unittest discovery. |
| `docs/` | Comprehensive technical documentation | Grouped into Architecture, Validation, Demos, and Research. |
| `reports/final/` | Immutable verification evidence | Tracked in Git; contains signed logs and SHA-256 manifests. |

---

## 4. Execution Commands

### Run Full Test Suite (Unit + Integration + Regression)
```bash
python -u -m unittest discover -s tests -p "test_*.py" -v
```

### Run Specific Test Categories
```bash
# Unit tests only
python -u -m unittest discover -s tests/unit -p "test_*.py" -v

# Integration tests only
python -u -m unittest discover -s tests/integration -p "test_*.py" -v

# Regression tests only
python -u -m unittest discover -s tests/regression -p "test_*.py" -v
```

### Run Demonstration Benchmarks
```bash
# Benchmark 1: Generic ALU
python src/engine.py --project-dir examples/generic_alu --config configs/generic_alu.json --force

# Benchmark 2: Synthetic MAC
python src/engine.py --project-dir examples/synthetic_mac --config configs/synthetic_mac.json --force

# Benchmark 3: Posit Multiplier
python src/engine.py --project-dir examples/posit_multiplier --config configs/posit_multiplier.json --force
```

### Verify SHA-256 Bit-for-Bit Source Invariance
```bash
python scripts/verify_project_independence_manifest.py
```
