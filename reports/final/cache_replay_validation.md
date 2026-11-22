# Cryptographic Merkle Cache and Historic Replay Validation Report

## Executive Summary
The RTL Regression Framework utilizes a hierarchical SHA-256 Merkle DAG caching engine to enforce incremental regression integrity. Any change in:
1. DUT source code
2. Submodule dependencies (hierarchical)
3. Included header files (`.vh`, `.h`)
4. Testbench source code
5. Associated data/reference files (`.csv`, `.hex`, `.mem`)
6. Compiler/simulator flags
7. Simulator adapter backend

strictly invalidates the Merkle root hash for that plan, preventing stale cache hits.

Additionally, every regression execution records a cryptographically signed execution log into `reports/verification_history.jsonl`. Historic runs can be faithfully replayed by Run ID (`--replay <run_id>`) with automated divergence detection.

---

## 1. Merkle Tree Invalidation Test Results

| Invalidation Trigger | Baseline Hash Prefix | Perturbed Hash Prefix | Cache State | Verification Result |
|---|---|---|---|---|
| **Unchanged Baseline** | `c844e914763e...` | `c844e914763e...` | **CACHE HIT** | Passed (0 ms overhead) |
| **DUT Source Mutation** | `c844e914763e...` | `1f986833...` | **INVALIDATED (MISS)** | Re-executes compilation |
| **Submodule Modification** | `c844e914763e...` | `acd6c1c1...` | **INVALIDATED (MISS)** | Re-executes compilation |
| **Testbench Modification** | `c844e914763e...` | `336b6360...` | **INVALIDATED (MISS)** | Re-executes compilation |
| **Reference File Update** | `c844e914763e...` | `46078c34...` | **INVALIDATED (MISS)** | Re-executes compilation |
| **Compiler Flag Change** | `c844e914763e...` | `e115f920...` | **INVALIDATED (MISS)** | Re-executes compilation |
| **Simulator Adapter Change** | `c844e914763e...` | `e1e7009f...` | **INVALIDATED (MISS)** | Re-executes compilation |

---

## 2. Replay Verification Summary

Historical execution run `run_20261121_075609_36a779` containing 45 distinct verification plans was replayed against the current workspace:

- **Total Plans Replayed**: 45
- **Plans Passing Match**: 45 (100.0%)
- **Divergences Detected**: 0 (0.0%)
- **Result**: `[SUCCESS] All replayed plans reproduced 100% identically.`

### Detailed Plan Consistency
- `adder_behavioral__tb_adder`: Status=`PASS_REFERENCE_VERIFIED` (Matched historic run)
- `adder_behavioral__tb_adder_random`: Status=`PASS_TESTBENCH_ONLY` (Matched historic run)
- `adder_buggy__tb_adder`: Status=`FUNCTIONAL FAIL` (Matched historic run)
- `adder_cla__tb_adder`: Status=`PASS_REFERENCE_VERIFIED` (Matched historic run)
- `adder_csla__tb_adder`: Status=`PASS_REFERENCE_VERIFIED` (Matched historic run)
- `adder_rca__tb_adder`: Status=`PASS_REFERENCE_VERIFIED` (Matched historic run)
- `counter_updown_4bit__tb_counter`: Status=`PASS_REFERENCE_VERIFIED` (Matched historic run)
- `counter_faulty__tb_counter`: Status=`FUNCTIONAL FAIL` (Matched historic run)
- `alu_4bit__tb_alu`: Status=`PASS_TESTBENCH_ONLY` (Matched historic run)
- `alu8__tb_alu8`: Status=`EXECUTED / NOT VERIFIED` (Matched historic run)
- `adder_syntax_error__tb_adder`: Status=`COMPILE ERROR` (Matched historic run)
- `adder_infinite_loop__tb_adder`: Status=`TIMEOUT` (Matched historic run)
- `adder_x_output__tb_adder`: Status=`INVALID RESULTS` (Matched historic run)
- `multiplier__tb_multiplier`: Status=`TIMEOUT` (Matched historic run under 5s default watchdog)
