# RTL Verification and Regression Framework: Audit and Baseline Report (Phase 0)

**Project Workspace:** `D:\dop2`  
**Date:** 2026-11-21  
**Author:** Senior EDA Software Engineer & RTL Verification Architect  

---

## 1. Existing Architecture

The existing regression framework is organized into modular Python components:

```
[Discovery / Scanner]  -->  [Parser / AST]  -->  [Dependency Resolver]
        |                           |                     |
        v                           v                     v
[Candidate DUTs & TBs]  -->  [Matcher Heuristics]  -->  [Execution Planner]
                                                              |
                                                              v
[Cache Manager (Merkle Tree)] <--> [Simulator Executor (Icarus/Edalize/Verilator)]
                                                              |
                                                              v
[Auditor / Log & Ref Analysis] <--> [Static Lint Analyzer]
        |
        v
[Report Generator (CSV / HTML Dashboard)]
```

### Core Modules:
- **`src/models.py`**: Dataclasses for `PortSpec`, `InstanceInfo`, `ModuleInfo`, `CompatibilityEvidence`, `VerificationPlan`, `TestResult`, and simulation/audit status constants.
- **`src/scanner.py`**: `ProjectScanner` discovers HDL files (`.v`, `.sv`, `.vh`, `.svh`) and data files (`.mem`, `.hex`, `.dat`, `.csv`).
- **`src/parser.py`**: `TreeSitterVerilogParser`, `SlangCLIParser`, and fallback regex engine to parse module declarations, ports, parameter widths, instantiations, and signal usage.
- **`src/dependency_resolver.py`**: Recursive post-order DFS to build exact compilation file lists for hierarchical modules, detecting circular loops and missing dependencies.
- **`src/matcher.py`**: Multi-tiered heuristic matcher to connect DUTs with testbenches based on explicit manifests, instantiation signatures, port compatibility, and signal flow.
- **`src/planner.py`**: Constructs `VerificationPlan` objects with isolated build paths and required include/data files.
- **`src/wrapper_generator.py`**: Generates Verilog wrapper modules when port interfaces are identical but module names differ.
- **`src/executor.py`**: Executes simulations inside isolated build directories using simulator adapters (`IcarusSimulatorAdapter`, `EdalizeSimulatorAdapter`, `VerilatorSimulatorAdapter`).
- **`src/auditor.py`**: Parses simulator output streams to classify execution outcomes and check against `.mem` tables.
- **`src/cache_manager.py`**: Merkle-tree incremental cache based on SHA-256 hashes of DUT sources, dependencies, testbenches, and compiler flags.
- **`src/static_analyzer.py`**: Synthesizes AST checks for undriven nets, unassigned ports, and latches.
- **`src/report_generator.py`**: Emits `regression_summary.csv` and an interactive HTML report.
- **`src/engine.py`**: Main pipeline driver coordinating the complete verification cycle.

---

## 2. Existing Features That Work

1. **HDL File Discovery:** Traversal and classification of Verilog/SystemVerilog sources and include headers.
2. **Tree-Sitter Syntax Parsing:** Accurate extraction of ANSI and non-ANSI port declarations, parameters, and module hierarchy for standard designs.
3. **Multi-level Dependency Graph:** Post-order dependency sorting ensuring submodules compile before parents.
4. **Isolated Build Directories:** Each test execution uses a dedicated working folder (`build/<plan_id>`) preventing dirty state collisions.
5. **Icarus Verilog Adapter:** Compilation and simulation with `iverilog` and `vvp` using watchdog timeouts.
6. **Interface Wrapper Synthesis:** Automated generation and validation of interface translation wrappers for renamed top-level modules.
7. **Basic Merkle Caching:** SHA-256 content hashing to bypass re-executing unchanged plans in Icarus.
8. **Summary Reporting:** Generation of structured machine-readable CSV tables and HTML dashboards.

---

## 3. Existing Features That Are Incomplete

1. **Native Questa 2025.3 Adapter:** Completely absent. The existing framework only has Icarus, a Verilator stub, and an Edalize wrapper that falls back to Icarus. No native integration with `vlib`, `vlog`, or `vsim -c` exists.
2. **Licensing Architecture:** No support for validating `SALT_LICENSE_SERVER`, no detection of the user's node-locked single-session license (`LR-213236_License.dat`), no sequential execution enforcement (worker count = 1), and no handling of `LICENSE_ERROR`.
3. **Separation of Verification Paths:**
   - **Path A (Existing Testbench):** Conflates testbench completion with functional correctness. Does not distinguish `PASS_TESTBENCH_ONLY` from `PASS_REFERENCE_VERIFIED`.
   - **Path B (Independent Reference Verification):** Missing. No automated test harness generation driven by reference vector tables, no settling-time/clock timing models, and no independent Python comparison engine.
4. **Configurable Reference Data:** Only basic `$readmemh` memory dumps are handled. Generic CSV, JSON, HEX, and plain-text numerical tables with explicit signal/timing configurations are unsupported.
5. **Posit<16,1> Arithmetic Verification:** No golden Posit arithmetic model; `lookup_table.txt` is 0 bytes; no vector generation or mismatch auditing.
6. **Mutation Analysis:** No mutation qualification module or integration with MANTRA2.

---

## 4. Existing Bugs and Limitations

1. **Parser Regex Trap on `===` (Critical Bug):**
   - In `parser.py` (lines 332-337), the assignment regex `(?:<=|=)` matches the equality operator `===` in `if (product === 16'hxxxx)`.
   - This erroneously marks `product` as a **driven** signal in the testbench.
   - Consequently, `matcher.py` infers that the testbench expects `product` to be an `input` to the DUT, raising a false `INTERFACE ERROR: Port 'product' direction mismatch: expected input, got output` for `tb_multiplier (2).v`!
