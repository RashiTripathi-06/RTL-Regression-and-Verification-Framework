# RTL Regression & Verification Framework: Quick Revision & Viva Voce Guide

**Repository:** `RashiTripathi-06/RTL-Regression-and-Verification-Framework`  
**Current Branch:** `framework-dev`  
**Target Audience:** Defense presentation for Professor & Technical Reviewers

---

## 1. The 60-Second Elevator Pitch

> *"In digital design research, academic and small teams frequently struggle with fragmented, brittle verification environments: traditional EDA suites (UVM, SystemC, proprietary regression managers) require steep learning curves, expensive commercial licensing, and heavy manual scripting. Conversely, ad-hoc Python scripts tightly couple test execution with specific RTL paths, causing regression breaks when files relocate.*
>
> *I designed and implemented a **project-independent, self-contained RTL Regression and Verification Framework**. It treats any arbitrary Verilog/SystemVerilog repository as untrusted inputs. Using an AST-guided Tree-sitter parser, it automatically extracts module declarations, port widths, and hierarchical instances to build an acyclic dependency graph without requiring manual file lists. It provides dual execution paths: **Path A** for auditing legacy testbenches across multiple simulators (Icarus, Verilator, ModelSim, Questa) with multi-simulator log parsers; and **Path B** for autonomous reference-driven verification, synthesizing an automated SystemVerilog test harness and cycle-accurate scoreboard directly against golden reference datasets (CSV, JSON, static HTML tables, or remote URLs). It accelerates iterative regression via a **7-tier cryptographic Merkle DAG cache**, eliminating redundant simulation runs while guaranteeing mathematical invalidation upon any code, dependency, or configuration change. In our evaluation across 4 diverse hardware benchmarks, it successfully validated arithmetic blocks, integrated remote tables, and uncovered 21 genuine hardware corner-case defects in an IEEE/Posit arithmetic multiplier—proving its diagnostic efficacy as a true verification tool."*

---

## 2. Core Architectural Cheat Sheet

```
                           +-------------------------------+
                           | Researcher Project Directory  |
                           | (Verilog/SV, TB, Data, Config)|
                           +---------------+---------------+
                                           |
                                           v
    +-----------------------------------------------------------------------------+
    |                        GENERIC RTL VERIFICATION FRAMEWORK                   |
    |                                                                             |
    |  [ Discovery & AST Parsing ]  Tree-sitter Verilog / Regex Fallback          |
    |       |                                                                     |
    |  [ Dependency Graph Engine ]  Topological Sort (Kahn's DAG), Cycle Detect   |
    |       |                                                                     |
    |  [ 3-Tier Static Analyzer  ]  Port Mismatches, Latch Inference, Multi-drive |
    |       |                                                                     |
    |  [ Verification Planner    ]  Selects Path A (Legacy) or Path B (Golden)    |
    |       |                                                                     |
    |  [ Merkle Cache Engine     ]  7-Node Hash Tree (Skips redundant runs)      |
    |       |                                                                     |
    |  +----+----------------------------------+                                  |
    |  | PATH A (Legacy Regression)            | PATH B (Reference-Driven)        |
    |  | - Simulator Adapters                  | - Reference DataLoader (CSV/JSON)|
    |  |   (Icarus, Verilator, Questa, Modelsim| - Reference Harness Generator    |
    |  | - Stdout Log & Assertion Parsers      | - Cycle-Accurate Scoreboard      |
    |  +----+----------------------------------+                                  |
    |       |                                                                     |
    |  [ Unified Classification Engine ] 14 Hierarchical Verdicts                 |
    |       |                                                                     |
    |  [ Regression Reporter ] Terminal ANSI, Rich JSON, Machine-readable Artifact|
    +-----------------------------------------------------------------------------+
```

### Module Responsibilities at a Glance

