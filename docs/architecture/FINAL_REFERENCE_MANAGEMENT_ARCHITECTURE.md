# Final Reference Management Architecture

## 1. Architectural Overview & Design Philosophy

The **RTL Regression and Verification Framework** incorporates an extensible, project-independent reference management architecture designed to decouple the hardware under test (DUT) and legacy testbenches from independent functional correctness verification.

### Core Separation of Verification Paths

The framework operates on two fundamentally distinct verification paradigms:

```
                            ┌──────────────────────────────────────────────┐
                            │               HDL Workspace /                │
                            │           User Project Directory             │
                            └──────────────────────┬───────────────────────┘
                                                   │
                   ┌───────────────────────────────┴───────────────────────────────┐
                   ▼                                                               ▼
        [ PATH A: Testbench Execution ]                             [ PATH B: Reference Verification ]
 1. Automatic DUT-Testbench Matching                        1. Multi-Source Reference Resolution
 2. Port Compatibility & Wrapper Synthesis                  2. Primary Golden vs. Secondary Fallback
 3. Dependency-Aware Isolated Simulation                    3. Classification (Direct I/O vs. Decoding)
 4. Log Sentinel & Assertion Auditing                       4. Dynamic SystemVerilog Harness Generation
 5. Evaluates Execution & Checking Strength                 5. Bit-Level Scoreboard Comparison
 6. Status: PASS_TESTBENCH_ONLY / EXECUTED_NOT_VERIFIED     6. Status: PASS_REFERENCE_VERIFIED / FAIL_REFERENCE
```

- **Path A (Legacy Testbench Execution)**: Discovers, compiles, and simulates existing project testbenches without modification. Audits outputs for self-checking assertions and sentinels. A testbench that completes without error but lacks assertions is classified as `EXECUTED / NOT VERIFIED`.
- **Path B (Independent Reference Verification)**: Bypasses potentially biased or flawed testbenches by injecting stimulus directly from verified reference sources into a dynamically synthesized SystemVerilog harness, checking actual hardware outputs against expected values bit-for-bit.

---

## 2. The Two Complementary Reference Sources

The framework recognizes two distinct sources of correctness information:

### Source A: Golden Reference Dataset (Primary Source)
- **Role**: Primary ground truth for Path B verification.
- **Formats Supported**: CSV, MEM (Verilog `$readmemh`/`$readmemb` compatible), HEX, JSON, and structured tabular files.
- **Characteristics**: Must define input vectors, expected outputs, signal mappings, and radix representations.
- **Policy**: When present and valid, it is selected as the primary verification source. It is **never** silently overwritten or altered.

