from __future__ import annotations
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from models import (
    ModuleInfo,
    PortSpec,
    VectorMismatch,
    TestResult,
    VerificationPlan,
    CompatibilityEvidence,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_INVALID_RESULTS,
    STATUS_INCOMPLETE,
    STATUS_COMPILE_ERROR,
    STATUS_SIMULATION_ERROR,
    STATUS_TIMEOUT,
    STATUS_LICENSE_ERROR,
    EXEC_SUCCESS,
    EXEC_COMPILE_ERROR,
    EXEC_SIMULATION_ERROR,
    EXEC_TIMEOUT,
    EXEC_LICENSE_ERROR,
    VERIF_PASS,
    VERIF_FAIL,
    VERIF_INVALID,
    VERIF_INCOMPLETE,
    AUDIT_MATCH,
    AUDIT_MISMATCH,
    AUDIT_INVALID,
)
from executor import BaseSimulatorAdapter, IsolatedSimulatorExecutor, QuestaSimulatorAdapter, IcarusSimulatorAdapter


@dataclass
class ReferenceTiming:
    mode: str = "combinational"  # "combinational" or "sequential"
    settling_time_ns: float = 1.0  # settling delay for combinational logic
    clock_signal: Optional[str] = None
    clock_period_ns: float = 10.0
    reset_signal: Optional[str] = None
    reset_active_level: int = 0
    reset_duration_cycles: int = 2
    latency_cycles: int = 1  # clock cycles between driving input and sampling output


@dataclass
class ReferenceConfig:
    file: Path
    format: str = "csv"  # "csv", "json", "hex", "mem", "table"
    radix: str = "hex"  # "hex", "dec", "bin"
    input_mapping: Dict[str, str] = field(default_factory=dict)   # ref_field -> dut_input_port
    output_mapping: Dict[str, str] = field(default_factory=dict)  # ref_field -> dut_output_port
    timing: ReferenceTiming = field(default_factory=ReferenceTiming)
    file_hash: str = ""

    def __post_init__(self):
        self.file = Path(self.file)
        if self.file.exists() and not self.file_hash:
            self.file_hash = hashlib.sha256(self.file.read_bytes()).hexdigest()


@dataclass
class ParsedVector:
    index: int
    inputs: Dict[str, int]
    expected_outputs: Dict[str, int]
    source_line: int
    raw_row: Any


