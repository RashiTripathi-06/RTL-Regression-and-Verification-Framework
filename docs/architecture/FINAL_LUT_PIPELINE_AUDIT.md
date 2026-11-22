# Final Universal LUT & Reference Pipeline Audit

## 1. Introduction

This audit comprehensively documents the discovery, parsing, association, simulation, and verification pipeline for Lookup Tables (LUTs) and external reference datasets within the universal RTL Regression Framework.

---

## 2. Detailed Technical Audit (21 Core Questions)

### Q1: How are reference files discovered?
- **Implementation**: `ProjectScanner._scan_directory()` in `src/scanner.py` (lines 60–105).
- **Mechanism**: Traverses the project directory and classifies files by extension and content. Files with extensions `.mem`, `.hex`, `.dat`, `.csv`, `.json`, or tabular `.txt` with keywords (`lut`, `table`, `ref`, `golden`, `vector`, `mem`) are cataloged in `project.data_files`.

### Q2: Which extensions and formats are supported?
- **Supported Formats**:
  1. `.mem` — Verilog hex or binary memory files (supporting addresses `@...`, comments `//`, `#`, and bitpacked concatenations).
  2. `.hex` — Standard Intel/Verilog hex files.
  3. `.dat` — Raw binary/hex ASCII data arrays.
  4. `.csv` — Comma-separated values with header matching port names.
  5. `.json` — Structured JSON objects with arrays of vector objects.
  6. `.txt` — Tabular space/comma-delimited data files.