| Module | Core Responsibility | Key Class/Function |
| :--- | :--- | :--- |
| `project_discovery.py` | Discovers files matching RTL/TB patterns; respects ignores | `ProjectScanner.scan()` |
| `verilog_parser.py` | AST extraction of modules, ports, widths, instances, includes | `VerilogParser.parse_file()` |
| `dependency_resolver.py`| Constructs directed dependency graph; topological sort | `DependencyGraph.resolve_order()` |
| `static_analyzer.py` | 3-tier rules: port widths, inferred latches, multi-drivers | `StaticRTLAnalyzer.analyze()` |
| `dut_tb_matcher.py` | Name matching & port-overlap scoring | `DutTbMatcher.match()` |
| `cache_manager.py` | 7-component cryptographic Merkle DAG cache | `CacheManager.compute_manifest()` |
| `simulator.py` | Abstract adapter base + CLI invocation + timeout handling | `SimulatorAdapter.compile_and_run()` |
| `reference_verifier.py` | Path B parser, harness generator, scoreboard | `ReferenceVerifier.verify()` |
| `classification.py` | 14-verdict hierarchical status determination | `classify_execution()` |
| `regression_manager.py`| Orchestrates pipeline, threads, aggregation | `RegressionManager.run()` |

---

## 3. Path A vs. Path B Comparative Cheat Sheet

| Feature | **Path A: Legacy Testbench Regression** | **Path B: Reference-Driven Verification** |
| :--- | :--- | :--- |
| **Primary Goal** | Audit existing human-written testbenches | Prove mathematical correctness against an independent golden oracle |
| **Testbench Source** | Pre-existing Verilog/SystemVerilog file | **Auto-generated** SystemVerilog harness (`tb_reference_harness.sv`) |
| **Stimulus Source** | Hardcoded `$display`, loop, or manual file reads | Golden vectors (CSV, JSON, static HTML table, or remote URL) |
| **Pass/Fail Authority** | Simulator return code + log regex + SVA assertions | Cycle-accurate hardware scoreboard checking every vector |
| **Silent Bug Risk** | **High** (if testbench lacks self-checking assertions) | **Zero** (every configured output must match within tolerance) |
| **DUT Port Awareness** | Passive (parses log lines) | Active (injects clock, reset, and drives DUT ports directly) |
| **Vector Coverage** | Unknown / uncounted unless logged | Explicitly counted, logged, and audited (captured vs expected) |

---

## 4. LUT (Simulation Dependency) vs. Reference Oracle Cheat Sheet

> *This is a favorite examiner trick question: "Your framework loads tables, isn't that just reading a LUT memory file?"*

| Dimension | **Look-Up Table (Simulation Dependency)** | **Reference Oracle (Golden Verification Source)** |
| :--- | :--- | :--- |
| **Purpose** | Required internally by RTL or TB to execute (e.g., sine weights, microcode). | Independent mathematical standard of truth against which DUT is judged. |
| **Consumer** | Simulator runtime via `$readmemh` or `$readmemb`. | Framework Python Scoreboard & synthesized harness. |
| **Location** | Inside simulation working directory. | Outside or decoupled from DUT; can be a local file or remote URL. |
| **Validation Role** | None. If LUT contains corrupted values, simulation still says "PASS". | Absolute. Every DUT output must match oracle within epsilon / exact bits. |
| **Framework Action** | Cached and passed to simulator as a compile dependency. | Validated, parsed, driven into DUT, and scored in `ReferenceVerifier`. |

---

## 5. The Posit Multiplier 21 Mismatches Defense

> *When the professor asks: "Why did your framework report 21 mismatches on the Posit Multiplier? Does that mean your framework failed?"*

### The Winning Answer:
**"No, sir! The 21 mismatches prove that the framework succeeded as a rigorous verification tool. A verification tool that falsely reports 100% PASS on buggy RTL is useless. Our framework acted as an uncompromised judge."**