class ReferenceDataLoader:
    """Loads and validates reference vectors from CSV, JSON, HEX, MEM, or tabular files."""

    @staticmethod
    def _parse_val(raw: Any, radix: str) -> Optional[int]:
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.lower() in ("x", "z", "none", "null", "-"):
            return None
        # Remove Verilog width prefix if present, e.g. 16'h4800 -> 4800
        m = re.match(r"^\d+'[hH]([0-9a-fA-F_]+)$", s)
        if m:
            return int(m.group(1).replace("_", ""), 16)
        m = re.match(r"^\d+'[bB]([01_]+)$", s)
        if m:
            return int(m.group(1).replace("_", ""), 2)
        m = re.match(r"^\d+'[dD]([0-9_]+)$", s)
        if m:
            return int(m.group(1).replace("_", ""), 10)

        s_clean = s.replace("_", "")
        if s_clean.startswith("0x") or s_clean.startswith("0X"):
            return int(s_clean, 16)
        if s_clean.startswith("0b") or s_clean.startswith("0B"):
            return int(s_clean, 2)

        try:
            if radix == "hex":
                return int(s_clean, 16)
            elif radix == "bin":
                return int(s_clean, 2)
            else:
                return int(s_clean, 10)
        except ValueError:
            return None

    @classmethod
    def load(cls, config: ReferenceConfig) -> List[ParsedVector]:
        path = config.file
        if not path.exists():
            raise FileNotFoundError(f"Reference file not found: {path}")

        vectors: List[ParsedVector] = []
        fmt = config.format.lower()
        radix = config.radix.lower()

        if fmt == "csv":
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for line_idx, row in enumerate(reader, start=2):
                    inputs = {}
                    outputs = {}
                    # Map input ports
                    for ref_key, dut_port in config.input_mapping.items():
                        raw_val = row.get(ref_key, row.get(dut_port))
                        val = cls._parse_val(raw_val, radix)
                        if val is not None:
                            inputs[dut_port] = val
                    # Map output ports
                    for ref_key, dut_port in config.output_mapping.items():
                        raw_val = row.get(ref_key, row.get(dut_port))
                        val = cls._parse_val(raw_val, radix)
                        if val is not None:
                            outputs[dut_port] = val

                    if inputs or outputs:
                        vectors.append(ParsedVector(
                            index=len(vectors),
                            inputs=inputs,
                            expected_outputs=outputs,
                            source_line=line_idx,
                            raw_row=dict(row)
                        ))

        elif fmt == "json":
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            items = raw_data if isinstance(raw_data, list) else raw_data.get("vectors", [])
            for idx, item in enumerate(items, start=1):
                inputs = {}
                outputs = {}
                for ref_key, dut_port in config.input_mapping.items():
                    val = cls._parse_val(item.get(ref_key, item.get(dut_port)), radix)
                    if val is not None:
                        inputs[dut_port] = val
                for ref_key, dut_port in config.output_mapping.items():
                    val = cls._parse_val(item.get(ref_key, item.get(dut_port)), radix)
                    if val is not None:
                        outputs[dut_port] = val
                vectors.append(ParsedVector(
                    index=len(vectors),
                    inputs=inputs,
                    expected_outputs=outputs,
                    source_line=idx,
                    raw_row=item
                ))

        elif fmt in ("mem", "hex", "table"):
            lines = path.read_text(encoding="utf-8").splitlines()
            line_num = 0
            for line in lines:
                line_num += 1
                stripped = line.split("//")[0].strip()
                if not stripped or stripped.startswith("@"):
                    continue
                tokens = stripped.split()
                # If fields correspond to input mapping then output mapping
                in_keys = list(config.input_mapping.values())
                out_keys = list(config.output_mapping.values())
                all_keys = in_keys + out_keys
                if len(tokens) >= len(all_keys):
                    inputs = {}
                    outputs = {}
                    for i, k in enumerate(in_keys):
                        inputs[k] = cls._parse_val(tokens[i], radix)
                    for j, k in enumerate(out_keys):
                        outputs[k] = cls._parse_val(tokens[len(in_keys) + j], radix)
                    vectors.append(ParsedVector(
                        index=len(vectors),
                        inputs=inputs,
                        expected_outputs=outputs,
                        source_line=line_num,
                        raw_row=tokens
                    ))

        return vectors


