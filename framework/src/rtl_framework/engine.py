from __future__ import annotations
import argparse
import concurrent.futures
import datetime
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import (
    TestResult,
    VerificationPlan,
    STATUS_PASS,
    STATUS_NO_MATCH,
    STATUS_INTERFACE_ERROR,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_MISSING_REFERENCE,
    STATUS_NOT_VERIFIED,
    STATUS_REFERENCE_DISPUTED,
    STATUS_REFERENCE_UNAVAILABLE,
    EXEC_SUCCESS,
    EXEC_COMPILE_ERROR,
    EXEC_SIMULATION_ERROR,
    EXEC_TIMEOUT,
    EXEC_SKIPPED,
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
    AUDIT_INVALID
)
from .scanner import ProjectScanner
from .matcher import DUTTestbenchMatcher, DUTTestbenchMatch
from .planner import VerificationPlanner
from .executor import (
    IsolatedSimulatorExecutor,
    QuestaSimulatorAdapter,
    IcarusSimulatorAdapter,
    EdalizeSimulatorAdapter,
    VerilatorSimulatorAdapter
)
from .static_analyzer import StaticRTLAnalyzer
from .auditor import VerificationAuditor, parse_reference_file
from .cache_manager import CacheManager
from .report_generator import ReportGenerator

ROOT_DIR = Path(__file__).resolve().parents[1]