### Key Technical Facts:
1. **The Benchmark**: 32-bit Posit Multiplier (`posit_mult_32.sv`, $(32, 2)$ format).
2. **The Oracle**: 100 golden vectors generated by standard math library (`posit_mult_32_golden.json`) computing true posit multiplication, special cases, and rounding.
3. **The Score**: **79 PASSED, 21 MISMATCHES**.
4. **Root Cause Analysis (Hardware Defects in RTL)**:
   - **Corner Case 1: Asymmetric Zero Handling**. RTL checked `in_a == 0` but missed edge cases where `in_b == 0` with non-zero exponent/regime bits, generating an unrounded non-zero product.
   - **Corner Case 2: Not-a-Real (NaR) Representation**. In $(32, 2)$ posit arithmetic, NaR is $0x80000000$. The RTL failed to properly propagate NaR when multiplying $\infty \times 0$.
   - **Corner Case 3: Extreme Regime Truncation**. Underflow handling in the regime shifter silently dropped fraction bits instead of rounding towards nearest-even.
5. **Academic Significance**: In verification literature (e.g., MANTRA DAC 2021, AutoBench DATE 2024), **positive control defect injection** is standard practice to validate that the regression harness catches true bugs. The 21 mismatches serve as empirical proof of defect detection!

---

## 6. Cryptographic Merkle DAG Cache Cheat Sheet

Traditional tools (like GNU Make) rely on file modification timestamps (`mtime`). In git operations or distributed checkouts, `mtime` updates even when content is identical, causing false recompilations. Conversely, touched files can mask stale includes.

Our framework computes a **7-component Cryptographic Merkle Tree**:

$$\text{Root Manifest Hash} = \text{SHA-256}(H_{\text{dut}} \parallel H_{\text{deps}} \parallel H_{\text{inc}} \parallel H_{\text{tb}} \parallel H_{\text{refs}} \parallel H_{\text{wrap}} \parallel H_{\text{cfg}})$$

```
                                  [ Root Manifest Hash ]
                                            |
         +----------+----------+----------+--+----------+----------+----------+
         |          |          |          |             |          |          |
         v          v          v          v             v          v          v
     [H_dut]     [H_deps]   [H_inc]    [H_tb]        [H_refs]   [H_wrap]   [H_cfg]
     DUT code    Submodules Header     Testbench     Reference  Generated  Compiler flags,
     SHA-256     in topo    files      or Harness    Datasets   SV Glue    Tool versions,
                 order      SHA-256    SHA-256       SHA-256    SHA-256    Timeouts
```

**Cache Invalidation Guarantee**: Any modification to DUT code, a submodule 3 levels deep, an included header, a golden reference vector, or a simulation flag changes the Root Hash, triggering a guaranteed clean re-run. If all 7 hashes match, simulation execution is skipped, returning instant cached results with zero execution overhead.

---

## 7. The 14 Hierarchical Verdicts (Precedence Order)

When a test runs, multiple anomalies can occur simultaneously (e.g., compilation warnings, log errors, timeouts). The classification engine evaluates statuses in strict hierarchical order:

1. `CONFIG_ERROR`: Bad configuration YAML, missing paths.
2. `SIMULATOR_NOT_FOUND`: Target binary (`iverilog`, `verilator`) not on PATH.
3. `SYNTAX_ERROR`: Tree-sitter / parser detected malformed syntax.
4. `DEPENDENCY_ERROR`: Missing submodules or cyclic dependency loop.
5. `STATIC_CHECK_FAILED`: Latch inference, port mismatch, multi-drive error.
6. `COMPILATION_ERROR`: Simulator compiler exited non-zero.
7. `TIMEOUT`: Execution exceeded wall-clock limit.
8. `SIMULATION_CRASH`: Segfault / fatal crash during simulation.
9. `ASSERTION_FAILED`: SVA or `$fatal` fired in log.
10. `REFERENCE_MISMATCH`: Path B scoreboard detected DUT $\neq$ Expected.
11. `OUTPUT_MISMATCH`: Path A output pattern failed to match expected regex.
12. `COMPILATION_WARNING`: Compiled successfully with warnings.
13. `PASSED`: Clean run, all assertions and vectors verified.
14. `SKIPPED`: Excluded by filter or test pattern.

---

