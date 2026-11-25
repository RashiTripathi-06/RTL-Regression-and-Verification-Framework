from __future__ import annotations
import concurrent.futures
import csv
import hashlib
import importlib
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .executor import BaseSimulatorAdapter, IcarusSimulatorAdapter, IsolatedSimulatorExecutor, QuestaSimulatorAdapter
from .models import (
    AUDIT_MATCH,
    AUDIT_MISMATCH,
    AUDIT_SKIPPED,
    EXEC_COMPILE_ERROR,
    EXEC_LICENSE_ERROR,
    EXEC_SIMULATION_ERROR,
    EXEC_SUCCESS,
    EXEC_TIMEOUT,
    ModuleInfo,
    STATUS_COMPILE_ERROR,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_INCOMPLETE,
    STATUS_INVALID_OUTPUT,
    STATUS_INVALID_RESULTS,
    STATUS_LICENSE_ERROR,
    STATUS_PASS_APPROXIMATE_REFERENCE,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_REFERENCE_UNVALIDATED,
    STATUS_SIMULATION_ERROR,
    STATUS_TIMEOUT,
    STATUS_APPROXIMATION_WITHIN_BOUND,
    STATUS_APPROXIMATION_OUT_OF_BOUND,
    TestResult,
    VERIF_FAIL,
    VERIF_INVALID,
    VERIF_PASS,
    VerificationPlan,
    CompatibilityEvidence,
)
from .reference_verifier import (
    ParsedVector,
    ReferenceConfig,
    ReferenceHarnessGenerator,
    ReferenceTiming,
)


@dataclass
class VerificationStrategyConfig:
    """Generic configuration for configurable directed/random verification modes."""
    mode: str = "directed_random"
    test_count: int = 30000
    random_seed: int = 12345
    special_value_tests: bool = True
    boundary_tests: bool = True
    structured_tests: bool = True
    random_tests: bool = True
    preserve_original_testbench: bool = True
    run_special_value_suite: bool = True
    target_dut: Optional[str] = None
    generator: Optional[str] = None
    generator_params: Dict[str, Any] = field(default_factory=dict)
    approximate_evaluator: Optional[str] = None
    run_approximate_suite: bool = False
    nar_bit_pattern: Optional[int] = None
    timing: ReferenceTiming = field(default_factory=ReferenceTiming)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationStrategyConfig":
        t_data = data.get("timing", {}) or {}
        timing = ReferenceTiming(
            mode=t_data.get("mode", "combinational"),
            settling_time_ns=float(t_data.get("settling_time_ns", 5.0)),
            clock_signal=t_data.get("clock_signal"),
            clock_period_ns=float(t_data.get("clock_period_ns", 10.0)),
            reset_signal=t_data.get("reset_signal"),
            reset_active_level=int(t_data.get("reset_active_level", 0)),
            reset_duration_cycles=int(t_data.get("reset_duration_cycles", 2)),
            latency_cycles=int(t_data.get("latency_cycles", 1)),
        )
        raw_nar = data.get("nar_bit_pattern")
        nar_pat: Optional[int] = None
        if raw_nar is not None:
            if isinstance(raw_nar, int):
                nar_pat = raw_nar
            elif isinstance(raw_nar, str):
                nar_pat = int(raw_nar, 16) if raw_nar.lower().startswith("0x") else int(raw_nar)

        return cls(
            mode=str(data.get("mode", "directed_random")),
            test_count=int(data.get("test_count", 30000)),
            random_seed=int(data.get("random_seed", 12345)),
            special_value_tests=bool(data.get("special_value_tests", True)),
            boundary_tests=bool(data.get("boundary_tests", True)),
            structured_tests=bool(data.get("structured_tests", True)),
            random_tests=bool(data.get("random_tests", True)),
            preserve_original_testbench=bool(data.get("preserve_original_testbench", True)),
            run_special_value_suite=bool(data.get("run_special_value_suite", True)),
            target_dut=data.get("target_dut"),
            generator=data.get("generator"),
            generator_params=dict(data.get("generator_params", {}) or {}),
            approximate_evaluator=data.get("approximate_evaluator"),
            run_approximate_suite=bool(data.get("run_approximate_suite", False)),
            nar_bit_pattern=nar_pat,
            timing=timing,
        )


@dataclass
class GeneratedVector:
    index: int
    inputs: Dict[str, int]
    expected_outputs: Dict[str, int]
    category: str = "random"
    source: str = "generic"
    description: str = ""


def _load_plugin_callable(spec: str, root_dir: Optional[Path] = None) -> Any:
    """Dynamically loads a 'module.path:callable_name' plugin entrypoint."""
    mod_path, func_name = spec.split(":", 1)
    search_roots = []
    if root_dir:
        search_roots.extend([root_dir, root_dir.parent, root_dir.parent.parent])
    workspace_root = Path(__file__).resolve().parents[3]
    search_roots.append(workspace_root)
    for sr in search_roots:
        sr_str = str(sr.resolve())
        if sr.exists() and sr_str not in sys.path:
            sys.path.insert(0, sr_str)
    mod = importlib.import_module(mod_path)
    return getattr(mod, func_name)


