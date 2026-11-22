# Generic External Reference Integration Demonstration

This demonstration illustrates how the **RTL Regression and Verification Framework** retrieves, extracts, validates, caches, and verifies an RTL design against an external reference source (in this case, an HTML truth table) using **Path B** verification alongside traditional **Path A** testbenches.

---

## 1. Benchmark Overview

- **Design Under Test (DUT)**: `priority_encoder_4bit.v`  
  A combinational 4-bit priority encoder:
  - Input: `req[3:0]`
  - Outputs: `grant[1:0]`, `valid`
  - Highest bit set determines `grant`; if `req == 0`, `valid = 0`.
- **Testbench (Path A)**: `tb_priority_encoder.v`  
  A self-checking testbench asserting expected responses on a subset of test vectors.
- **Reference Specification (Path B)**: `reference_data/truth_table.html`  
  A published HTML specification document containing a standard HTML `<table>` with `id="truth_table"`.

---

## 2. Configuration (`config.json`)

```json
{
  "project_name": "external_reference_demo",
  "top_module": "priority_encoder_4bit",
  "simulator": "icarus",
  "reference_sources": {
    "primary": {
      "priority": 1,
      "type": "direct_io_table",
      "url": "reference_data/truth_table.html",
      "format": "html_table",
      "table_id": "truth_table",
      "radix": "hex",
      "input_mapping": {
        "req": "req"
      },
      "output_mapping": {
        "grant": "grant",
        "valid": "valid"
      }
    }
  }
}
```

### What the Framework Does Automatically:
1. **Retrieval**: Accesses the specified URL (supports `http://`, `https://`, and local file URLs).
2. **HTML Extraction**: `HTMLTableExtractor` parses the HTML document without third-party dependencies and locates `<table id="truth_table">`.
3. **Format Normalization**: Extracted rows are converted into a standardized reference format.
4. **Caching & Provenance**: The table is saved to `.reference_cache/` alongside a `.meta.json` file recording the retrieval timestamp, source URL, and SHA-256 checksum.
5. **Path B Harness Generation**: The framework dynamically compiles a reference verification harness matching the DUT ports.
6. **Execution & Scoreboard**: The simulator stimulates all 16 vectors through the DUT, captures actual outputs, and validates against the extracted reference data.

---

## 3. How to Run the Demonstration

### A. Direct Execution (Local File URL)
From the repository root:
```powershell
python -m rtl_framework.cli run --project examples/external_reference_demo --simulator icarus
```

Expected output:
```
==========================================================================================================================
DUT MODULE               | TESTBENCH         | STATUS            | CONF      | CACHE  | VECTORS    | TIME   | DIAGNOSTIC
--------------------------------------------------------------------------------------------------------------------------
priority_encoder_4bit    | harness_priority_encoder_4bit | PASS_REFERENCE_VERIFIED | CONFIRMED | RUN    | 16/16      | 0.156s | All 16/16 vectors verified against golden reference.
priority_encoder_4bit    | tb_priority_encoder | PASS_TESTBENCH_ONLY | CONFIRMED | RUN    | 3/3        | 0.145s | All 3/3 self-checking testbench assertions passed.
==========================================================================================================================
```

### B. Live HTTP Server Demonstration
To demonstrate retrieval over HTTP:
1. In a terminal, start the local reference server:
   ```powershell
   python examples/external_reference_demo/serve_reference.py 8080
   ```
2. In `examples/external_reference_demo/config.json`, change the `"url"` to:
   ```json
   "url": "http://127.0.0.1:8080/truth_table.html"
   ```
3. Run regression:
   ```powershell
   python -m rtl_framework.cli run --project examples/external_reference_demo --simulator icarus
   ```
4. The framework will retrieve the HTML page over HTTP, extract `<table id="truth_table">`, cache it with a SHA-256 hash, and execute verification.

---

## 4. Key Architectural Concepts

### Direct I/O Table vs. Decoding Lookup Table
- **Direct Input/Output Reference Table (This Demo)**:  
  Every column maps directly to a DUT port (`req -> grant, valid`). The framework can directly drive Path B without any domain-specific mathematics.
- **Decoding Lookup Table (e.g. Posit Demonstration)**:  
  A lookup table mapping bit-patterns to mathematical real values. It is **not** a direct I/O oracle for operations such as multiplication. For decoding tables, the generic framework provides the cached data to a project-specific `ReferenceProvider` extension; the generic framework never contains hardcoded domain arithmetic.

### Limitations of Arbitrary Websites
The framework's generic `HTMLTableExtractor` parses standard HTML `<table>` elements with static structure. It deliberately **does not** execute JavaScript or scrape dynamic SPAs. For interactive websites or dynamic calculators, researchers should use the `ReferenceProvider` extension interface or export the reference dataset to CSV/JSON.
