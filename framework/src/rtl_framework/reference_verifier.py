from __future__ import annotations
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .models import (
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
from .executor import BaseSimulatorAdapter, IsolatedSimulatorExecutor, QuestaSimulatorAdapter, IcarusSimulatorAdapter


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

    rejected_reasons: List[str] = []

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
            try:
                return int(m.group(1).replace("_", ""), 16)
            except ValueError:
                return None
        m = re.match(r"^\d+'[bB]([01_]+)$", s)
        if m:
            try:
                return int(m.group(1).replace("_", ""), 2)
            except ValueError:
                return None
        m = re.match(r"^\d+'[dD]([0-9_]+)$", s)
        if m:
            try:
                val = int(m.group(1).replace("_", ""), 10)
                return val if val >= 0 else None
            except ValueError:
                return None

        s_clean = s.replace("_", "")
        # Reject negative numbers: hardware port values are unsigned bitvectors
        if s_clean.startswith("-"):
            return None
        if s_clean.startswith("0x") or s_clean.startswith("0X"):
            try:
                return int(s_clean, 16)
            except ValueError:
                return None
        if s_clean.startswith("0b") or s_clean.startswith("0B"):
            try:
                return int(s_clean, 2)
            except ValueError:
                return None

        try:
            if radix == "hex":
                val = int(s_clean, 16)
            elif radix == "bin":
                val = int(s_clean, 2)
            else:
                val = int(s_clean, 10)
            return val if val >= 0 else None
        except ValueError:
            return None

    @staticmethod
    def _validate_port_val(
        port_name: str,
        val: int,
        is_output: bool,
        line_ref: str,
        dut: Optional[ModuleInfo]
    ) -> None:
        if val < 0:
            kind = "output" if is_output else "input"
            raise ValueError(f"{line_ref}: Negative value {val} is invalid for {kind} port '{port_name}'.")
        if dut and port_name in dut.ports:
            port = dut.ports[port_name]
            width = port.width if port.width > 0 else 1
            max_val = (1 << width) - 1
            if val > max_val:
                kind = "output" if is_output else "input"
                raise ValueError(
                    f"{line_ref}: Value {val} (0x{val:x}) for {kind} port '{port_name}' "
                    f"exceeds configured port width of {width} bits (maximum allowed value is {max_val} / 0x{max_val:x})."
                )

    @classmethod
    def load(
        cls,
        config: ReferenceConfig,
        dut: Optional[ModuleInfo] = None,
        strict: bool = False
    ) -> List[ParsedVector]:
        path = config.file
        if not path.exists():
            raise FileNotFoundError(f"Reference file not found: {path}")

        cls.rejected_reasons = []

        if not config.input_mapping:
            raise ValueError("ReferenceConfig must define non-empty 'input_mapping' for reference verification.")
        if not config.output_mapping:
            raise ValueError("ReferenceConfig must define non-empty 'output_mapping' for reference verification.")

        vectors: List[ParsedVector] = []
        fmt = config.format.lower()
        radix = config.radix.lower()

        def _reject_or_raise(err_msg: str):
            cls.rejected_reasons.append(err_msg)
            if strict:
                raise ValueError(err_msg)

        if fmt == "csv":
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    raise ValueError(f"Reference CSV file '{path}' is empty or missing a header row.")

                # Ensure configured mapping columns exist in CSV header
                for ref_key, dut_port in config.input_mapping.items():
                    if ref_key not in reader.fieldnames and dut_port not in reader.fieldnames:
                        raise ValueError(
                            f"Reference CSV header is missing configured input column '{ref_key}' (DUT port '{dut_port}'). "
                            f"Available columns: {reader.fieldnames}"
                        )
                for ref_key, dut_port in config.output_mapping.items():
                    if ref_key not in reader.fieldnames and dut_port not in reader.fieldnames:
                        raise ValueError(
                            f"Reference CSV header is missing configured output column '{ref_key}' (DUT port '{dut_port}'). "
                            f"Available columns: {reader.fieldnames}"
                        )

                for line_idx, row in enumerate(reader, start=2):
                    inputs = {}
                    outputs = {}
                    line_ref = f"Line {line_idx}"
                    vector_valid = True

                    # Map input ports - strictly reject missing or invalid fields
                    for ref_key, dut_port in config.input_mapping.items():
                        raw_val = row.get(ref_key) if ref_key in row else row.get(dut_port)
                        if raw_val is None or str(raw_val).strip() == "":
                            _reject_or_raise(
                                f"{line_ref}: Missing configured input field '{ref_key}' (DUT port '{dut_port}') in reference vector."
                            )
                            vector_valid = False
                            break
                        val = cls._parse_val(raw_val, radix)
                        if val is None:
                            _reject_or_raise(
                                f"{line_ref}: Invalid or non-numeric value for input '{dut_port}': {raw_val!r}."
                            )
                            vector_valid = False
                            break
                        try:
                            cls._validate_port_val(dut_port, val, False, line_ref, dut)
                        except ValueError as ve:
                            _reject_or_raise(str(ve))
                            vector_valid = False
                            break
                        inputs[dut_port] = val

                    if not vector_valid:
                        continue

                    # Map output ports - strictly reject missing or invalid fields
                    for ref_key, dut_port in config.output_mapping.items():
                        raw_val = row.get(ref_key) if ref_key in row else row.get(dut_port)
                        if raw_val is None or str(raw_val).strip() == "":
                            _reject_or_raise(
                                f"{line_ref}: Missing configured expected-output field '{ref_key}' (DUT port '{dut_port}') in reference vector."
                            )
                            vector_valid = False
                            break
                        val = cls._parse_val(raw_val, radix)
                        if val is None:
                            _reject_or_raise(
                                f"{line_ref}: Invalid or non-numeric value for expected output '{dut_port}': {raw_val!r}."
                            )
                            vector_valid = False
                            break
                        try:
                            cls._validate_port_val(dut_port, val, True, line_ref, dut)
                        except ValueError as ve:
                            _reject_or_raise(str(ve))
                            vector_valid = False
                            break
                        outputs[dut_port] = val

                    if not vector_valid:
                        continue

                    vectors.append(ParsedVector(
                        index=len(vectors),
                        inputs=inputs,
                        expected_outputs=outputs,
                        source_line=line_idx,
                        raw_row=dict(row)
                    ))

        elif fmt == "json":
            raw_data = json.loads(path.read_text(encoding="utf-8-sig"))
            items = raw_data if isinstance(raw_data, list) else raw_data.get("vectors", [])
            if not items:
                raise ValueError(f"Reference JSON file '{path}' contains no vector elements.")

            for idx, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    raise ValueError(f"JSON vector entry {idx} is not an object/dictionary: {item!r}")
                inputs = {}
                outputs = {}
                line_ref = f"Vector entry {idx}"
                vector_valid = True

                for ref_key, dut_port in config.input_mapping.items():
                    raw_val = item.get(ref_key) if ref_key in item else item.get(dut_port)
                    if raw_val is None or str(raw_val).strip() == "":
                        _reject_or_raise(
                            f"{line_ref}: Missing configured input field '{ref_key}' (DUT port '{dut_port}')."
                        )
                        vector_valid = False
                        break
                    val = cls._parse_val(raw_val, radix)
                    if val is None:
                        _reject_or_raise(
                            f"{line_ref}: Invalid or non-numeric value for input '{dut_port}': {raw_val!r}."
                        )
                        vector_valid = False
                        break
                    try:
                        cls._validate_port_val(dut_port, val, False, line_ref, dut)
                    except ValueError as ve:
                        _reject_or_raise(str(ve))
                        vector_valid = False
                        break
                    inputs[dut_port] = val

                if not vector_valid:
                    continue

                for ref_key, dut_port in config.output_mapping.items():
                    raw_val = item.get(ref_key) if ref_key in item else item.get(dut_port)
                    if raw_val is None or str(raw_val).strip() == "":
                        _reject_or_raise(
                            f"{line_ref}: Missing configured expected-output field '{ref_key}' (DUT port '{dut_port}')."
                        )
                        vector_valid = False
                        break
                    val = cls._parse_val(raw_val, radix)
                    if val is None:
                        _reject_or_raise(
                            f"{line_ref}: Invalid or non-numeric value for expected output '{dut_port}': {raw_val!r}."
                        )
                        vector_valid = False
                        break
                    try:
                        cls._validate_port_val(dut_port, val, True, line_ref, dut)
                    except ValueError as ve:
                        _reject_or_raise(str(ve))
                        vector_valid = False
                        break
                    outputs[dut_port] = val

                if not vector_valid:
                    continue

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
            in_keys = list(config.input_mapping.values())
            out_keys = list(config.output_mapping.values())
            all_keys = in_keys + out_keys
            for line in lines:
                line_num += 1
                stripped = line.split("//")[0].strip()
                if not stripped or stripped.startswith("@"):
                    continue
                tokens = stripped.split()
                line_ref = f"Line {line_num}"
                if len(tokens) < len(all_keys):
                    _reject_or_raise(
                        f"{line_ref}: Insufficient tokens ({len(tokens)}) for configured inputs "
                        f"({len(in_keys)}) and outputs ({len(out_keys)})."
                    )
                    continue
                inputs = {}
                outputs = {}
                vector_valid = True
                for i, k in enumerate(in_keys):
                    val = cls._parse_val(tokens[i], radix)
                    if val is None:
                        _reject_or_raise(f"{line_ref}: Invalid numeric value for input '{k}': {tokens[i]!r}.")
                        vector_valid = False
                        break
                    try:
                        cls._validate_port_val(k, val, False, line_ref, dut)
                    except ValueError as ve:
                        _reject_or_raise(str(ve))
                        vector_valid = False
                        break
                    inputs[k] = val
                if not vector_valid:
                    continue

                for j, k in enumerate(out_keys):
                    tok = tokens[len(in_keys) + j]
                    val = cls._parse_val(tok, radix)
                    if val is None:
                        _reject_or_raise(f"{line_ref}: Invalid numeric value for expected output '{k}': {tok!r}.")
                        vector_valid = False
                        break
                    try:
                        cls._validate_port_val(k, val, True, line_ref, dut)
                    except ValueError as ve:
                        _reject_or_raise(str(ve))
                        vector_valid = False
                        break
                    outputs[k] = val

                if not vector_valid:
                    continue

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
                if p.name not in vec.inputs:
                    raise ValueError(
                        f"Vector index {vec.index} (source line {vec.source_line}) is missing configured input port '{p.name}'. "
                        "Missing inputs must not be silently replaced with zero."
                    )
                val = vec.inputs[p.name]
                if val is None:
                    raise ValueError(
                        f"Vector index {vec.index} (source line {vec.source_line}) has None for configured input port '{p.name}'."
                    )
                mask = (1 << p.width) - 1 if p.width > 0 else 1
                if val < 0 or val > mask:
                    raise ValueError(
                        f"Vector index {vec.index} value {val} for input port '{p.name}' exceeds port width {p.width}."
                    )
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
            if not reader.fieldnames:
                return (
                    STATUS_INVALID_RESULTS,
                    0,
                    len(expected_vectors),
                    len(expected_vectors),
                    [],
                    "actual_outputs.csv is empty or missing a header row."
                )
            for r in reader:
                actual_rows.append(r)

        if not actual_rows:
            return (
                STATUS_INCOMPLETE,
                0,
                len(expected_vectors),
                len(expected_vectors),
                [],
                "actual_outputs.csv contains no data rows."
            )

        # 1. Require number of captured output rows to strictly equal expected vector count
        if len(actual_rows) != len(expected_vectors):
            if len(actual_rows) < len(expected_vectors):
                diag = (
                    f"Simulation terminated early: expected {len(expected_vectors)} vectors, "
                    f"but only {len(actual_rows)} output rows were captured."
                )
                return (
                    STATUS_INCOMPLETE,
                    0,
                    len(expected_vectors),
                    len(expected_vectors),
                    [],
                    diag
                )
            else:
                diag = (
                    f"Captured output row count ({len(actual_rows)}) exceeds "
                    f"expected vector count ({len(expected_vectors)})."
                )
                return (
                    STATUS_INVALID_RESULTS,
                    0,
                    len(expected_vectors),
                    len(actual_rows),
                    [],
                    diag
                )

        # 2. Reject missing output columns
        required_cols = list(config.output_mapping.values())
        first_row = actual_rows[0]
        missing_cols = [col for col in required_cols if col not in first_row]
        if missing_cols:
            diag = f"Captured actual_outputs.csv is missing configured output column(s): {missing_cols}"
            return (
                STATUS_INVALID_RESULTS,
                0,
                len(expected_vectors),
                len(expected_vectors),
                [],
                diag
            )

        # 3. Reject malformed, duplicate or out-of-order vector indices where indices are present
        index_col = "idx" if "idx" in first_row else ("index" if "index" in first_row else None)
        if index_col:
            seen_indices = set()
            for r_idx, r in enumerate(actual_rows):
                val_str = r.get(index_col)
                if val_str is None or str(val_str).strip() == "":
                    diag = f"Malformed vector index at output row {r_idx}: index field is empty or missing."
                    return (STATUS_INVALID_RESULTS, 0, len(expected_vectors), len(expected_vectors), [], diag)
                try:
                    num_idx = int(str(val_str).strip())
                except ValueError:
                    diag = f"Malformed vector index at output row {r_idx}: cannot parse {val_str!r} as integer."
                    return (STATUS_INVALID_RESULTS, 0, len(expected_vectors), len(expected_vectors), [], diag)

                if num_idx in seen_indices:
                    diag = f"Duplicate vector index {num_idx} detected at output row {r_idx}."
                    return (STATUS_INVALID_RESULTS, 0, len(expected_vectors), len(expected_vectors), [], diag)
                seen_indices.add(num_idx)

                if num_idx != r_idx:
                    diag = f"Out-of-order vector index at output row {r_idx}: expected index {r_idx}, got {num_idx}."
                    return (STATUS_INVALID_RESULTS, 0, len(expected_vectors), len(expected_vectors), [], diag)

        # 4. Compare every configured expected output against actual output
        passed = 0
        failed = 0
        has_xz = False
        mismatches: List[VectorMismatch] = []

        for idx in range(len(expected_vectors)):
            act_row = actual_rows[idx]
            exp_vec = expected_vectors[idx]

            row_failed = False
            act_dict: Dict[str, Any] = {}
            exp_dict: Dict[str, Any] = {}
            ports_matched = 0

            for dut_port in required_cols:
                # Validate expected output presence
                if dut_port not in exp_vec.expected_outputs or exp_vec.expected_outputs[dut_port] is None:
                    row_failed = True
                    exp_dict[dut_port] = "<MISSING_EXPECTED>"
                    act_dict[dut_port] = act_row.get(dut_port, "").strip().lower()
                    continue

                exp_val = exp_vec.expected_outputs[dut_port]
                exp_dict[dut_port] = f"{exp_val:x}"

                # Validate actual output presence
                if dut_port not in act_row or act_row[dut_port] is None or str(act_row[dut_port]).strip() == "":
                    row_failed = True
                    act_dict[dut_port] = "<MISSING_ACTUAL>"
                    continue

                act_str = str(act_row[dut_port]).strip().lower()
                act_dict[dut_port] = act_str

                # Check X/Z
                if "x" in act_str or "z" in act_str:
                    has_xz = True
                    row_failed = True
                    continue

                try:
                    act_val = int(act_str, 16)
                    if act_val != exp_val:
                        row_failed = True
                    else:
                        ports_matched += 1
                except ValueError:
                    row_failed = True

            # Never classify a partially unchecked vector as passed
            if ports_matched != len(required_cols):
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

        if has_xz:
            diag = f"Detected unknown/high-impedance 'x' or 'z' on {failed} output vectors."
            return (STATUS_INVALID_RESULTS, passed, len(expected_vectors), failed, mismatches, diag)

        if failed > 0:
            diag = f"Functional reference mismatch on {failed}/{len(expected_vectors)} vectors. First mismatch: {mismatches[0].raw_message}"
            return (STATUS_FUNCTIONAL_FAIL, passed, len(expected_vectors), failed, mismatches, diag)

        if passed != len(expected_vectors):
            diag = f"Only {passed}/{len(expected_vectors)} vectors fully verified."
            return (STATUS_INCOMPLETE, passed, len(expected_vectors), len(expected_vectors) - passed, mismatches, diag)

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

        # 1. Load Reference Vectors with port validation against DUT
        try:
            vectors = ReferenceDataLoader.load(config, dut=dut)
        except Exception as exc:
            return TestResult(
                plan_id=f"ref_harness__{dut.name}",
                dut_name=dut.name,
                tb_name=f"ref_harness_{config.file.stem}",
                status=STATUS_INVALID_RESULTS,
                diagnostic_summary=f"Failed to load or validate reference file '{config.file}': {exc}",
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_INVALID
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
        try:
            harness_file, mem_file = ReferenceHarnessGenerator.generate(dut, config, vectors, build_dir)
        except Exception as exc:
            return TestResult(
                plan_id=f"ref_harness__{dut.name}",
                dut_name=dut.name,
                tb_name=f"ref_harness_{config.file.stem}",
                status=STATUS_INVALID_RESULTS,
                diagnostic_summary=f"Failed to synthesize reference verification harness: {exc}",
                execution_status=EXEC_COMPILE_ERROR,
                functional_status=VERIF_INVALID
            )

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