class GenericVectorGenerator:
    """
    Project-independent vector generator.
    Delegates to a configured domain-specific generator callable when specified,
    or falls back to generic port-width-aware boundary and random stimulus generation.
    """

    @staticmethod
    def generate(
        strategy_cfg: VerificationStrategyConfig,
        dut: ModuleInfo,
        root_dir: Optional[Path] = None,
    ) -> List[GeneratedVector]:
        if strategy_cfg.generator:
            gen_fn = _load_plugin_callable(strategy_cfg.generator, root_dir=root_dir)
            raw_list = gen_fn(strategy_cfg, dut)
            out: List[GeneratedVector] = []
            for idx, item in enumerate(raw_list):
                out.append(GeneratedVector(
                    index=int(item.get("index", idx)),
                    inputs={k: int(v) for k, v in item["inputs"].items()},
                    expected_outputs={k: int(v) for k, v in item.get("expected_outputs", {}).items()},
                    category=str(item.get("category", "unknown")),
                    source=str(item.get("source", strategy_cfg.generator)),
                    description=str(item.get("description", "")),
                ))
            return out

        return GenericVectorGenerator._generate_generic_fallback(strategy_cfg, dut)

    @staticmethod
    def _generate_generic_fallback(
        strategy_cfg: VerificationStrategyConfig,
        dut: ModuleInfo,
    ) -> List[GeneratedVector]:
        input_ports = [
            dut.ports[p] for p in dut.port_order
            if p in dut.ports and dut.ports[p].direction == "input"
        ]
        if not input_ports:
            return []

        rng = random.Random(strategy_cfg.random_seed)
        vectors: List[GeneratedVector] = []
        seen: set[Tuple[int, ...]] = set()
        target = max(1, strategy_cfg.test_count)

        def _add(vals: Dict[str, int], cat: str) -> None:
            if len(vectors) >= target:
                return
            key = tuple(vals[p.name] for p in input_ports)
            if key in seen:
                return
            seen.add(key)
            vectors.append(GeneratedVector(
                index=len(vectors),
                inputs=vals,
                expected_outputs={},
                category=cat,
                source=f"generic_fallback_seed_{strategy_cfg.random_seed}",
            ))

        if strategy_cfg.boundary_tests:
            zero_vec = {p.name: 0 for p in input_ports}
            max_vec = {p.name: (1 << (p.width if p.width > 0 else 1)) - 1 for p in input_ports}
            _add(zero_vec, "boundary")
            _add(max_vec, "boundary")

        if strategy_cfg.random_tests:
            attempts = 0
            max_attempts = target * 4
            while len(vectors) < target and attempts < max_attempts:
                attempts += 1
                vals = {
                    p.name: rng.randint(0, (1 << (p.width if p.width > 0 else 1)) - 1)
                    for p in input_ports
                }
                _add(vals, "random")

        return vectors