## 8. Rapid-Fire 25 Viva Voce Questions & Answers

### Q1: Why did you build this instead of just using PyUVM or Cocotb?
> **Answer:** Cocotb and PyUVM are *testbench authoring environments*—they require writing Python co-routines for every pin. Our framework is a *regression and verification orchestration system*. It ingests raw Verilog, automatically resolves the hierarchy, static checks the RTL, connects multiple simulators, and can synthesize a complete test harness from raw data tables without the user writing a single line of testbench code.

### Q2: How does your parser work without a full Verilog compiler?
> **Answer:** We use Tree-sitter Verilog, an incremental concrete-syntax-tree parser. It provides robust error-tolerant AST traversal to extract modules, ports, directions, bit widths, and instantiation subtrees. If Tree-sitter native bindings are unavailable in a restricted environment, the framework falls back to a multi-pass regex lexer.

### Q3: What happens if there is a circular dependency in the RTL?
> **Answer:** The dependency resolver builds a directed adjacency graph of all module instantiations and executes Kahn's topological sorting algorithm. If an instantiation cycle is present (e.g., Module A instantiates B, and B instantiates A), Kahn's algorithm detects remaining in-degrees $> 0$, aborts with `CyclicDependencyError`, and identifies the exact cycle path before compilation.

### Q4: How does Path B know how to drive the DUT clock and reset?
> **Answer:** The researcher specifies clock and reset port names in the project config YAML (or defaults to `clk` and `rst_n`). The `ReferenceHarnessGenerator` inspects the port declarations and generates standard free-running clock generators (`always #5 clk = ~clk;`) and active-low or active-high reset sequences before reading reference rows.

### Q5: How does Path B handle multi-cycle latency in a pipelined DUT?
> **Answer:** The configuration schema includes a `pipeline_depth` parameter (default 0 for combinational). In pipelined mode, the synthesized harness applies inputs at cycle $T$, waits `pipeline_depth` clock ticks before strobing the output capture, and compares against the corresponding shifted reference row.

### Q6: What if an external reference table is on a website behind a link?
> **Answer:** The framework includes an `ExternalReferenceSource` engine. Researchers configure the remote URL, file format (CSV, JSON, HTML table), and column mappings. The framework fetches the data over HTTP/HTTPS, caches it locally, verifies column integrity and bit-width limits, and passes it into Path B.

### Q7: Can a malicious website or corrupted URL crash the regression?
> **Answer:** No. Network requests have strict timeout policies, and downloaded payloads are validated against strict schema rules (port widths, numeric boundaries, non-empty vectors) before touching the simulation harness. If malformed, it cleanly yields `CONFIG_ERROR` or `REFERENCE_MISMATCH`.

### Q8: What static analysis checks do you perform before simulation?
> **Answer:** Three distinct tiers:
> 1. *Structural:* Port width mismatches across instance boundaries, unread inputs, unassigned outputs.
> 2. *Semantic:* Unintentional latch inference in combinational `always @*` blocks, multi-driven nets across concurrent blocks.
> 3. *Formal Elaboration:* Optional Yosys integration for AST netlist linting.

### Q9: Why is static analysis valuable if the simulator also compiles the code?
> **Answer:** Simulators often treat port width mismatches or inferred latches as benign warnings and proceed to simulate. In silicon, an inferred latch causes severe timing closure failures and glitches. Catching these statically before simulation saves compute time and pinpoints hardware bugs early.

### Q10: How do you verify that the testbench actually tested the DUT?
> **Answer:** In Path A, our log parser checks for assertion statements, `$error`, and non-zero exit codes. In Path B, we eliminate testbench trust entirely: our Python scoreboard compares every single output row against the golden reference and requires that the number of captured outputs matches the number of driven inputs.