### Source B: Professor-Provided Reference Material (Secondary Source)
- **Role**: Secondary or supplemental resource supplied by instructors, researchers, or external authorities.
- **Formats Supported**: Remote URLs (e.g. [PositHub Lookup Widget](https://www.posithub.org/widget/lookup)), local documents (PDF, Markdown, text), decoding tables, datasheets, or mathematical specifications.
- **Dual Functionality**:
  1. **Validation & Cross-Checking**: When a primary golden dataset already exists, the framework examines the secondary source to verify agreement on overlapping vectors. If consensus is reached, cross-validation is logged as `MATCH`. If conflicting expected outputs are found, the framework flags `STATUS_REFERENCE_DISPUTED`.
  2. **Fallback Verification**: When no valid primary golden dataset exists, the framework inspects the secondary material. If it contains direct input-output vectors, it is elevated to serve as the active fallback source for Path B. If it contains only a decoding table or specification, the framework notes that an external reference plugin is required and reports `STATUS_REFERENCE_UNAVAILABLE`.

---

## 3. Generic Reference Material Classification

The framework's classification engine (`ReferenceClassificationEngine` in `src/reference_manager.py`) analyzes files and metadata into five standard categories:

| Category | Definition | Capabilities & Constraints |
| :--- | :--- | :--- |
| **`DIRECT_IO_TABLE`** | Tabular mapping of multiple input vectors to expected output port values. | Directly consumed by `ReferenceHarnessGenerator` for automated Path B stimulus generation. |
| **`DECODING_TABLE`** | 1-D dictionary mapping encoded bit patterns to real numbers or attributes (e.g. PositHub). | Represents representation rules, NOT arithmetic operations. Cannot drive arithmetic multiplier/adder ports without an external software reference model. |
| **`MATHEMATICAL_SPEC`** | Functional equations, algorithmic descriptions, or standard definitions (e.g. IEEE 754, Posit Standard). | Theoretical specification. Requires an external plugin/model to generate concrete simulation vectors. |
| **`DOCUMENTATION`** | PDF datasheets, user manuals, application notes. | Informational only. Flagged as non-executable. |
| **`UNSUPPORTED`** | Corrupt, missing, empty, or unparseable files. | Flagged with clear diagnostics; cannot be used for verification. |

---

## 4. Priority and Resolution Engine (Cases 1–4)

The resolution engine (`ReferenceResolver`) evaluates configured reference sources and deterministically classifies the run into one of four cases:

```
                                  [ Reference Sources Config ]
                                                │
                                 Is Primary Source Available?
                                        │               │
                                    YES │               │ NO
                                        ▼               ▼
                        Are Both Primary & Secondary     Is Secondary Available &
                           Direct I/O Tables?             Direct I/O Table?
                             │             │                 │           │
                         YES │             │ NO          YES │           │ NO
                             ▼             ▼                 ▼           ▼
                      Do They Agree?    [ CASE 1 ]       [ CASE 2 ]  [ CASE 4 ]
                      │            │   Primary Active  Fallback Active Unavailable
                  YES │        NO  │   Path B Runs     Path B Runs     No Path B
                      ▼            ▼
                  [ CASE 1 ]   [ CASE 3 ]
                 Primary Active Disputed
                 Cross-Val: OK  Conflict Flagged
```

### Case 1: Golden Reference Exists & Is Valid
- Selected as active primary reference for Path B.
- If secondary reference is present, cross-validation is attempted.
- If secondary is a decoding table (e.g. PositHub) and primary is arithmetic, cross-validation status is logged as `NOT_APPLICABLE` (different domains), and primary is preserved.

### Case 2: Golden Reference Absent, Secondary Is Valid Direct I/O
- Secondary material is elevated to active fallback reference.
- Stored provenance records `resolution_case: "CASE_2_FALLBACK_ACTIVE"`.
- Path B harness executes with secondary vectors.

### Case 3: Both References Exist But Disagree
- Both sources provide direct I/O vectors for the same inputs, but their expected outputs conflict.
- The framework refuses to guess or pick the source that makes the DUT pass.
- Status is set to **`STATUS_REFERENCE_DISPUTED`**.
- All conflicting vectors (inputs, primary expected, secondary expected) are recorded in the report.

### Case 4: Neither Source Provides Usable Direct Vectors
- Neither primary nor secondary provides direct simulation vectors.
- Status is set to **`STATUS_REFERENCE_UNAVAILABLE`**.
- Path A testbenches continue to run independently.

---

## 5. Configuration Schema

The framework supports multi-source configurations through external JSON files without modifying `src/`:

```json
{
  "project_name": "Multi-Source Reference Verification",
  "build_dir": "build",
  "reports_dir": "reports",
  "simulator": "icarus",
  "timeout_seconds": 30.0,
  "reference_sources": {
    "primary": {
      "name": "golden_dataset",
      "path": "ref/golden_vectors.csv",
      "priority": 1,
      "type": "direct_io_table",
      "format": "csv",
      "radix": "hex",
      "input_mapping": {
        "operand_a": "in_a",
        "operand_b": "in_b"
      },
      "output_mapping": {
        "expected_product": "result"
      },
      "timing": {
        "mode": "combinational",
        "settling_time_ns": 5.0
      }
    },
    "secondary": {
      "name": "posithub_lookup_widget",
      "url": "https://www.posithub.org/widget/lookup",
      "priority": 2,
      "type": "decoding_table",
      "notes": "Authoritative PositHub decoding lookup widget for Posit<16, 2>"
    }
  }
}
```

Legacy configurations utilizing `"reference": { "file": "...", ... }` remain 100% backward-compatible.

---

## 6. Provenance Tracking & Reproducibility

Every test execution preserves comprehensive reference provenance metadata inside `TestResult.reference_provenance`:

```json
{
  "resolution_case": "CASE_1_PRIMARY_ACTIVE",
  "primary_source": "posit_mult_corners",
  "primary_file": "D:\\dop2\\tb\\posit_mult_corners.csv",
  "primary_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "secondary_source": "posithub_lookup_widget",
  "secondary_category": "decoding_table",
  "cross_validation": "NOT_APPLICABLE"
}
```

This metadata is embedded in `regression_summary.json` and persistent `verification_history.jsonl` audit trails.