class StrategyVerificationRunner:
    """
    Executes configurable verification strategies (e.g., special_values, directed_random)
    with fast scoreboard auditing, NaR/unknown output classification, compilation caching,
    and full mismatch preservation.
    """

    def __init__(self, adapter: Optional[BaseSimulatorAdapter] = None):
        self.adapter = adapter or QuestaSimulatorAdapter()
        if not self.adapter.is_available():
            self.adapter = IcarusSimulatorAdapter()
        self.executor = IsolatedSimulatorExecutor(adapter=self.adapter)

    def run(
        self,
        dut: ModuleInfo,
        strategy_cfg: VerificationStrategyConfig,
        dependencies: List[Path],
        build_dir: Path,
        root_dir: Optional[Path] = None,
        timeout_seconds: float = 60.0,
    ) -> TestResult:
        self._root_dir = root_dir
        vectors = GenericVectorGenerator.generate(strategy_cfg, dut, root_dir=root_dir)
        return self.execute_vectors(
            dut=dut,
            strategy_cfg=strategy_cfg,
            vectors=vectors,
            dependencies=dependencies,
            build_dir=build_dir,
            timeout_seconds=timeout_seconds,
        )

    def execute_vectors(
        self,
        dut: ModuleInfo,
        strategy_cfg: VerificationStrategyConfig,
        vectors: List[GeneratedVector],
        dependencies: List[Path],
        build_dir: Path,
        timeout_seconds: float = 60.0,
    ) -> TestResult:
        start_ts = time.perf_counter()
        build_dir = build_dir.resolve()
        build_dir.mkdir(parents=True, exist_ok=True)
        plan_id = f"strategy_{strategy_cfg.mode}__{dut.name}"
        tb_name = f"strategy_{strategy_cfg.mode}_{dut.name}"

        if not vectors:
            return TestResult(
                plan_id=plan_id,
                dut_name=dut.name,
                tb_name=tb_name,
                status=STATUS_INCOMPLETE,
                diagnostic_summary=f"Strategy '{strategy_cfg.mode}' generated 0 test vectors.",
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_SKIPPED,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=0,
                executed_test_count=0,
                random_seed=strategy_cfg.random_seed,
                reference_status="NO_VECTORS",
            )

        input_ports = [
            p.name for p in dut.ports.values() if p.direction == "input"
        ]
        output_ports = [
            p.name for p in dut.ports.values() if p.direction == "output"
        ]
        ref_cfg = ReferenceConfig(
            file=build_dir / "generated_vectors.csv",
            format="csv",
            radix="hex",
            input_mapping={p: p for p in input_ports},
            output_mapping={p: p for p in output_ports},
            timing=strategy_cfg.timing,
        )

        # Persist vector metadata (category, source) for reproducibility
        meta_file = build_dir / "generated_vectors_meta.json"
        meta_payload = {
            "mode": strategy_cfg.mode,
            "configured_test_count": strategy_cfg.test_count,
            "generated_test_count": len(vectors),
            "random_seed": strategy_cfg.random_seed,
            "generator": strategy_cfg.generator,
        }
        meta_file.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")

        parsed_vectors = [
            ParsedVector(
                index=v.index,
                inputs=v.inputs,
                expected_outputs=v.expected_outputs,
                source_line=v.index + 1,
                raw_row={"category": v.category, "source": v.source, "description": v.description},
            )
            for v in vectors
        ]

        # Fast path: parallel simulation batching for large vector suites on Icarus Verilog
        if isinstance(self.adapter, IcarusSimulatorAdapter) and len(vectors) > 2500:
            return self._execute_batched_icarus(
                dut=dut,
                strategy_cfg=strategy_cfg,
                vectors=vectors,
                parsed_vectors=parsed_vectors,
                ref_cfg=ref_cfg,
                input_ports=input_ports,
                output_ports=output_ports,
                dependencies=dependencies,
                build_dir=build_dir,
                timeout_seconds=timeout_seconds,
                start_ts=start_ts,
            )

        harness_file, mem_file = ReferenceHarnessGenerator.generate(
            dut, ref_cfg, parsed_vectors, build_dir
        )

        required_sources = list(dependencies)
        if dut.file_path.resolve() not in [p.resolve() for p in required_sources]:
            required_sources.append(dut.file_path.resolve())
        required_sources.append(harness_file.resolve())

        plan = VerificationPlan(
            plan_id=plan_id,
            dut_name=dut.name,
            dut_module=dut.name,
            dut_file=dut.file_path,
            tb_name=f"harness_{strategy_cfg.mode}_{dut.name}",
            tb_module=f"harness_{dut.name}",
            tb_file=harness_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason=f"Synthesized Strategy Harness ({strategy_cfg.mode})",
                match_type="STRATEGY_HARNESS",
                expected_module_name=dut.name,
                actual_module_name=dut.name,
            ),
            required_sources=required_sources,
            data_files=[mem_file],
            build_dir=build_dir,
            timeout_seconds=timeout_seconds,
            iverilog_flags=["-g2012"],
            verification_path="PATH_B_STRATEGY",
        )

        # Compilation cache check: reuse .vvp when RTL & harness sources are unchanged
        src_hasher = hashlib.sha256()
        for src in required_sources:
            if src.exists():
                src_hasher.update(src.read_bytes())
        src_hash = src_hasher.hexdigest()
        compile_cache_file = build_dir / ".compile_hash"
        cached_vvp = build_dir / f"sim_{plan.plan_id}.vvp"

        sim_rc: Optional[int] = None
        sim_out = ""
        sim_err = ""
        timed_out = False

        if (
            isinstance(self.adapter, IcarusSimulatorAdapter)
            and cached_vvp.exists()
            and compile_cache_file.exists()
            and compile_cache_file.read_text(encoding="utf-8").strip() == src_hash
        ):
            sim_rc, sim_out, sim_err, timed_out = self.adapter.simulate(plan, build_dir, cached_vvp)
            comp_rc, comp_out, comp_err, is_lic = 0, "", "", False
        else:
            exec_res = self.executor.execute(plan)
            comp_rc = exec_res.compile_returncode
            comp_out = exec_res.compile_stdout
            comp_err = exec_res.compile_stderr
            sim_rc = exec_res.sim_returncode
            sim_out = exec_res.sim_stdout
            sim_err = exec_res.sim_stderr
            timed_out = exec_res.timed_out
            is_lic = exec_res.is_license_error
            if comp_rc == 0 and not timed_out and not is_lic and cached_vvp.exists():
                compile_cache_file.write_text(src_hash, encoding="utf-8")

        elapsed = round(time.perf_counter() - start_ts, 4)

        if is_lic:
            return TestResult(
                plan_id=plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_LICENSE_ERROR,
                diagnostic_summary=f"License Error: {comp_err or sim_err}",
                execution_status=EXEC_LICENSE_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=elapsed,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                random_seed=strategy_cfg.random_seed,
            )

        if comp_rc != 0:
            return TestResult(
                plan_id=plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_COMPILE_ERROR,
                diagnostic_summary=f"Harness compilation failed (rc={comp_rc}): {comp_err or comp_out}",
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=elapsed,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                random_seed=strategy_cfg.random_seed,
            )

        if timed_out:
            return TestResult(
                plan_id=plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_TIMEOUT,
                diagnostic_summary=f"Strategy simulation timed out after {timeout_seconds}s.",
                execution_status=EXEC_TIMEOUT,
                functional_status=VERIF_INVALID,
                elapsed_seconds=elapsed,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                random_seed=strategy_cfg.random_seed,
            )

        if sim_rc != 0:
            return TestResult(
                plan_id=plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_SIMULATION_ERROR,
                diagnostic_summary=f"Harness simulation error: {sim_err}",
                execution_status=EXEC_SIMULATION_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=elapsed,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                random_seed=strategy_cfg.random_seed,
            )

        actual_csv = build_dir / "actual_outputs.csv"
        return self._audit_outputs(
            actual_csv=actual_csv,
            vectors=vectors,
            output_ports=output_ports,
            dut=dut,
            plan=plan,
            strategy_cfg=strategy_cfg,
            build_dir=build_dir,
            start_ts=start_ts,
        )

    def _execute_batched_icarus(
        self,
        dut: ModuleInfo,
        strategy_cfg: VerificationStrategyConfig,
        vectors: List[GeneratedVector],
        parsed_vectors: List[ParsedVector],
        ref_cfg: ReferenceConfig,
        input_ports: List[str],
        output_ports: List[str],
        dependencies: List[Path],
        build_dir: Path,
        timeout_seconds: float,
        start_ts: float,
    ) -> TestResult:
        """
        Compiles a single batch-sized harness once and executes N simulation batches
        in parallel via ThreadPoolExecutor, then merges actual_outputs.csv.
        """
        num_workers = min(4, max(2, os.cpu_count() or 4))
        batch_size = (len(vectors) + num_workers - 1) // num_workers
        batches: List[List[ParsedVector]] = [
            parsed_vectors[i : i + batch_size]
            for i in range(0, len(parsed_vectors), batch_size)
        ]

        # Pad the template batch to batch_size so one compiled .vvp serves all batches
        template_batch = list(batches[0])
        harness_file, _ = ReferenceHarnessGenerator.generate(
            dut, ref_cfg, template_batch, build_dir
        )

        required_sources = list(dependencies)
        if dut.file_path.resolve() not in [p.resolve() for p in required_sources]:
            required_sources.append(dut.file_path.resolve())
        required_sources.append(harness_file.resolve())

        plan_id = f"strategy_{strategy_cfg.mode}__{dut.name}"
        plan = VerificationPlan(
            plan_id=plan_id,
            dut_name=dut.name,
            dut_module=dut.name,
            dut_file=dut.file_path,
            tb_name=f"harness_{strategy_cfg.mode}_{dut.name}",
            tb_module=f"harness_{dut.name}",
            tb_file=harness_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason=f"Synthesized Batched Strategy Harness ({strategy_cfg.mode})",
                match_type="STRATEGY_HARNESS",
                expected_module_name=dut.name,
                actual_module_name=dut.name,
            ),
            required_sources=required_sources,
            data_files=[],
            build_dir=build_dir,
            timeout_seconds=timeout_seconds,
            iverilog_flags=["-g2012"],
            verification_path="PATH_B_STRATEGY",
        )

        src_hasher = hashlib.sha256()
        for src in required_sources:
            if src.exists():
                src_hasher.update(src.read_bytes())
        src_hash = src_hasher.hexdigest()
        compile_cache_file = build_dir / ".compile_hash"
        sim_vvp = build_dir / f"sim_{plan.plan_id}.vvp"

        if not (
            sim_vvp.exists()
            and compile_cache_file.exists()
            and compile_cache_file.read_text(encoding="utf-8").strip() == src_hash
        ):
            comp_rc, comp_out, comp_err, sim_target, comp_to = self.adapter.compile(plan, build_dir)
            if comp_to:
                return TestResult(
                    plan_id=plan_id, dut_name=dut.name, tb_name=plan.tb_name,
                    status=STATUS_TIMEOUT, diagnostic_summary="Batched harness compilation timed out.",
                    execution_status=EXEC_TIMEOUT, functional_status=VERIF_INVALID,
                    elapsed_seconds=round(time.perf_counter() - start_ts, 4),
                    verification_mode=strategy_cfg.mode, test_strategy=strategy_cfg.mode,
                    configured_test_count=strategy_cfg.test_count, generated_test_count=len(vectors),
                    random_seed=strategy_cfg.random_seed,
                )
            if comp_rc != 0 or sim_target is None:
                return TestResult(
                    plan_id=plan_id, dut_name=dut.name, tb_name=plan.tb_name,
                    status=STATUS_COMPILE_ERROR,
                    diagnostic_summary=f"Batched harness compilation failed (rc={comp_rc}): {comp_err or comp_out}",
                    execution_status=EXEC_COMPILE_ERROR, functional_status=VERIF_INVALID,
                    elapsed_seconds=round(time.perf_counter() - start_ts, 4),
                    verification_mode=strategy_cfg.mode, test_strategy=strategy_cfg.mode,
                    configured_test_count=strategy_cfg.test_count, generated_test_count=len(vectors),
                    random_seed=strategy_cfg.random_seed,
                )
            compile_cache_file.write_text(src_hash, encoding="utf-8")

        # Format dut_inputs.mem for each batch and run vvp in parallel
        in_port_objs = [dut.ports[p] for p in dut.port_order if p in dut.ports and dut.ports[p].direction == "input"]
        total_input_bits = sum(p.width if p.width > 0 else 1 for p in in_port_objs)
        hex_chars = max(1, (total_input_bits + 3) // 4)

        def _run_batch(b_idx: int, batch_vecs: List[ParsedVector]) -> Tuple[int, str, str, bool, Path]:
            b_dir = build_dir / f"batch_{b_idx}"
            b_dir.mkdir(parents=True, exist_ok=True)
            mem_lines = []
            for pv in batch_vecs:
                packed = 0
                for p in in_port_objs:
                    w = p.width if p.width > 0 else 1
                    val = pv.inputs[p.name] & ((1 << w) - 1)
                    packed = (packed << w) | val
                mem_lines.append(f"{packed:0{hex_chars}x}")
            while len(mem_lines) < batch_size:
                mem_lines.append(mem_lines[-1])
            (b_dir / "dut_inputs.mem").write_text("\n".join(mem_lines) + "\n", encoding="utf-8")
            rc, out, err, to = self.adapter.simulate(plan, b_dir, sim_vvp)
            return rc, out, err, to, b_dir / "actual_outputs.csv"

        batch_results: List[Optional[Tuple[int, str, str, bool, Path]]] = [None] * len(batches)
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
            fut_map = {pool.submit(_run_batch, i, b): i for i, b in enumerate(batches)}
            for fut in concurrent.futures.as_completed(fut_map):
                batch_results[fut_map[fut]] = fut.result()

        # Merge actual_outputs.csv in order
        merged_csv = build_dir / "actual_outputs.csv"
        header_written = False
        global_idx = 0
        with open(merged_csv, "w", newline="", encoding="utf-8") as out_f:
            writer = csv.writer(out_f)
            for i, b_res in enumerate(batch_results):
                assert b_res is not None
                rc, out, err, to, b_csv = b_res
                if to:
                    return TestResult(
                        plan_id=plan_id, dut_name=dut.name, tb_name=plan.tb_name,
                        status=STATUS_TIMEOUT, diagnostic_summary=f"Batch {i} simulation timed out.",
                        execution_status=EXEC_TIMEOUT, functional_status=VERIF_INVALID,
                        elapsed_seconds=round(time.perf_counter() - start_ts, 4),
                        verification_mode=strategy_cfg.mode, test_strategy=strategy_cfg.mode,
                        configured_test_count=strategy_cfg.test_count, generated_test_count=len(vectors),
                        random_seed=strategy_cfg.random_seed,
                    )
                if rc != 0 or not b_csv.exists():
                    return TestResult(
                        plan_id=plan_id, dut_name=dut.name, tb_name=plan.tb_name,
                        status=STATUS_SIMULATION_ERROR, diagnostic_summary=f"Batch {i} failed (rc={rc}): {err}",
                        execution_status=EXEC_SIMULATION_ERROR, functional_status=VERIF_INVALID,
                        elapsed_seconds=round(time.perf_counter() - start_ts, 4),
                        verification_mode=strategy_cfg.mode, test_strategy=strategy_cfg.mode,
                        configured_test_count=strategy_cfg.test_count, generated_test_count=len(vectors),
                        random_seed=strategy_cfg.random_seed,
                    )
                with open(b_csv, "r", encoding="utf-8", errors="replace") as bf:
                    b_reader = csv.reader(bf)
                    b_header = next(b_reader, None)
                    if b_header and not header_written:
                        writer.writerow(b_header)
                        header_written = True
                    expected_len = len(batches[i])
                    for row_idx, row in enumerate(b_reader):
                        if row_idx >= expected_len:
                            break
                        row[0] = str(global_idx)
                        writer.writerow(row)
                        global_idx += 1

        return self._audit_outputs(
            actual_csv=merged_csv,
            vectors=vectors,
            output_ports=output_ports,
            dut=dut,
            plan=plan,
            strategy_cfg=strategy_cfg,
            build_dir=build_dir,
            start_ts=start_ts,
        )

    def _audit_outputs(
        self,
        actual_csv: Path,
        vectors: List[GeneratedVector],
        output_ports: List[str],
        dut: ModuleInfo,
        plan: VerificationPlan,
        strategy_cfg: VerificationStrategyConfig,
        build_dir: Path,
        start_ts: float,
    ) -> TestResult:
        if not actual_csv.exists():
            elapsed = round(time.perf_counter() - start_ts, 4)
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_INCOMPLETE,
                total_vectors=len(vectors),
                failed_vectors=len(vectors),
                elapsed_seconds=elapsed,
                diagnostic_summary="Simulation failed to produce actual_outputs.csv.",
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_MISMATCH,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                executed_test_count=0,
                random_seed=strategy_cfg.random_seed,
                reference_status="INCOMPLETE_SIMULATION",
            )

        with open(actual_csv, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                elapsed = round(time.perf_counter() - start_ts, 4)
                return TestResult(
                    plan_id=plan.plan_id,
                    dut_name=dut.name,
                    tb_name=plan.tb_name,
                    status=STATUS_INVALID_RESULTS,
                    total_vectors=len(vectors),
                    failed_vectors=len(vectors),
                    elapsed_seconds=elapsed,
                    diagnostic_summary="actual_outputs.csv is empty.",
                    execution_status=EXEC_SUCCESS,
                    functional_status=VERIF_INVALID,
                    audit_status=AUDIT_MISMATCH,
                    verification_mode=strategy_cfg.mode,
                    test_strategy=strategy_cfg.mode,
                    configured_test_count=strategy_cfg.test_count,
                    generated_test_count=len(vectors),
                    executed_test_count=0,
                    random_seed=strategy_cfg.random_seed,
                    reference_status="INVALID_RESULTS",
                )
            col_idx = {name.strip(): i for i, name in enumerate(header)}
            rows = list(reader)

        executed_count = len(rows)
        if executed_count != len(vectors):
            elapsed = round(time.perf_counter() - start_ts, 4)
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_INCOMPLETE if executed_count < len(vectors) else STATUS_INVALID_RESULTS,
                total_vectors=len(vectors),
                failed_vectors=abs(len(vectors) - executed_count),
                elapsed_seconds=elapsed,
                diagnostic_summary=f"Expected {len(vectors)} output rows, captured {executed_count}.",
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_MISMATCH,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                executed_test_count=executed_count,
                random_seed=strategy_cfg.random_seed,
                reference_status="INCOMPLETE_SIMULATION",
            )

        # Approximate-reference mode: delegate evaluation to configured plugin evaluator
        if strategy_cfg.mode == "approximate_reference":
            return self._audit_approximate(
                rows=rows,
                col_idx=col_idx,
                vectors=vectors,
                output_ports=output_ports,
                dut=dut,
                plan=plan,
                strategy_cfg=strategy_cfg,
                build_dir=build_dir,
                start_ts=start_ts,
            )

        out_col_indices = [(p, col_idx[p]) for p in output_ports if p in col_idx]
        has_oracle = bool(vectors[0].expected_outputs)
        nar_pat = strategy_cfg.nar_bit_pattern

        passed = 0
        failed = 0
        unknown_outputs = 0
        nar_outputs = 0
        cat_stats: Dict[str, Dict[str, int]] = {}
        all_mismatches: List[Dict[str, Any]] = []

        for idx, row in enumerate(rows):
            vec = vectors[idx]
            cat = vec.category or "unknown"
            st = cat_stats.setdefault(cat, {"total": 0, "passed": 0, "failed": 0, "unknown": 0, "nar": 0})
            st["total"] += 1

            row_unknown = False
            row_failed = False
            row_nar = False
            act_dict: Dict[str, str] = {}
            exp_dict: Dict[str, str] = {}

            for port_name, c_i in out_col_indices:
                act_str = row[c_i].strip().lower() if c_i < len(row) else ""
                act_dict[port_name] = act_str

                if not act_str or "x" in act_str or "z" in act_str:
                    row_unknown = True
                    row_failed = True
                    if has_oracle and port_name in vec.expected_outputs:
                        exp_dict[port_name] = f"{vec.expected_outputs[port_name]:04x}"
                    continue

                try:
                    act_val = int(act_str, 16)
                except ValueError:
                    row_unknown = True
                    row_failed = True
                    continue

                if nar_pat is not None and act_val == nar_pat:
                    row_nar = True

                if has_oracle and port_name in vec.expected_outputs:
                    exp_val = vec.expected_outputs[port_name]
                    exp_dict[port_name] = f"{exp_val:04x}"
                    if act_val != exp_val:
                        row_failed = True

            if row_nar:
                nar_outputs += 1
                st["nar"] += 1

            if row_unknown:
                unknown_outputs += 1
                st["unknown"] += 1

            if row_failed:
                failed += 1
                st["failed"] += 1
                all_mismatches.append({
                    "index": idx,
                    "category": cat,
                    "source": vec.source,
                    "description": vec.description,
                    "inputs": {k: f"{v:04x}" for k, v in vec.inputs.items()},
                    "actual_outputs": act_dict,
                    "expected_outputs": exp_dict,
                })
            else:
                passed += 1
                st["passed"] += 1

        # Preserve all mismatches to disk without truncation
        mismatch_file_rel = ""
        if all_mismatches:
            mm_csv = build_dir / "all_mismatches.csv"
            with open(mm_csv, "w", newline="", encoding="utf-8") as mf:
                writer = csv.DictWriter(
                    mf,
                    fieldnames=["index", "category", "source", "description", "inputs", "expected_outputs", "actual_outputs"],
                )
                writer.writeheader()
                for m in all_mismatches:
                    writer.writerow({
                        "index": m["index"],
                        "category": m["category"],
                        "source": m["source"],
                        "description": m["description"],
                        "inputs": json.dumps(m["inputs"]),
                        "expected_outputs": json.dumps(m["expected_outputs"]),
                        "actual_outputs": json.dumps(m["actual_outputs"]),
                    })
            mismatch_file_rel = str(mm_csv)

        elapsed = max(round(time.perf_counter() - start_ts, 4), 0.0001)
        throughput = round(executed_count / elapsed, 2)

        if unknown_outputs > 0:
            status = STATUS_INVALID_RESULTS
            func_status = VERIF_INVALID
            audit_status = AUDIT_MISMATCH
            ref_status = "INVALID_UNKNOWN_OUTPUTS"
            diag = (
                f"[{strategy_cfg.mode}] Detected {unknown_outputs} unknown (X/Z) outputs out of "
                f"{executed_count} vectors ({failed} total failures, {nar_outputs} NaR outputs)."
            )
        elif not has_oracle:
            status = STATUS_INCOMPLETE
            func_status = VERIF_INVALID
            audit_status = AUDIT_SKIPPED
            ref_status = "NO_REFERENCE_ORACLE"
            diag = f"[{strategy_cfg.mode}] Executed {executed_count} vectors with no reference oracle."
        elif failed > 0:
            status = STATUS_FUNCTIONAL_FAIL
            func_status = VERIF_FAIL
            audit_status = AUDIT_MISMATCH
            ref_status = "REFERENCE_MISMATCH"
            first = all_mismatches[0]
            diag = (
                f"[{strategy_cfg.mode}] {passed}/{executed_count} passed, {failed} failed "
                f"({unknown_outputs} X/Z, {nar_outputs} NaR). First mismatch idx={first['index']} "
                f"({first['category']}): in={first['inputs']} exp={first['expected_outputs']} got={first['actual_outputs']}"
            )
        else:
            status = STATUS_PASS_REFERENCE_VERIFIED
            func_status = VERIF_PASS
            audit_status = AUDIT_MATCH
            ref_status = "REFERENCE_VERIFIED"
            diag = (
                f"[{strategy_cfg.mode}] All {passed}/{executed_count} vectors verified against reference "
                f"({nar_outputs} NaR outputs, {throughput:.1f} vec/s)."
            )

        return TestResult(
            plan_id=plan.plan_id,
            dut_name=dut.name,
            tb_name=plan.tb_name,
            status=status,
            passed_vectors=passed,
            total_vectors=executed_count,
            failed_vectors=failed,
            elapsed_seconds=elapsed,
            diagnostic_summary=diag,
            failing_vectors=all_mismatches[:100],
            confidence="CONFIRMED",
            execution_status=EXEC_SUCCESS,
            functional_status=func_status,
            audit_status=audit_status,
            simulator_name=self.adapter.name,
            verification_mode=strategy_cfg.mode,
            test_strategy=strategy_cfg.mode,
            configured_test_count=strategy_cfg.test_count,
            generated_test_count=len(vectors),
            executed_test_count=executed_count,
            unknown_outputs=unknown_outputs,
            nar_outputs=nar_outputs,
            throughput_vps=throughput,
            random_seed=strategy_cfg.random_seed,
            reference_status=ref_status,
            category_breakdown=cat_stats,
            mismatch_report_file=mismatch_file_rel,
        )

    def _audit_approximate(
        self,
        rows: List[List[str]],
        col_idx: Dict[str, int],
        vectors: List[GeneratedVector],
        output_ports: List[str],
        dut: ModuleInfo,
        plan: VerificationPlan,
        strategy_cfg: VerificationStrategyConfig,
        build_dir: Path,
        start_ts: float,
    ) -> TestResult:
        """
        Generic approximate-reference audit hook.
        Parses simulator hex outputs (treating X/Z as None) and delegates
        numerical/bound evaluation to `strategy_cfg.approximate_evaluator`.
        """
        executed_count = len(rows)
        elapsed = max(round(time.perf_counter() - start_ts, 4), 0.0001)
        throughput = round(executed_count / elapsed, 2)

        if not strategy_cfg.approximate_evaluator:
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_REFERENCE_UNVALIDATED,
                total_vectors=executed_count,
                elapsed_seconds=elapsed,
                diagnostic_summary="No approximate_evaluator plugin configured for approximate_reference mode.",
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INVALID,
                audit_status=AUDIT_SKIPPED,
                simulator_name=self.adapter.name,
                verification_mode=strategy_cfg.mode,
                test_strategy=strategy_cfg.mode,
                configured_test_count=strategy_cfg.test_count,
                generated_test_count=len(vectors),
                executed_test_count=executed_count,
                throughput_vps=throughput,
                random_seed=strategy_cfg.random_seed,
                reference_status="REFERENCE_UNVALIDATED",
            )

        out_col_indices = [(p, col_idx[p]) for p in output_ports if p in col_idx]
        nar_pat = strategy_cfg.nar_bit_pattern
        nar_outputs = 0
        actual_outputs_list: List[Optional[Dict[str, int]]] = []

        for row in rows:
            row_map: Dict[str, int] = {}
            row_invalid = False
            for port_name, c_i in out_col_indices:
                act_str = row[c_i].strip().lower() if c_i < len(row) else ""
                if not act_str or "x" in act_str or "z" in act_str:
                    row_invalid = True
                    break
                try:
                    val = int(act_str, 16)
                except ValueError:
                    row_invalid = True
                    break
                if nar_pat is not None and val == nar_pat:
                    nar_outputs += 1
                row_map[port_name] = val
            actual_outputs_list.append(None if row_invalid else row_map)

        eval_fn = _load_plugin_callable(strategy_cfg.approximate_evaluator, root_dir=getattr(self, "_root_dir", None))
        eval_res = eval_fn(vectors, actual_outputs_list, strategy_cfg)

        status = str(eval_res.get("status", STATUS_REFERENCE_UNVALIDATED))
        bound_status = str(eval_res.get("bound_status", ""))
        passed = int(eval_res.get("rtl_tleap_exact_matches", 0))
        failed = int(eval_res.get("rtl_tleap_mismatches", 0))
        unknown_xz = int(eval_res.get("unknown_xz_count", 0))
        mismatches = list(eval_res.get("mismatches", []))

        mismatch_file_rel = ""
        if mismatches:
            mm_csv = build_dir / "all_mismatches.csv"
            with open(mm_csv, "w", newline="", encoding="utf-8") as mf:
                writer = csv.DictWriter(
                    mf,
                    fieldnames=[
                        "index", "category", "source", "description",
                        "inputs", "expected_outputs", "actual_outputs",
                        "exact_posit_expected", "failure_type",
                    ],
                )
                writer.writeheader()
                for m in mismatches:
                    writer.writerow({
                        "index": m.get("index", ""),
                        "category": m.get("category", ""),
                        "source": m.get("source", ""),
                        "description": m.get("description", ""),
                        "inputs": json.dumps(m.get("inputs", {})),
                        "expected_outputs": json.dumps(m.get("expected_outputs", {})),
                        "actual_outputs": json.dumps(m.get("actual_outputs", {})),
                        "exact_posit_expected": m.get("exact_posit_expected", ""),
                        "failure_type": m.get("failure_type", ""),
                    })
            mismatch_file_rel = str(mm_csv)

        metrics_summary = {
            k: v for k, v in eval_res.items()
            if k not in ("mismatches",)
        }

        diag = (
            f"[{strategy_cfg.mode}] status={status} ({bound_status}): "
            f"RTL==Approx {passed}/{executed_count}, RTL==Exact {eval_res.get('rtl_exact_posit_matches', 0)}/{executed_count}, "
            f"within_bound={eval_res.get('within_bound_count', 0)}, out_of_bound={eval_res.get('out_of_bound_count', 0)}, "
            f"X/Z={unknown_xz}, special_err={eval_res.get('special_value_errors', 0)}, "
            f"mean_rel={eval_res.get('mean_rel_error', 0.0):.4%}, max_rel={eval_res.get('max_rel_error', 0.0):.4%}, "
            f"max_ulp={eval_res.get('max_ulp_diff', 0)}"
        )

        is_pass = status in (STATUS_PASS_APPROXIMATE_REFERENCE, STATUS_APPROXIMATION_WITHIN_BOUND)
        return TestResult(
            plan_id=plan.plan_id,
            dut_name=dut.name,
            tb_name=plan.tb_name,
            status=status,
            passed_vectors=passed,
            total_vectors=executed_count,
            failed_vectors=failed,
            elapsed_seconds=elapsed,
            diagnostic_summary=diag,
            failing_vectors=mismatches[:100],
            confidence="CONFIRMED",
            execution_status=EXEC_SUCCESS,
            functional_status=VERIF_PASS if is_pass else (VERIF_INVALID if status == STATUS_INVALID_OUTPUT else VERIF_FAIL),
            audit_status=AUDIT_MATCH if is_pass else AUDIT_MISMATCH,
            simulator_name=self.adapter.name,
            verification_mode=strategy_cfg.mode,
            test_strategy=strategy_cfg.mode,
            configured_test_count=strategy_cfg.test_count,
            generated_test_count=len(vectors),
            executed_test_count=executed_count,
            unknown_outputs=unknown_xz,
            nar_outputs=nar_outputs,
            throughput_vps=throughput,
            random_seed=strategy_cfg.random_seed,
            reference_status=bound_status or status,
            category_breakdown=eval_res.get("category_metrics"),
            mismatch_report_file=mismatch_file_rel,
            approximation_metrics=metrics_summary,
        )