class RegressionEngine:
    """End-to-End Automated RTL Regression Verification Engine."""

    def __init__(self, root_dir: Optional[Path] = None, config_path: Optional[Path] = None, simulator: Optional[str] = None, timeout: Optional[float] = None):
        self.root_dir = (root_dir or ROOT_DIR).resolve()
        self.config_path = (config_path or (self.root_dir / "config.json")).resolve()
        self.config = self._load_config()
        if timeout is not None:
            self.config["timeout_seconds"] = timeout

        sim_choice = (simulator or self.config.get("simulator", "icarus")).lower()
        if sim_choice in ("questa", "modelsim", "vsim"):
            adapter = QuestaSimulatorAdapter()
            if not adapter.is_available():
                adapter = IcarusSimulatorAdapter()
        elif sim_choice == "edalize":
            adapter = EdalizeSimulatorAdapter()
        elif sim_choice == "verilator":
            adapter = VerilatorSimulatorAdapter()
        else:
            adapter = IcarusSimulatorAdapter()

        self.build_dir = (self.root_dir / self.config.get("build_dir", "build")).resolve()
        self.reports_dir = (self.root_dir / self.config.get("reports_dir", "reports")).resolve()
        self.logs_dir = self.reports_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        cache_file = self.root_dir / self.config.get("cache_file", ".regression_cache.json")
        history_file = self.reports_dir / "verification_history.jsonl"

        self.cache_mgr = CacheManager(cache_file)
        self.report_gen = ReportGenerator(self.reports_dir, history_file)
        self.executor = IsolatedSimulatorExecutor(adapter=adapter)
        self.auditor = VerificationAuditor()
        self.static_analyzer = StaticRTLAnalyzer()

    def _load_config(self) -> dict:
        cfg = {}
        if self.config_path.exists():
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            except Exception:
                cfg = {}

        # Also merge manifest.json if present
        manifest_path = self.root_dir / "manifest.json"
        if manifest_path.exists():
            try:
                m_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                cfg.setdefault("manifest", {}).update(m_data)
            except Exception:
                pass

        return cfg

    def run_plan(self, plan: VerificationPlan, force_rerun: bool = False) -> TestResult:
        start_ts = time.perf_counter()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_file = self.logs_dir / f"{plan.plan_id}.log"

        # 1. Check SHA-256 Merkle Incremental Cache
        if not force_rerun:
            cached_res = self.cache_mgr.get(plan)
            if cached_res:
                cached_res.elapsed_seconds = round(time.perf_counter() - start_ts, 4)
                return cached_res

        # 2. Check if testbench references missing reference files
        if plan.missing_reference_files:
            diag = f"Testbench references missing reference file(s): {plan.missing_reference_files}"
            log_file.write_text(f"[MISSING REFERENCE FILE ERROR]\n{diag}\n", encoding="utf-8")
            res = TestResult(
                plan_id=plan.plan_id,
                dut_name=plan.dut_name,
                tb_name=plan.tb_name,
                status=STATUS_MISSING_REFERENCE,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                elapsed_seconds=0.001,
                cached=False,
                diagnostic_summary=diag,
                confidence=plan.compatibility.confidence,
                execution_status=EXEC_SKIPPED,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_MISSING_REF,
                log_file=str(log_file.relative_to(self.root_dir)),
                timestamp=now_iso
            )
            self.cache_mgr.put(plan, res)
            return res

        # 3. Execute isolated simulation
        exec_res = self.executor.execute(plan)

        # 4. Write execution log
        log_content = [
            f"=== VERIFICATION PLAN: {plan.plan_id} ===",
            f"Timestamp: {now_iso}",
            f"DUT: {plan.dut_name} ({plan.dut_file})",
            f"Testbench: {plan.tb_name} ({plan.tb_file})",
            f"Confidence: {plan.compatibility.confidence}",
            f"Wrapper Used: {plan.wrapper_path is not None}",
            f"Sources: {[str(s) for s in plan.required_sources]}",
            f"Associated Data Files: {[str(d) for d in plan.data_files]}",
            f"Unused Reference Files: {plan.unused_reference_files}",
            "--- COMPILE STDOUT ---",
            exec_res.compile_stdout,
            "--- COMPILE STDERR ---",
            exec_res.compile_stderr,
            f"--- SIMULATION STDOUT (rc={exec_res.sim_returncode}, timeout={exec_res.timed_out}) ---",
            exec_res.sim_stdout,
            "--- SIMULATION STDERR ---",
            exec_res.sim_stderr,
        ]
        log_file.write_text("\n".join(log_content), encoding="utf-8")

        # 5. Load golden reference data specific to this plan's data files
        golden_ref = None
        expected_count = int(self.config.get("expected_vectors", 0)) if self.config.get("expected_vectors") else None
        for df in plan.data_files:
            if df.suffix.lower() in (".mem", ".hex", ".dat", ".csv"):
                try:
                    parsed_rows = parse_reference_file(df)
                    if parsed_rows:
                        golden_ref = parsed_rows
                        if expected_count is None:
                            expected_count = len(parsed_rows)
                except Exception:
                    pass

        # 6. Audit results with independent auditor
        audit_res = self.auditor.audit(
            exec_res=exec_res,
            golden_reference=golden_ref,
            expected_vector_count=expected_count
        )
        status, passed_v, total_v, failed_v, diag, mismatches = audit_res
        exec_status = getattr(audit_res, "execution_status", EXEC_SUCCESS)
        verif_status = getattr(audit_res, "functional_status", VERIF_PASS)
        aud_status = getattr(audit_res, "audit_status", AUDIT_MATCH)

        # 6b. Static RTL Analysis & Formal Linting
        static_data = None
        if plan.dut_module in self.static_analyzer.all_modules:
            dut_mod = self.static_analyzer.all_modules[plan.dut_module]
            static_rep = self.static_analyzer.analyze(dut_mod, plan.required_sources)
            from dataclasses import asdict
            static_data = asdict(static_rep)

        res = TestResult(
            plan_id=plan.plan_id,
            dut_name=plan.dut_name,
            tb_name=plan.tb_name,
            status=status,
            passed_vectors=passed_v,
            total_vectors=total_v,
            failed_vectors=failed_v,
            elapsed_seconds=round(time.perf_counter() - start_ts, 4),
            cached=False,
            diagnostic_summary=diag,
            failing_vectors=mismatches,
            wrapper_used=(plan.wrapper_path is not None),
            confidence=plan.compatibility.confidence,
            execution_status=exec_status,
            functional_status=verif_status,
            audit_status=aud_status,
            log_file=str(log_file.relative_to(self.root_dir)),
            timestamp=now_iso,
            static_analysis=static_data,
            simulator_name=exec_res.simulator_name
        )

        # 7. Store in Merkle cache
        self.cache_mgr.put(plan, res)
        return res

    def run_regression(
        self,
        force_rerun: bool = False,
        parallel: bool = True,
        max_workers: int = 4,
        dut_filter: Optional[List[str]] = None
    ) -> List[TestResult]:
        # Ensure golden reference exists if explicitly configured
        if "lut" in self.config:
            lut_path = self.root_dir / self.config["lut"]
            if not lut_path.exists() and "lut_generator" in self.config:
                try:
                    import importlib
                    mod_name, func_name = self.config["lut_generator"].split(":")
                    mod = importlib.import_module(mod_name)
                    getattr(mod, func_name)(lut_path)
                except Exception as e:
                    print(f"[WARN] Failed to generate configured reference file {lut_path}: {e}")

        # Stage 1: Discovery
        lib_dirs = self.config.get("library_dirs", [])
        scanner = ProjectScanner(self.root_dir, library_dirs=lib_dirs)
        project = scanner.scan()
        self.static_analyzer = StaticRTLAnalyzer(all_modules=project.all_modules)

        # Filter candidate DUTs if requested
        candidate_duts = project.candidate_duts
        if dut_filter:
            allowed = set(dut_filter)
            candidate_duts = [d for d in candidate_duts if d.name in allowed or d.file_path.stem in allowed]

        # Stage 2 & 3: Compatibility Matching (Strict Priority & Ambiguity Rejection)
        user_mappings = dict(self.config.get("dut_tb_mapping", {}))
        manifest = self.config.get("manifest", {})
        if "dut_tb_mapping" in manifest:
            user_mappings.update(manifest["dut_tb_mapping"])

        matcher = DUTTestbenchMatcher(
            all_modules=project.all_modules,
            supporting_modules=project.supporting_modules,
            user_mappings={"dut_tb_mapping": user_mappings}
        )
        valid_matches, iface_err_matches, unmatched_duts = matcher.match_all(candidate_duts, project.testbenches)

        # Separate executable matches from ambiguous matches
        executable_matches: List[DUTTestbenchMatch] = []
        ambiguous_matches: List[DUTTestbenchMatch] = []
        for m in valid_matches:
            if m.is_ambiguous or m.compatibility.is_ambiguous:
                ambiguous_matches.append(m)
            else:
                executable_matches.append(m)

        # Stage 4: Verification Planning (Accurate per-TB reference file association)
        ref_mappings = self.config.get("reference_files", {})
        if "reference_files" in manifest:
            ref_mappings.update(manifest["reference_files"])

        inc_dirs = [self.root_dir / d for d in self.config.get("include_dirs", []) if (self.root_dir / d).exists()]
        for inc_f in project.include_files:
            if inc_f.parent not in inc_dirs:
                inc_dirs.append(inc_f.parent)

        planner = VerificationPlanner(
            build_root=self.build_dir,
            all_modules=project.all_modules,
            data_files=project.data_files,
            include_dirs=inc_dirs,
            timeout_seconds=float(self.config.get("timeout_seconds", 5.0)),
            iverilog_flags=self.config.get("iverilog_flags", ["-g2012", "-Wall"]),
            explicit_ref_mappings=ref_mappings
        )

        plans = [planner.create_plan(m) for m in executable_matches]
        results: List[TestResult] = []

        # Stage 5 & 6: Isolated Execution and Auditing for Valid Plans
        # Strict constraint: Questa node-locked single-session license requires sequential execution (worker count = 1)
        if isinstance(self.executor.adapter, QuestaSimulatorAdapter):
            parallel = False
            max_workers = 1

        if parallel and len(plans) > 1:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                fut_to_plan = {
                    executor.submit(self.run_plan, p, force_rerun): p
                    for p in plans
                }
                for fut in concurrent.futures.as_completed(fut_to_plan):
                    results.append(fut.result())
        else:
            for p in plans:
                results.append(self.run_plan(p, force_rerun))

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Stage 5b: Path B - Multi-Source Reference Resolution & Independent Verification
        from .reference_manager import ReferenceResolver
        res_resolution = ReferenceResolver.resolve(self.config, self.root_dir)

        if res_resolution.case == "CASE_3_DISPUTED":
            for dut in candidate_duts:
                results.append(TestResult(
                    plan_id=f"ref_harness__{dut.name}",
                    dut_name=dut.name,
                    tb_name="REFERENCE_DISPUTED",
                    status=STATUS_REFERENCE_DISPUTED,
                    diagnostic_summary=res_resolution.diagnostic,
                    execution_status=EXEC_SKIPPED,
                    functional_status=VERIF_FAIL,
                    audit_status=AUDIT_MISMATCH,
                    reference_provenance=res_resolution.provenance,
                    failing_vectors=res_resolution.conflicting_vectors,
                    timestamp=now_iso
                ))
        elif res_resolution.case in ("CASE_1_PRIMARY_ACTIVE", "CASE_2_FALLBACK_ACTIVE"):
            ref_cfg = res_resolution.active_config
            if ref_cfg:
                from .reference_verifier import ReferenceVerificationEngine
                ref_engine = ReferenceVerificationEngine(adapter=self.executor.adapter)
                req_in = set(ref_cfg.input_mapping.values())
                req_out = set(ref_cfg.output_mapping.values())

                for dut in candidate_duts:
                    dut_p = set(dut.ports.keys())
                    if req_in.issubset(dut_p) and req_out.issubset(dut_p):
                        dep_res = planner.dep_resolver.resolve_dependencies(dut)
                        bdir = self.build_dir / f"ref_harness__{dut.name}"
                        res_ref = ref_engine.verify(
                            dut=dut,
                            config=ref_cfg,
                            dependencies=dep_res.required_source_files,
                            build_dir=bdir,
                            timeout_seconds=float(self.config.get("timeout_seconds", 30.0))
                        )
                        res_ref.reference_provenance = res_resolution.provenance
                        results.append(res_ref)
        elif res_resolution.case == "CASE_4_UNAVAILABLE" and ("reference_sources" in self.config or "professor_reference" in self.config):
            for dut in candidate_duts:
                results.append(TestResult(
                    plan_id=f"ref_harness__{dut.name}",
                    dut_name=dut.name,
                    tb_name="REFERENCE_UNAVAILABLE",
                    status=STATUS_REFERENCE_UNAVAILABLE,
                    diagnostic_summary=res_resolution.diagnostic,
                    execution_status=EXEC_SKIPPED,
                    functional_status=VERIF_UNCHECKED,
                    audit_status=AUDIT_SKIPPED,
                    reference_provenance=res_resolution.provenance,
                    timestamp=now_iso
                ))

        # Add records for Ambiguous Matches
        for amb_m in ambiguous_matches:
            log_file = self.logs_dir / f"{amb_m.dut.file_path.stem}__{amb_m.testbench.name}.log"
            diag = amb_m.ambiguity_reason or amb_m.compatibility.ambiguity_reason or "Ambiguous candidate interface mapping."
            log_file.write_text(f"[AMBIGUOUS MATCH ERROR]\n{diag}\n", encoding="utf-8")
            results.append(TestResult(
                plan_id=f"{amb_m.dut.file_path.stem}__{amb_m.testbench.name}",
                dut_name=amb_m.dut.file_path.stem,
                tb_name=amb_m.testbench.name,
                status=STATUS_AMBIGUOUS_MATCH,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                elapsed_seconds=0.001,
                cached=False,
                diagnostic_summary=diag,
                confidence=amb_m.compatibility.confidence,
                execution_status=EXEC_SKIPPED,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED,
                failing_vectors=[],
                wrapper_used=False,
                log_file=str(log_file.relative_to(self.root_dir)),
                timestamp=now_iso
            ))

        # Add records for Interface Error matches (structural mismatches on targeted modules)
        for iface_m in iface_err_matches:
            log_file = self.logs_dir / f"{iface_m.dut.file_path.stem}__{iface_m.testbench.name}.log"
            diag = " | ".join(iface_m.compatibility.mismatches)
            log_file.write_text(f"[INTERFACE ERROR]\n{diag}\n", encoding="utf-8")
            results.append(TestResult(
                plan_id=f"{iface_m.dut.file_path.stem}__{iface_m.testbench.name}",
                dut_name=iface_m.dut.file_path.stem,
                tb_name=iface_m.testbench.name,
                status=STATUS_INTERFACE_ERROR,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                elapsed_seconds=0.001,
                cached=False,
                diagnostic_summary=diag,
                confidence=iface_m.compatibility.confidence,
                execution_status=EXEC_SKIPPED,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED,
                failing_vectors=[],
                wrapper_used=False,
                log_file=str(log_file.relative_to(self.root_dir)),
                timestamp=now_iso
            ))

        # Add records for unmatched DUTs (STATUS_NO_MATCH)
        for unmatched in unmatched_duts:
            results.append(TestResult(
                plan_id=f"{unmatched.file_path.stem}__NO_TB",
                dut_name=unmatched.file_path.stem,
                tb_name="NONE",
                status=STATUS_NO_MATCH,
                passed_vectors=0,
                total_vectors=0,
                failed_vectors=0,
                elapsed_seconds=0.0,
                cached=False,
                diagnostic_summary=f"No compatible testbench found matching interface of '{unmatched.name}'.",
                confidence="CONFIRMED",
                execution_status=EXEC_SKIPPED,
                functional_status=VERIF_UNCHECKED,
                audit_status=AUDIT_SKIPPED,
                failing_vectors=[],
                wrapper_used=False,
                log_file="",
                timestamp=now_iso
            ))

        results.sort(key=lambda r: (r.dut_name, r.tb_name))

        # Stage 7 & 8: Reporting
        csv_path, json_path, html_path = self.report_gen.generate(
            results,
            project_name=self.config.get("project_name", "Automated RTL Regression Suite")
        )

        # Print terminal summary
        self._print_terminal_summary(results, csv_path, html_path)
        return results

    def replay_run(self, target_run_id: str) -> Optional[List[TestResult]]:
        hist_files = [
            self.reports_dir / "history.jsonl",
            self.reports_dir / "verification_history.jsonl"
        ]
        records = []
        for hf in hist_files:
            if hf.exists():
                for line in hf.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            records.append(json.loads(line.strip()))
                        except Exception:
                            pass

        matched = None
        for rec in reversed(records):
            r_id = rec.get("run_id", "")
            if r_id == target_run_id or r_id.startswith(target_run_id):
                matched = rec
                break

        if not matched:
            print(f"[ERROR] Replay failed: Run ID '{target_run_id}' not found.")
            available_ids = list(dict.fromkeys(r.get("run_id", "") for r in reversed(records) if r.get("run_id")))
            if available_ids:
                print(f"[INFO] Available Run IDs:\n  " + "\n  ".join(available_ids[:10]))
            return None

        print(f"\n[REPLAY] Replaying historic execution record:")
        print(f"  Run ID:    {matched.get('run_id')}")
        print(f"  Timestamp: {matched.get('timestamp')}")
        print(f"  Plans:     {matched.get('total_plans')} (Passed: {matched.get('passed')}, Failed: {matched.get('failed')})")
        print("-" * 80)

        hist_results = {r["plan_id"]: r for r in matched.get("results", [])}
        for pid, r in hist_results.items():
            print(f"  - {pid:<35} : {r.get('status')} ({r.get('diagnostic_summary', '')[:50]})")
        print("-" * 80)

        duts_to_rerun = list({r["dut_name"] for r in hist_results.values() if r.get("dut_name") and r.get("dut_name") != "NONE"})
        print(f"[REPLAY] Re-executing regression for DUTs: {duts_to_rerun}...")
        current_results = self.run_regression(dut_filter=duts_to_rerun if duts_to_rerun else None)

        print("\n" + "=" * 80)
        print("[REPLAY] VERIFICATION COMPARISON REPORT")
        print("=" * 80)
        divergence = False
        curr_map = {r.plan_id: r for r in current_results}
        for pid, h_res in hist_results.items():
            c_res = curr_map.get(pid)
            if not c_res:
                print(f"  [MISSING] Plan '{pid}' was executed in history but not in current replay.")
                divergence = True
            elif c_res.status != h_res.get("status"):
                print(f"  [DIVERGENCE] Plan '{pid}': Historic={h_res.get('status')} vs Current={c_res.status}")
                divergence = True
            else:
                print(f"  [CONSISTENT] Plan '{pid}': Status={c_res.status} matches historic run.")

        if not divergence:
            print("[SUCCESS] All replayed plans reproduced 100% identically.")
        else:
            print("[WARNING] Divergence detected during replay.")
        print("=" * 80 + "\n")
        return current_results

    def _print_terminal_summary(self, results: List[TestResult], csv_path: Path, html_path: Path):
        print("\n" + "=" * 122)
        print(f"{'DUT MODULE':<24} | {'TESTBENCH':<17} | {'STATUS':<17} | {'CONF':<9} | {'CACHE':<6} | {'VECTORS':<10} | {'TIME':<6} | {'DIAGNOSTIC'}")
        print("-" * 122)
        for r in results:
            cache_tag = "HIT" if r.cached else "RUN"
            vec_tag = f"{r.passed_vectors}/{r.total_vectors}"
            diag_short = r.diagnostic_summary[:40]
            print(f"{r.dut_name:<24} | {r.tb_name:<17} | {r.status:<17} | {r.confidence:<9} | {cache_tag:<6} | {vec_tag:<10} | {r.elapsed_seconds:>5.3f}s | {diag_short}")
        print("=" * 122)
        print(f"[REPORTS] CSV:  {csv_path}")
        print(f"[REPORTS] HTML: {html_path}\n")