class ReferenceHarnessGenerator:
    """
    Generates an isolated, automated Verilog/SystemVerilog test harness
    driven by staged structured vectors.
    """

    @classmethod
    def generate(
        cls,
        dut: ModuleInfo,
        config: ReferenceConfig,
        vectors: List[ParsedVector],
        build_dir: Path
    ) -> Tuple[Path, Path]:
        """
        Creates:
        1. vector_inputs.mem containing input words
        2. golden_harness.sv driving inputs and dumping actual outputs to actual_outputs.csv
        """
        build_dir.mkdir(parents=True, exist_ok=True)
        harness_file = build_dir / f"harness_{dut.name}.sv"
        vector_mem_file = build_dir / "dut_inputs.mem"

        # 1. Determine input ports ordering and total width
        input_ports = [dut.ports[p] for p in dut.port_order if p in config.input_mapping.values()]
        output_ports = [dut.ports[p] for p in dut.port_order if p in config.output_mapping.values()]

        # Write vector inputs to .mem
        mem_lines = []
        for vec in vectors:
            # Concatenate input fields
            concat_val = 0
            cur_shift = 0
            # Reverse order so first port is at MSB
            for p in reversed(input_ports):
                val = vec.inputs.get(p.name, 0)
                mask = (1 << p.width) - 1 if p.width > 0 else 1
                concat_val |= (val & mask) << cur_shift
                cur_shift += p.width if p.width > 0 else 1
            hex_digits = max(1, (cur_shift + 3) // 4)
            mem_lines.append(f"{concat_val:0{hex_digits}x}")

        vector_mem_file.write_text("\n".join(mem_lines) + "\n", encoding="utf-8")

        total_input_bits = sum(p.width if p.width > 0 else 1 for p in input_ports)
        vec_count = len(vectors)

        # 2. Generate Harness Verilog
        timing = config.timing
        is_seq = (timing.mode == "sequential")
        clk_sig = timing.clock_signal or "clk"
        rst_sig = timing.reset_signal or "rst_n"

        lines = [
            "`timescale 1ns/1ps",
            f"module harness_{dut.name};",
            f"    localparam TOTAL_VECTORS = {vec_count};",
            f"    localparam INPUT_BITS = {total_input_bits};",
            "",
            "    // DUT Signals",
        ]

        # Declare input wires/regs
        for p in input_ports:
            rng = p.range_str if p.range_str else (f"[{p.width-1}:0]" if p.width > 1 else "")
            lines.append(f"    reg {rng} {p.name};")

        # Declare output wires
        for p in output_ports:
            rng = p.range_str if p.range_str else (f"[{p.width-1}:0]" if p.width > 1 else "")
            lines.append(f"    wire {rng} {p.name};")

        if is_seq:
            lines.append(f"    reg {clk_sig};")
            lines.append(f"    reg {rst_sig};")
            lines.append("")
            lines.append(f"    always #{timing.clock_period_ns / 2} {clk_sig} = ~{clk_sig};")

        lines.append("")
        lines.append(f"    reg [INPUT_BITS-1:0] test_vectors [0:TOTAL_VECTORS-1];")
        lines.append("    integer idx;")
        lines.append("    integer outfile;")
        lines.append("")
        lines.append(f"    // Instantiate DUT: {dut.name}")
        lines.append(f"    {dut.name} uut (")
        conn_strs = []
        for p in dut.port_order:
            if p in dut.ports:
                conn_strs.append(f"        .{p}({p})")
        lines.append(",\n".join(conn_strs))
        lines.append("    );")
        lines.append("")
        lines.append("    initial begin")
        lines.append('        $readmemh("dut_inputs.mem", test_vectors);')
        lines.append('        outfile = $fopen("actual_outputs.csv", "w");')
        lines.append(f'        $fdisplay(outfile, "idx,{",".join(p.name for p in output_ports)}");')

        if is_seq:
            lines.append(f"        {clk_sig} = 0;")
            rst_active = timing.reset_active_level
            lines.append(f"        {rst_sig} = {rst_active};")
            lines.append(f"        repeat ({timing.reset_duration_cycles}) @(posedge {clk_sig});")
            lines.append(f"        {rst_sig} = {1 - rst_active};")
            lines.append(f"        @(posedge {clk_sig});")

        lines.append("        for (idx = 0; idx < TOTAL_VECTORS; idx = idx + 1) begin")

        # Unpack input bits into respective ports
        bit_offset = total_input_bits
        for p in input_ports:
            w = p.width if p.width > 0 else 1
            bit_offset -= w
            if w == 1:
                lines.append(f"            {p.name} = test_vectors[idx][{bit_offset}];")
            else:
                lines.append(f"            {p.name} = test_vectors[idx][{bit_offset + w - 1}:{bit_offset}];")

        if not is_seq:
            lines.append(f"            #{timing.settling_time_ns};")
        else:
            lines.append(f"            repeat ({timing.latency_cycles}) @(posedge {clk_sig});")
            lines.append("            #1;")

        # Format output write
        fmt_spec = "%0d," + ",".join("%h" for _ in output_ports)
        out_vars = ", ".join(p.name for p in output_ports)
        lines.append(f'            $fdisplay(outfile, "{fmt_spec}", idx, {out_vars});')
        lines.append("        end")
        lines.append("        $fclose(outfile);")
        lines.append('        $display("[HARNESS] Verification complete: %0d vectors executed.", TOTAL_VECTORS);')
        lines.append("        $finish;")
        lines.append("    end")
        lines.append("endmodule")
        lines.append("")

        harness_file.write_text("\n".join(lines), encoding="utf-8")
        return harness_file, vector_mem_file


class ReferenceScoreboard:
    """Compares simulated actual outputs against expected reference vectors in Python."""

    @classmethod
    def audit(
        cls,
        actual_csv_path: Path,
        expected_vectors: List[ParsedVector],
        config: ReferenceConfig
    ) -> Tuple[str, int, int, int, List[VectorMismatch], str]:
        if not actual_csv_path.exists():
            return (
                STATUS_INCOMPLETE,
                0,
                len(expected_vectors),
                len(expected_vectors),
                [],
                "Simulation failed to produce actual_outputs.csv."
            )

        actual_rows: List[Dict[str, str]] = []
        with open(actual_csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for r in reader:
                actual_rows.append(r)

        if not actual_rows:
            return (
                STATUS_INCOMPLETE,
                0,
                len(expected_vectors),
                len(expected_vectors),
                [],
                "actual_outputs.csv is empty."
            )

        passed = 0
        failed = 0
        has_xz = False
        mismatches: List[VectorMismatch] = []

        total_to_check = min(len(actual_rows), len(expected_vectors))

        for idx in range(total_to_check):
            act_row = actual_rows[idx]
            exp_vec = expected_vectors[idx]

            row_failed = False
            act_dict: Dict[str, Any] = {}
            exp_dict: Dict[str, Any] = {}

            for dut_port in config.output_mapping.values():
                act_str = act_row.get(dut_port, "").strip().lower()
                act_dict[dut_port] = act_str

                exp_val = exp_vec.expected_outputs.get(dut_port)
                exp_dict[dut_port] = f"{exp_val:x}" if exp_val is not None else "none"

                # Check X/Z
                if "x" in act_str or "z" in act_str:
                    has_xz = True
                    row_failed = True
                    continue

                try:
                    act_val = int(act_str, 16)
                    if exp_val is not None and act_val != exp_val:
                        row_failed = True
                except ValueError:
                    row_failed = True

            if row_failed:
                failed += 1
                if len(mismatches) < 100:  # Cap recorded mismatches
                    mismatches.append(VectorMismatch(
                        index=idx,
                        inputs=exp_vec.inputs,
                        actual_outputs=act_dict,
                        expected_outputs=exp_dict,
                        raw_message=f"Line {exp_vec.source_line}: mismatch on input {exp_vec.inputs}. Exp: {exp_dict}, Got: {act_dict}"
                    ))
            else:
                passed += 1

        # Check vector count mismatch
        if len(actual_rows) < len(expected_vectors):
            return (
                STATUS_INCOMPLETE,
                passed,
                len(expected_vectors),
                len(expected_vectors) - passed,
                mismatches,
                f"Simulation terminated early: expected {len(expected_vectors)} vectors, but only {len(actual_rows)} simulated."
            )

        if has_xz:
            diag = f"Detected unknown/high-impedance 'x' or 'z' on {failed} output vectors."
            return (STATUS_INVALID_RESULTS, passed, len(expected_vectors), failed, mismatches, diag)

        if failed > 0:
            diag = f"Functional reference mismatch on {failed}/{len(expected_vectors)} vectors. First mismatch: {mismatches[0].raw_message}"
            return (STATUS_FUNCTIONAL_FAIL, passed, len(expected_vectors), failed, mismatches, diag)

        diag = f"All {passed}/{len(expected_vectors)} vectors verified against golden reference '{config.file.name}'."
        return (STATUS_PASS_REFERENCE_VERIFIED, passed, len(expected_vectors), 0, [], diag)


class ReferenceVerificationEngine:
    """
    Executes Path B (Independent Golden Reference Verification).
    Generates a dedicated test harness, drives reference vectors, and performs independent scoreboard checking.
    """

    def __init__(self, adapter: Optional[BaseSimulatorAdapter] = None):
        self.adapter = adapter or QuestaSimulatorAdapter()
        if not self.adapter.is_available():
            self.adapter = IcarusSimulatorAdapter()
        self.executor = IsolatedSimulatorExecutor(adapter=self.adapter)

    def verify(
        self,
        dut: ModuleInfo,
        config: ReferenceConfig,
        dependencies: List[Path],
        build_dir: Path,
        timeout_seconds: float = 30.0
    ) -> TestResult:
        start_ts = time.perf_counter()
        build_dir.mkdir(parents=True, exist_ok=True)

        # 1. Load Reference Vectors
        try:
            vectors = ReferenceDataLoader.load(config)
        except Exception as exc:
            return TestResult(
                plan_id=f"ref_harness__{dut.name}",
                dut_name=dut.name,
                tb_name=f"ref_harness_{config.file.stem}",
                status=STATUS_FUNCTIONAL_FAIL,
                diagnostic_summary=f"Failed to load reference file '{config.file}': {exc}",
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_FAIL
            )

        if not vectors:
            return TestResult(
                plan_id=f"ref_harness__{dut.name}",
                dut_name=dut.name,
                tb_name=f"ref_harness_{config.file.stem}",
                status=STATUS_INCOMPLETE,
                diagnostic_summary=f"Reference file '{config.file}' contains 0 usable test vectors.",
                execution_status=EXEC_SUCCESS,
                functional_status=VERIF_INCOMPLETE
            )

        # 2. Synthesize Verification Harness
        harness_file, mem_file = ReferenceHarnessGenerator.generate(dut, config, vectors, build_dir)

        # 3. Create Verification Plan for Harness
        required_sources = list(dependencies)
        if dut.file_path.resolve() not in [p.resolve() for p in required_sources]:
            required_sources.append(dut.file_path.resolve())
        required_sources.append(harness_file.resolve())

        plan = VerificationPlan(
            plan_id=f"ref_harness__{dut.name}",
            dut_name=dut.name,
            dut_module=dut.name,
            dut_file=dut.file_path,
            tb_name=f"harness_{dut.name}",
            tb_module=f"harness_{dut.name}",
            tb_file=harness_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Synthesized Reference Verification Harness",
                match_type="REFERENCE_HARNESS",
                expected_module_name=dut.name,
                actual_module_name=dut.name
            ),
            required_sources=required_sources,
            data_files=[mem_file],
            build_dir=build_dir,
            timeout_seconds=timeout_seconds,
            verification_path="PATH_B"
        )

        # 4. Execute Simulation
        exec_res = self.executor.execute(plan)

        if exec_res.is_license_error:
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_LICENSE_ERROR,
                diagnostic_summary=f"License Error during reference harness execution: {exec_res.compile_stderr or exec_res.sim_stderr}",
                execution_status=EXEC_LICENSE_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=round(time.perf_counter() - start_ts, 4)
            )

        if exec_res.compile_returncode != 0:
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_COMPILE_ERROR,
                diagnostic_summary=f"Harness compilation failed: {exec_res.compile_stderr or exec_res.compile_stdout}",
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=round(time.perf_counter() - start_ts, 4)
            )

        if exec_res.timed_out:
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_TIMEOUT,
                diagnostic_summary="Harness simulation timed out.",
                execution_status=EXEC_TIMEOUT,
                functional_status=VERIF_INVALID,
                elapsed_seconds=round(time.perf_counter() - start_ts, 4)
            )

        if exec_res.sim_returncode != 0:
            return TestResult(
                plan_id=plan.plan_id,
                dut_name=dut.name,
                tb_name=plan.tb_name,
                status=STATUS_SIMULATION_ERROR,
                diagnostic_summary=f"Harness simulation runtime error: {exec_res.sim_stderr}",
                execution_status=EXEC_SIMULATION_ERROR,
                functional_status=VERIF_INVALID,
                elapsed_seconds=round(time.perf_counter() - start_ts, 4)
            )

        # 5. Scoreboard Audit
        actual_csv = build_dir / "actual_outputs.csv"
        status, passed, total, failed, mismatches, diag = ReferenceScoreboard.audit(
            actual_csv, vectors, config
        )

        func_status = VERIF_PASS if status == STATUS_PASS_REFERENCE_VERIFIED else VERIF_FAIL
        audit_status = AUDIT_MATCH if status == STATUS_PASS_REFERENCE_VERIFIED else AUDIT_MISMATCH

        return TestResult(
            plan_id=plan.plan_id,
            dut_name=dut.name,
            tb_name=plan.tb_name,
            status=status,
            passed_vectors=passed,
            total_vectors=total,
            failed_vectors=failed,
            elapsed_seconds=round(time.perf_counter() - start_ts, 4),
            diagnostic_summary=diag,
            failing_vectors=[m.__dict__ for m in mismatches[:20]],
            confidence="CONFIRMED",
            execution_status=EXEC_SUCCESS,
            functional_status=func_status,
            audit_status=audit_status,
            simulator_name=self.adapter.name
        )