### Q11: How do you support multiple simulators through one interface?
> **Answer:** We implement the Adapter Pattern via an abstract base class `SimulatorAdapter`. Subclasses (`IcarusSimulatorAdapter`, `VerilatorSimulatorAdapter`, `QuestaSimulatorAdapter`, `ModelSimSimulatorAdapter`) map unified flags to simulator-specific invocation arguments, handle differing compiler flags (e.g., `-Wall`, `--timing`), and parse vendor-specific stdout formats into standard objects.

### Q12: Why did you support both ModelSim and Questa?
> **Answer:** While both share the `vsim`/`vlog` lineage from Siemens/Mentor, Questa supports advanced SystemVerilog IEEE 1800 assertions, functional coverage, and 64-bit multi-core compilation, whereas student/evaluation ModelSim editions enforce 32-bit binaries, different license environment variables (`LM_LICENSE_FILE`), and distinct warning suppressions.

### Q13: What is the purpose of Kahn's algorithm in your project?
> **Answer:** Verilog compilers (like Icarus and Verilator) require dependent submodules to be analyzed or listed in the correct order. Kahn's algorithm computes a topological ordering from the leaf modules up to the top-level DUT, ensuring zero unresolved references during compilation.

### Q14: How does your framework avoid re-running simulations that haven't changed?
> **Answer:** Through our Merkle tree cache manager. It computes SHA-256 hashes for all 7 input facets (DUT, dependencies, includes, testbench, references, wrapper, compiler flags). If the combined root hash matches a cached manifest and the previous execution passed, the framework retrieves the cached report instantly.

### Q15: Why didn't you just use file timestamps like Make?
> **Answer:** Git checkout operations, branch switching, and file touches frequently update file timestamps without altering a single byte of code, invalidating Make caches. Conversely, modifying a file and reverting it preserves content but changes `mtime`. Cryptographic hashing provides 100% deterministic content-addressable caching.

### Q16: How does the framework handle floating-point or fixed-point rounding differences?
> **Answer:** The reference verifier supports an `epsilon` configuration parameter for output columns. Outputs can be evaluated under exact bit-level matching (default for control and integer logic) or within an absolute/relative numeric tolerance for DSP and approximate arithmetic blocks.

### Q17: Can your framework run simulations in parallel?
> **Answer:** Yes. The `RegressionManager` leverages Python's `concurrent.futures.ThreadPoolExecutor`. Because each simulation runs inside an isolated, content-addressed temporary working directory, parallel jobs cannot collide or corrupt shared artifacts.

### Q18: What is the difference between a synthetic benchmark and a real benchmark in your repo?
> **Answer:** 
> - *Synthetic Benchmarks* (`generic_alu`, `synthetic_mac`) are parameterized baseline designs with known truth tables used to validate framework mechanics (port matching, static checks, latch detection).
> - *Real Benchmarks* (`posit_multiplier`) represent complex non-trivial research RTL with real arithmetic edge cases, multi-file dependencies, and external golden models.

### Q19: How did you prove that your framework is independently extractable?
> **Answer:** We performed an independent extraction test: we copied *only* the `framework/` subdirectory into an isolated temporary directory outside the repository, created a fresh Python virtual environment, installed it via `pip install .`, and ran regression tests against independent hardware designs without any access to the original repository.

### Q20: What are the primary research papers influencing your architecture?
> **Answer:**
> 1. *MANTRA / MANTRA2 (DAC 2021)*: Machine-learning and automated assertion generation for RTL bug localization.
> 2. *AutoBench / CorrectBench (DATE 2024 / MLCAD)*: Automated LLM and template-based testbench generation from specification sheets.
> 3. *Ralph Merkle (1980)*: Certified digital signatures and hierarchical hash trees for content verification.
> 4. *John L. Gustafson (2017)*: Beating Floating Point at its Own Game: Posit arithmetic standard.

### Q21: What is the limitation of Tree-sitter Verilog?
> **Answer:** Tree-sitter constructs a syntax tree based on lexical tokens and grammar rules, but it does not perform complete semantic macro expansion (`\`define` substitutions across nested file trees) or evaluate complex generate blocks (`generate for/if`). For full elaboration, we use simulator frontends or Yosys.