### Q3 & Q4: Does the scanner detect `$readmemh` and `$readmemb`?
- **Implementation**: `src/parser.py` (lines 350–375) and `src/planner.py` (lines 80–115).
- **Mechanism**:
  ```python
  for mem_call in re.finditer(r'\$(?:readmem[hb])\s*\(\s*["\']([^"\']+)["\']', tb_text):
      ref_name = mem_call.group(1).strip()
  ```
  The parser also resolves macro identifiers such as `$readmemh(`LUT_FILE, ...)` and parameters.

### Q5: Does it detect `$fopen` and other file references?
- **Implementation**: `src/parser.py` (lines 365–385) scans for `$fopen`, `$dumpfile`, and `$readmemb`. System calls are stored in `ModuleInfo.system_calls`.

### Q6: Does it discover LUTs referenced inside existing testbenches?
- **Implementation**: `VerificationPlanner.extract_testbench_reference_files()` in `src/planner.py`.
- **Mechanism**: Parses the testbench HDL source to find all data files referenced via `$readmemh`/`$readmemb`, searches project directories for matching basenames, and binds them to the verification plan.

### Q7 & Q8: Does it support both automatic discovery and explicit configuration?
- **Implementation**: Yes. `VerificationPlanner` applies strict priority:
  1. Explicit user configuration in `config.json` (`reference_files` or `manifest.json`).
  2. Automatic AST/regex extraction from HDL source.
  3. Discovery from workspace scanning.

### Q9 & Q10: How are reference datasets associated with DUTs, and how are ambiguous associations handled?
- **Implementation**: Association is scoped strictly at the testbench level in `src/planner.py`.
- **Mechanism**:
  - `associated_data`: Only data files explicitly referenced by the matched testbench are attached.
  - `unused_reference_files`: Data files present in the project but not needed by the testbench are tracked but NOT staged.
  - If a testbench references a file not found in the repository, it is added to `missing_reference_files`, resulting in immediate status `STATUS_MISSING_REFERENCE`.

### Q11: How are unrelated LUTs prevented from being associated with the wrong DUT?
- **Evidence**: Tested in `tests/test_lut_association.py::test_unrelated_lut_files_not_associated`.
- `tb_counter` references `counter_ref.mem`. Even though `adder_lut.mem` exists in `tb/`, the planner associates ONLY `counter_ref.mem` with `tb_counter`. Unrelated files are ignored.

### Q12: How are reference files parsed?
- **Dual Parser Implementation**:
  1. `parse_reference_file()` in `src/auditor.py` for legacy testbench log checking. Parses bitpacked headers dynamically:
     ```python
     // word = {a[3:0], b[3:0], cin, expected_cout, expected_sum[3:0]}
     ```
  2. `ReferenceDataLoader.load()` in `src/reference_verifier.py` for Path B independent verification. Handles arbitrary CSV, JSON, and MEM files, resolving Verilog radix prefixes (`16'h`, `8'b`, `0x`, `0b`).

### Q13: How are input vectors applied to the DUT?
- **Implementation**: `ReferenceHarnessGenerator.generate()` in `src/reference_verifier.py`.
- **Mechanism**: Synthesizes a standalone SystemVerilog harness (`harness_<dut>.sv`) and packs all input signals into an array written to `dut_inputs.mem`. The harness loads vectors via `$readmemh`, unrolls them into the exact DUT port bit-ranges, drives clocks/resets for sequential designs or delays for combinational settling, and advances vectors in a loop.

### Q14: How are expected output columns mapped to DUT output ports?
- **Mechanism**: Driven by external configuration (`input_mapping` and `output_mapping`). For example:
  ```json
  "output_mapping": { "expected_out": "mac_out", "expected_ovf": "ovf" }
  ```
  The harness writes actual DUT output values to `actual_outputs.csv`.

### Q15: How are actual outputs captured?
- **Mechanism**: In `harness_<dut>.sv`, an initial block opens `actual_outputs.csv` via `$fopen` and uses `$fdisplay(outfile, "%0d,%h,%h", idx, port1, port2)` at each evaluation step.

### Q16: How does the comparison engine operate?
- **Implementation**: `ReferenceScoreboard.audit()` in `src/reference_verifier.py`.
- **Mechanism**: In Python, parses `actual_outputs.csv` and compares each output value against `ParsedVector.expected_outputs` at identical indices.

### Q17: How are X/Z values handled?
- **Mechanism**: Any appearance of `x`, `z`, `X`, or `Z` in the actual output string immediately triggers a failure and classifies the run as **`STATUS_INVALID_RESULTS`**.

### Q18: How are missing entries, duplicate vectors, invalid widths, and ordering errors handled?
- **Premature termination**: If simulation produces fewer lines than expected reference vectors, reports `STATUS_INCOMPLETE`.
- **Duplicate indices / out-of-order vectors**: Flagged as `STATUS_INVALID_RESULTS` (validated in `test_adversarial.py`).
- **Width mismatches**: Sliced or masked to port width by the harness generator, with static warnings issued.

### Q19: How are mismatches represented in reports?
- **Data Structure**: `VectorMismatch` object containing `index`, `inputs`, `actual_outputs`, `expected_outputs`, and human-readable `raw_message`.
- **Export**: Emitted in `regression_summary.json` under `failing_vectors`, logged in `.log` files, and formatted in terminal summaries.

### Q20: Does an internal LUT used by the original testbench automatically become an independent Path B reference?
- **NO**: A LUT loaded via `$readmemh` by an original testbench is a **Path A dependency**. It is copied into `build/<plan_id>/` so the legacy simulation runs. It does NOT automatically verify the DUT independently because the original testbench might have flawed check logic (or none at all).
- An independent Path B verification occurs **only** when an external reference dataset is configured and verified through `ReferenceVerificationEngine`.

### Q21: Are Path A and Path B architecturally separate?
- **YES**:
  - Path A executes the original unmodified testbench and audits simulator text output for assertion pass/fail.
  - Path B generates a new test harness (`harness_<dut>.sv`), drives stimulus from external reference files, and uses a bit-accurate Python scoreboard.
  - As demonstrated on `multiplier.v`: Path A reported `PASS_TESTBENCH_ONLY` (65,536/65,536 passed because the testbench only checked for `xxxx`), while Path B reported `FUNCTIONAL FAIL` (123/144 passed, 21 failed).
