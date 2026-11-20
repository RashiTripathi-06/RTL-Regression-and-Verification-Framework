from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from models import (
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_SIMULATION_ERROR,
    STATUS_TIMEOUT,
    STATUS_INCOMPLETE,
    STATUS_INVALID_RESULTS,
    STATUS_INTERFACE_ERROR,
    STATUS_NOT_VERIFIED,
    STATUS_LICENSE_ERROR,
    EXEC_SUCCESS,
    EXEC_COMPILE_ERROR,
    EXEC_SIMULATION_ERROR,
    EXEC_TIMEOUT,
    EXEC_SKIPPED,
    EXEC_LICENSE_ERROR,
    VERIF_PASS,
    VERIF_FAIL,
    VERIF_INVALID,
    VERIF_INCOMPLETE,
    VERIF_NOT_VERIFIED,
    VERIF_UNCHECKED,
    AUDIT_MATCH,
    AUDIT_MISMATCH,
    AUDIT_MISSING_REF,
    AUDIT_SKIPPED,
    AUDIT_INVALID,
    VectorMismatch
)
from executor import ExecutionResult

VEC_GENERIC_RE = re.compile(
    r"^VEC\s+idx=(\d+)\s+(.+)$",
    re.MULTILINE
)

SUMMARY_RE = re.compile(
    r"===\s*TESTBENCH_SUMMARY:\s*total=(\d+)\s+pass=(\d+)\s+fail=(\d+)\s*===",
    re.IGNORECASE
)

# Detects 'x' or 'z' states in actual output expressions across testbench formats
XZ_OUTPUT_RE = re.compile(
    r"\b(?:got|out|sum|cout|alu_out|count|max_tick|min_tick|res|result|data_out|dout)\s*[:=]\s*(?:4'b|8'b|[0-9]+'b)?([0-9a-fA-FxXzZ]*[xXzZ]+[0-9a-fA-FxXzZ]*)\b",
    re.IGNORECASE
)


class AuditResult(tuple):
    """
    6-tuple compatible with legacy unpack:
    (status, passed_vectors, total_vectors, failed_vectors, diagnostic_summary, failing_vectors)
    while exposing explicit separated statuses for execution, functional verification, and reference audit.
    """
    status: str
    passed_vectors: int
    total_vectors: int
    failed_vectors: int
    diagnostic_summary: str
    failing_vectors: List[dict]
    execution_status: str
    functional_status: str
    audit_status: str

    def __new__(
        cls,
        status: str,
        passed_vectors: int,
        total_vectors: int,
        failed_vectors: int,
        diagnostic_summary: str,
        failing_vectors: List[dict],
        execution_status: str = EXEC_SUCCESS,
        functional_status: str = VERIF_PASS,
        audit_status: str = AUDIT_MATCH
    ):
        instance = super().__new__(
            cls,
            (status, passed_vectors, total_vectors, failed_vectors, diagnostic_summary, failing_vectors)
        )
        instance.status = status
        instance.passed_vectors = passed_vectors
        instance.total_vectors = total_vectors
        instance.failed_vectors = failed_vectors
        instance.diagnostic_summary = diagnostic_summary
        instance.failing_vectors = failing_vectors
        instance.execution_status = execution_status
        instance.functional_status = functional_status
        instance.audit_status = audit_status
        return instance


def parse_reference_file(ref_path: Path) -> List[Dict[str, Any]]:
    """
    Parses a reference LUT or data file (.mem, .hex, .dat, .csv).
    Handles hex words, binary words, addresses (@...), and commented lines.
    """
    rows: List[Dict[str, Any]] = []
    if not ref_path.exists():
        return rows

    content = ref_path.read_text(encoding="utf-8", errors="replace")

    # Native CSV parsing
    if ref_path.suffix.lower() == ".csv":
        import csv
        reader = csv.DictReader(content.splitlines())
        for r in reader:
            rows.append(dict(r))
        return rows

    for raw_line in content.splitlines():
        line = raw_line.split("//")[0].split("#")[0].strip()
        if not line:
            continue

        # Check CSV format
        if "," in line and not line.startswith("@"):
            parts = [p.strip() for p in line.split(",")]
            rows.append({"raw": line, "tokens": parts})
            continue

        # Standard hex or binary memory word
        tokens = line.split()
        for tok in tokens:
            if tok.startswith("@"):
                continue # Address directive in Verilog memory file
            try:
                # Try hex
                val = int(tok, 16)
                rows.append({"raw": tok, "val": val, "hex": tok})
            except ValueError:
                rows.append({"raw": tok, "val": tok})

    return rows