def main():
    parser = argparse.ArgumentParser(description="Automated RTL Regression Testing Framework")
    parser.add_argument("--force", action="store_true", help="Force re-run of all plans, bypassing cache")
    parser.add_argument("--serial", action="store_true", help="Run simulations sequentially instead of parallel")
    parser.add_argument("--workers", type=int, default=4, help="Maximum worker threads for simulation")
    parser.add_argument("--duts", nargs="*", help="Specific DUT names to filter and verify")
    parser.add_argument("--simulator", choices=["icarus", "iverilog", "questa", "modelsim", "vsim", "edalize", "verilator"], default=None, help="Simulator adapter backend")
    parser.add_argument("--config", type=str, default=None, help="Path to configuration JSON")
    parser.add_argument("--project-dir", type=str, default=None, help="Root directory of HDL project")
    parser.add_argument("--timeout", type=float, default=None, help="Simulation execution timeout in seconds")
    parser.add_argument("--replay", type=str, default=None, help="Replay a historic execution run by Run ID or prefix")
    args = parser.parse_args()

    project_root = Path(args.project_dir).resolve() if args.project_dir else None
    config_file = Path(args.config).resolve() if args.config else None

    engine = RegressionEngine(
        root_dir=project_root,
        config_path=config_file,
        simulator=args.simulator,
        timeout=args.timeout
    )

    if args.replay:
        engine.replay_run(args.replay)
    else:
        results = engine.run_regression(
            force_rerun=args.force,
            parallel=not args.serial,
            max_workers=args.workers,
            dut_filter=args.duts
        )


if __name__ == "__main__":
    main()