2. **License File Treated as Simulation Data (Bug):**
   - `scanner.py` classifies every `.dat` file as a simulation reference file, attempting to copy `LR-213236_License.dat` into build directories as a memory file.
3. **Duplicate Module Dropping (Bug):**
   - `scanner.py` silently drops duplicate module definitions (`if mod.name not in project.all_modules`) rather than tracking collisions, detecting multiple definitions across files, or reporting ambiguity.
4. **CacheManager Ignores Tool Provenance (Bug):**
   - Merkle hash leaves only include `plan.iverilog_flags`, omitting simulator executable identity, version, Questa options, and environment state.
5. **Observed Signals Regex Polluted (Bug):**
   - Testbench observed signal extraction captures string literals and numbers (`'txt'`, `'fail_log'`, `'w'`, `'h4800'`).
6. **Posit Multiplier RTL Questa 2025.3 Incompatibility (Discovered):**
   - In `shifterR.v` (line 1), the module header uses `output [n-1:0] F`, but `localparam n = 2**N;` is declared on line 2 in the body.
   - Questa 2025.3 strictly adheres to IEEE standard rules for ANSI port lists and rejects this with:
     `** Error: ..\shifterR.v(1): (vlog-2730) Undefined variable: 'n'.`
     `** Error: ..\shifterR.v(1): (vlog-13294) Identifier must be declared with a port mode: F.`
   - These syntax errors cannot be suppressed via `-suppress` or `-warning` in Questa 2025.3.
7. **Posit Multiplier Format Discrepancy (Discovered):**
   - The user specification mentions Posit<16,1> (1 exponent bit).
   - However, the actual RTL in `posit_decoder.v` and `posit_encoder.v` specifies `wire [1:0] exp` (2 exponent bits, corresponding to Posit<16,2>).
8. **Weakness of Existing Testbench Checker (Confirmed):**
   - `tb_multiplier (2).v` sweeps 65,536 vectors but only tests `if (product === 16'hxxxx)`.
   - Running simulation with Icarus confirmed: `Sweep complete: 65536 cases tested, 0 failures logged`.
   - However, this checks only for uninitialized bits; any constant or erroneous numerical value passes.

---

## 5. Existing Tests and Actual Results

| Test Category | Suite File | Result | Root Cause of Failure |
|---|---|---|---|
| AST Parsing | `tests/test_parser.py` | 3 Failures | Build path `PermissionError` when running tests outside isolated workspace |
| Cache Invalidation | `tests/test_cache.py` | 2 Failures | `PermissionError` on `test_cache.json` in read-only/unclean build directory |
| End-to-End Regression | `tests/test_end_to_end.py` | 1 Failure | `PermissionError` on wrapper generation path |
| Generic Family | `tests/test_generic_family.py` | 1 Failure | Build folder collision |
| DUT/TB Matcher | `tests/test_matcher.py` | PASS | Baseline matcher tests pass for standard adders |
| Posit Multiplier Match | Engine scan on `D:\dop2` | FAIL (`INTERFACE ERROR`) | Caused by Bug 1 (`===` regex misclassifying `product` as driven) |
| Posit Multiplier Simulation | `tb_multiplier (2).v` | PASS (X-only) | 65,536 cycles simulated in Icarus, 0 X's logged, zero numerical verification |

---

## 6. Components That Can Be Reused

1. **`models.py`**: Clean dataclass foundations for modules, ports, plans, and results.
2. **`dependency_resolver.py`**: Robust topological sorting and circular dependency detection.
3. **`wrapper_generator.py`**: Working Verilog wrapper code generation.
4. **`report_generator.py`**: Functional HTML and CSV export framework.
5. **`static_analyzer.py`**: AST-based static linting checks.

---

## 7. Prioritized Implementation Plan

- **Phase 1: Native Questa Simulator Adapter**
  - Implement `QuestaSimulatorAdapter` with `vlib`, `vlog`, `vsim -c`.
  - Add version detection and license environment validation (`SALT_LICENSE_SERVER`).
  - Enforce worker count = 1 and sequential execution.
  - Trap license errors distinctly from compile/runtime errors.

- **Phase 2: Robust HDL Discovery & Parsing**
  - Fix `===` regex bug in assignment analysis.
  - Filter out `.dat` license files from simulation data files.
  - Implement duplicate module detection across files.
  - Clean observed signal parsing and strengthen positional/named port inference.

- **Phase 3: Generic Reference Verification Engine (Path B)**
  - Implement flexible reference readers: CSV, JSON, HEX, .mem, plain tables.
  - Add explicit signal mapping and combinational/sequential timing configuration.
  - Develop automated Verilog/SystemVerilog test harness generator.
  - Implement independent Python comparison engine with detailed mismatch reporting.
  - Enforce strict separation between Path A (`PASS_TESTBENCH_ONLY`) and Path B (`PASS_REFERENCE_VERIFIED`).

- **Phase 4: Posit Multiplier Integration**
  - Implement independent Posit arithmetic reference model.
  - Clarify Posit<16,1> vs RTL Posit<16,2> encoding.
  - Create directed corner cases, random vector suites, and reference comparison.
  - Document syntax limitations and isolation mechanisms.

- **Phase 5: Reproducibility, History & Replay**
  - Update Merkle tree cache leaves to include simulator binary hash, tool options, and license hash.
  - Implement immutable execution history (`reports/history.jsonl`).
  - Provide CLI replay command to reproduce any historical run.

- **Phase 6: Quality, Mutation Analysis & Benchmark Suite**
  - Integrate MANTRA2-style mutation qualification.
  - Validate benchmark scenarios A through N.
  - Run full test suite and produce comprehensive final reports.