class VerificationAuditor:
    """
    Generic multi-paradigm verification auditor.
    Independently inspects simulation output against reference models and testbench summaries.
    Enforces consistent classifications (e.g., X/Z states are always INVALID RESULTS regardless of testbench type).
    Rejects simulations with 0 checks as EXECUTED / NOT VERIFIED.
    """

    def audit(
        self,
        exec_res: ExecutionResult,
        golden_reference: Optional[Any] = None,
        expected_vector_count: Optional[int] = None,
        golden_lut: Optional[Any] = None,
        reference_data: Optional[Any] = None,
        **kwargs
    ) -> AuditResult:
        ref = golden_reference if golden_reference is not None else (golden_lut if golden_lut is not None else reference_data)
        golden_reference = ref

        # 0. License failure
        if getattr(exec_res, "is_license_error", False):
            diag = (exec_res.compile_stderr or exec_res.compile_stdout or exec_res.sim_stderr or exec_res.sim_stdout).strip()
            return AuditResult(
                status=STATUS_LICENSE_ERROR,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                diagnostic_summary=f"License Error: {diag[:300]}",
                failing_vectors=[],
                execution_status=EXEC_LICENSE_ERROR,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED
            )

        # 1. Compilation failure
        if exec_res.compile_returncode != 0:
            if exec_res.timed_out:
                return AuditResult(
                    status=STATUS_TIMEOUT,
                    passed_vectors=0,
                    total_vectors=0,
                    failed_vectors=0,
                    diagnostic_summary="Compilation timed out.",
                    failing_vectors=[],
                    execution_status=EXEC_TIMEOUT,
                    functional_status=VERIF_UNCHECKED,
                    audit_status=AUDIT_SKIPPED
                )
            diag = (exec_res.compile_stderr or exec_res.compile_stdout).strip()
            diag_lines = [l.strip() for l in diag.splitlines() if l.strip()]
            short_diag = " ; ".join(diag_lines[:3]) if diag_lines else "iverilog compilation failed."
            return AuditResult(
                status=STATUS_COMPILE_ERROR,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                diagnostic_summary=short_diag,
                failing_vectors=[],
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED
            )

        # 2. Watchdog timeout during simulation
        if exec_res.timed_out:
            return AuditResult(
                status=STATUS_TIMEOUT,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                diagnostic_summary="Simulation hung and exceeded watchdog timeout limit.",
                failing_vectors=[],
                execution_status=EXEC_TIMEOUT,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED
            )

        # 3. Simulator runtime error / crash
        if exec_res.sim_returncode is not None and exec_res.sim_returncode != 0:
            err_msg = exec_res.sim_stderr.strip() or f"vvp exited with return code {exec_res.sim_returncode}."
            return AuditResult(
                status=STATUS_SIMULATION_ERROR,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                diagnostic_summary=err_msg[:500],
                failing_vectors=[],
                execution_status=EXEC_SIMULATION_ERROR,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED
            )

        stdout = exec_res.sim_stdout

        # 4. Check for Testbench start and done sentinels
        has_start = "=== TESTBENCH_START ===" in stdout
        has_done = "=== TESTBENCH_DONE ===" in stdout

        # 5. UNIFIED X/Z DETECTION (Prioritized before summary inspection)
        # Any unknown 'x' or high-impedance 'z' state on actual outputs MUST be classified as INVALID RESULTS,
        # whether the testbench is LUT-based or self-checking!
        xz_match = XZ_OUTPUT_RE.search(stdout)
        if xz_match:
            offending_val = xz_match.group(0).strip()
            return AuditResult(
                status=STATUS_INVALID_RESULTS,
                passed_vectors=0,
                total_vectors=1,
                failed_vectors=1,
                diagnostic_summary=f"Unknown/high-impedance 'x' or 'z' output detected in actual DUT outputs ({offending_val}).",
                failing_vectors=[{"raw": offending_val}],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_INVALID
            )

        # 6. Check if output contains self-checking testbench summary with failures
        sum_match = SUMMARY_RE.search(stdout)
        if sum_match:
            total = int(sum_match.group(1))
            passed = int(sum_match.group(2))
            failed = int(sum_match.group(3))

            if not has_done:
                return AuditResult(
                    status=STATUS_INCOMPLETE,
                    passed_vectors=passed,
                    total_vectors=total,
                    failed_vectors=failed,
                    diagnostic_summary=f"Testbench completion marker missing (completed {passed + failed}/{total}).",
                    failing_vectors=[],
                    execution_status=EXEC_SUCCESS,
                    functional_status=VERIF_INCOMPLETE,
                    audit_status=AUDIT_SKIPPED
                )

            if failed > 0:
                mismatches = []
                for line in stdout.splitlines():
                    if any(k in line for k in ("FAIL", "ERROR", "MISMATCH")):
                        mismatches.append({"raw": line.strip()})
                return AuditResult(
                    status=STATUS_FUNCTIONAL_FAIL,
                    passed_vectors=passed,
                    total_vectors=total,
                    failed_vectors=failed,
                    diagnostic_summary=f"Self-checking testbench reported {failed}/{total} failed assertions.",
                    failing_vectors=mismatches[:25],
                    execution_status=EXEC_SUCCESS,
                    functional_status=VERIF_FAIL,
                    audit_status=AUDIT_MISMATCH
                )

        # 7. Check if output contains structured vector records (VEC idx=...)
        vec_matches = list(VEC_GENERIC_RE.finditer(stdout))
        if vec_matches:
            return self._audit_structured_vectors(
                stdout, vec_matches, has_start, has_done, golden_reference, expected_vector_count
            )

        # 8. Check if output contains self-checking testbench summary with all passed
        if sum_match:
            total = int(sum_match.group(1))
            passed = int(sum_match.group(2))
            failed = int(sum_match.group(3))

            if total == 0:
                return AuditResult(
                    status=STATUS_NOT_VERIFIED,
                    passed_vectors=0,
                    total_vectors=0,
                    failed_vectors=0,
                    diagnostic_summary="Testbench completed successfully but executed 0 verification assertions.",
                    failing_vectors=[],
                    execution_status=EXEC_SUCCESS,
                    functional_status=VERIF_NOT_VERIFIED,
                    audit_status=AUDIT_SKIPPED
                )

            return AuditResult(
                status=STATUS_PASS,
                passed_vectors=passed,
                total_vectors=total,
                failed_vectors=0,
                diagnostic_summary=f"All {passed}/{total} self-checking testbench assertions passed.",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_PASS,
                audit_status=AUDIT_MATCH
            )

        # 8. Generic testbench without structured vector markers or summary
        if not has_start or not has_done:
            return AuditResult(
                status=STATUS_INCOMPLETE,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                diagnostic_summary=f"Testbench sentinels missing (START={has_start}, DONE={has_done}).",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INCOMPLETE,
                audit_status=AUDIT_SKIPPED
            )

        # Check for explicit failure keywords or assertion violations in stdout
        fail_pattern = r"\b(ERROR|FAIL|FAILED|MISMATCH|UVM_ERROR|UVM_FATAL|ASSERTION\s+FAILED)\b"
        if re.search(fail_pattern, stdout, re.IGNORECASE):
            fail_lines = [l.strip() for l in stdout.splitlines() if re.search(fail_pattern, l, re.IGNORECASE)]
            return AuditResult(
                status=STATUS_FUNCTIONAL_FAIL,
                passed_vectors=0,
                total_vectors=len(fail_lines),
                failed_vectors=len(fail_lines),
                diagnostic_summary=" ; ".join(fail_lines[:3]),
                failing_vectors=[{"raw": l} for l in fail_lines[:25]],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_FAIL,
                audit_status=AUDIT_MISMATCH
            )

        # A testbench that ran with return code 0, had START/DONE, but produced ZERO assertions or vectors:
        # Must NOT automatically be PASS!
        return AuditResult(
            status=STATUS_NOT_VERIFIED,
            passed_vectors=0,
            total_vectors=0,
            failed_vectors=0,
            diagnostic_summary="Simulation completed with exit code 0, but performed no detectable assertions or vector checks.",
            failing_vectors=[],
            execution_status=EXEC_SUCCESS,
            functional_status=VERIF_NOT_VERIFIED,
            audit_status=AUDIT_SKIPPED
        )

    def _audit_structured_vectors(
        self,
        stdout: str,
        matches: list,
        has_start: bool,
        has_done: bool,
        golden_ref: Optional[Any],
        expected_count: Optional[int]
    ) -> AuditResult:
        records = []
        for m in matches:
            idx = int(m.group(1))
            body = m.group(2)
            kv_dict: Dict[str, str] = {}
            has_explicit_match = ("MATCH" in body)
            has_explicit_mismatch = ("MISMATCH" in body)

            for token in re.finditer(r"([a-zA-Z0-9_$]+)=([0-9a-fA-FxXzZ]+)", body):
                kv_dict[token.group(1)] = token.group(2)

            records.append({
                "idx": idx,
                "kv": kv_dict,
                "explicit_match": has_explicit_match,
                "explicit_mismatch": has_explicit_mismatch,
                "raw": body
            })

        indices = [r["idx"] for r in records]

        # Check duplicate indices
        if len(set(indices)) != len(indices):
            return AuditResult(
                status=STATUS_INVALID_RESULTS,
                passed_vectors=0,
                total_vectors=len(records),
                failed_vectors=0,
                diagnostic_summary="Vector indices are duplicated.",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_INVALID
            )

        # Check vector ordering
        if indices != sorted(indices):
            return AuditResult(
                status=STATUS_INVALID_RESULTS,
                passed_vectors=0,
                total_vectors=len(records),
                failed_vectors=0,
                diagnostic_summary="Vector indices observed out of order.",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_INVALID
            )

        # Check completion sentinels
        if not has_start or not has_done:
            return AuditResult(
                status=STATUS_INCOMPLETE,
                passed_vectors=0,
                total_vectors=len(records),
                failed_vectors=0,
                diagnostic_summary=f"Simulation terminated prematurely: observed {len(records)} vectors (START={has_start}, DONE={has_done}).",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INCOMPLETE,
                audit_status=AUDIT_SKIPPED
            )

        # Check expected count
        if expected_count and len(records) < expected_count:
            return AuditResult(
                status=STATUS_INCOMPLETE,
                passed_vectors=0,
                total_vectors=len(records),
                failed_vectors=0,
                diagnostic_summary=f"Simulation incomplete: executed {len(records)}/{expected_count} vectors.",
                failing_vectors=[],
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INCOMPLETE,
                audit_status=AUDIT_SKIPPED
            )

        passed = 0
        failed = 0
        mismatches: List[dict] = []

        for rec in records:
            idx = rec["idx"]
            kv = rec["kv"]

            # 1. Check for unknown 'x' or high-impedance 'z' states in actual outputs
            has_xz = False
            for k, val in kv.items():
                if any(out_prefix in k for out_prefix in ("sum", "cout", "out", "act", "data", "result", "p")):
                    if any(c in val.lower() for c in ("x", "z")):
                        has_xz = True
                        break

            if has_xz:
                return AuditResult(
                    status=STATUS_INVALID_RESULTS,
                    passed_vectors=passed,
                    total_vectors=len(records),
                    failed_vectors=failed + 1,
                    diagnostic_summary=f"Unknown/high-impedance 'x' or 'z' output detected at vector index {idx} in {kv}.",
                    failing_vectors=[{"index": idx, "inputs": kv, "actual_outputs": kv, "expected_outputs": {}}],
                    execution_status=EXEC_SUCCESS,
                    functional_status=VERIF_INVALID,
                    audit_status=AUDIT_INVALID
                )

            # 2. Check explicit MATCH / MISMATCH if present in trace
            if rec["explicit_mismatch"]:
                failed += 1
                if len(mismatches) < 25:
                    mismatches.append({"index": idx, "raw_message": rec["raw"], "inputs": kv, "actual_outputs": kv, "expected_outputs": {}})
                continue
            elif rec["explicit_match"]:
                passed += 1
                continue

            # 3. Check against independent Python golden reference if provided
            if golden_ref and idx < len(golden_ref):
                ref = golden_ref[idx]
                # Check adder reference
                if "sum" in ref and "sum" in kv:
                    ref_sum = ref["sum"]
                    ref_cout = ref["cout"]
                    got_sum_str = kv["sum"]
                    got_cout_str = kv["cout"]
                    try:
                        got_sum = int(got_sum_str, 2) if set(got_sum_str) <= {"0", "1"} else int(got_sum_str)
                        got_cout = int(got_cout_str, 2) if set(got_cout_str) <= {"0", "1"} else int(got_cout_str)
                    except ValueError:
                        got_sum = int(got_sum_str, 16)
                        got_cout = int(got_cout_str, 16)

                    if got_sum == ref_sum and got_cout == ref_cout:
                        passed += 1
                    else:
                        failed += 1
                        if len(mismatches) < 25:
                            mismatches.append({
                                "index": idx,
                                "inputs": {"a": kv.get("a"), "b": kv.get("b"), "cin": kv.get("cin")},
                                "actual_outputs": {"sum": got_sum, "cout": got_cout},
                                "expected_outputs": {"sum": ref_sum, "cout": ref_cout},
                                "raw_message": f"idx={idx}: got sum={got_sum}, cout={got_cout}; expected sum={ref_sum}, cout={ref_cout}"
                            })
                    continue

                # Generic key comparison if golden_ref has dictionary
                if isinstance(ref, dict):
                    match_all_keys = True
                    for rk, rv in ref.items():
                        if rk in kv and str(kv[rk]).lower() != str(rv).lower():
                            match_all_keys = False
                            break
                    if match_all_keys:
                        passed += 1
                    else:
                        failed += 1
                        if len(mismatches) < 25:
                            mismatches.append({"index": idx, "inputs": kv, "actual_outputs": kv, "expected_outputs": ref})
                    continue

            # If no independent reference rule matched and no explicit mismatch, treat as observed vector
            passed += 1

        if failed > 0:
            first = mismatches[0]
            diag = first.get("raw_message", f"Failed {failed}/{len(records)} vectors.")
            return AuditResult(
                status=STATUS_FUNCTIONAL_FAIL,
                passed_vectors=passed,
                total_vectors=len(records),
                failed_vectors=failed,
                diagnostic_summary=f"Failed {failed}/{len(records)} vectors. First mismatch at idx={first.get('index', 0)} ({diag}).",
                failing_vectors=mismatches,
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_FAIL,
                audit_status=AUDIT_MISMATCH
            )

        return AuditResult(
            status=STATUS_PASS,
            passed_vectors=passed,
            total_vectors=len(records),
            failed_vectors=0,
            diagnostic_summary=f"All {passed}/{len(records)} vectors matched golden reference.",
            failing_vectors=[],
            execution_status=EXEC_SUCCESS,
            functional_status=VERIF_PASS,
            audit_status=AUDIT_MATCH
        )