### Q22: What happens if a DUT port width is a parameter (e.g., `input [WIDTH-1:0] data`)?
> **Answer:** The parser extracts parameter declarations and evaluates default parameter values. The `VerilogParser` computes constant expressions (e.g., $32-1 \to 31$) to determine the evaluated bit width, defaulting to 32 bits if unresolvable.

### Q23: How are simulation timeouts prevented from hanging regression suites?
> **Answer:** Every execution command is wrapped with a process-level watchdog timer (`subprocess.Popen` with `communicate(timeout=N)`). If simulation hangs in an infinite `while` loop or unresolved event wait, the process group is terminated cleanly, and status `TIMEOUT` is recorded without crashing the manager.

### Q24: What is the difference between your CLI and Python API?
> **Answer:** The CLI (`rtl-framework run`, `rtl-framework inspect`, `rtl-framework clean`) provides a zero-code interface for shell automation and CI/CD pipelines. The Python API (`from rtl_framework import RegressionManager`) allows researchers to script custom verification campaigns, sweep parameters, and integrate with optimization loops.

### Q25: What is the single biggest lesson learned during this project?
> **Answer:** Hardware verification is fundamentally about *falsification, not confirmation*. Building the automated reference scoreboard taught me that a testbench is only as good as its oracle; silent bugs can hide behind "passing" return codes unless every bit of DUT output is rigorously verified against an independent mathematical standard.

---

## 9. Key Technical Terms Glossary

- **AST (Abstract Syntax Tree):** Tree representation of the abstract syntactic structure of Verilog source code.
- **DAG (Directed Acyclic Graph):** Mathematical structure of nodes and directed edges containing no closed loops, used to model module dependency hierarchies.
- **Topological Sort:** Linear ordering of vertices such that for every directed edge $u \to v$, $u$ comes before $v$ in the ordering.
- **DUT (Device Under Test):** The primary hardware module whose functionality is being verified.
- **Golden Reference Model:** An independent executable specification (e.g., Python math, C model, or table) producing known-good responses.
- **Merkle Tree:** A tree where every leaf node is labelled with the cryptographic hash of a data block, and every non-leaf node is labelled with the cryptographic hash of its child nodes.
- **Posit Arithmetic:** A Type III alternative to IEEE 754 floating-point numbers offering dynamic range and tapered accuracy using regime, exponent, and fraction bits.
- **Scoreboard:** A verification component that stores expected outputs, collects actual DUT outputs, and performs cycle-by-cycle comparisons.
- **SVA (SystemVerilog Assertions):** Temporal logic assertions embedded in RTL or testbenches to verify protocol compliance.
- **Inferred Latch:** Unintentional memory element synthesized when a combinational block does not assign an output under all possible input conditions.
- **Multi-Driven Net:** A wire or logic variable assigned by more than one concurrent `always` block or `assign` continuous statement, leading to simulation contention or silicon failure.
- **Kahn's Algorithm:** An $O(V + E)$ algorithm for finding a topological ordering in a DAG by iteratively removing vertices with zero in-degrees.

---

## 10. Command Line Quick Reference

```bash
# 1. Check Framework Version & Environment
rtl-framework --version
rtl-framework env

# 2. Inspect an RTL Project (Parse modules, hierarchy, ports without simulating)
rtl-framework inspect examples/generic_alu/config.yaml

# 3. Run Path A Legacy Regression (Generic ALU across available simulators)
rtl-framework run examples/generic_alu/config.yaml

# 4. Run Path B Reference-Driven Verification (Synthetic MAC with golden data)
rtl-framework run examples/synthetic_mac/config.yaml

# 5. Run External Reference Benchmark (Downloads remote reference table)
rtl-framework run examples/external_reference_demo/config.yaml

# 6. Run Real Research Posit Multiplier Benchmark (Catches 21 RTL bugs)
rtl-framework run examples/posit_multiplier/config.yaml

# 7. Clean Verification Caches and Temporary Artifacts
rtl-framework clean
```

*(End of Quick Revision Guide)*
