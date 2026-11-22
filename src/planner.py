from __future__ import annotations
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from models import VerificationPlan, CompatibilityEvidence
from matcher import DUTTestbenchMatch
from dependency_resolver import DependencyResolver
from wrapper_generator import generate_dut_wrapper

class VerificationPlanner:
    """Constructs explicit, auditable verification execution plans for compatible DUT-testbench pairs."""

    def __init__(
        self,
        build_root: Path,
        all_modules: dict,
        data_files: Dict[str, Path],
        include_dirs: Optional[List[Path]] = None,
        timeout_seconds: float = 5.0,
        iverilog_flags: Optional[List[str]] = None,
        explicit_ref_mappings: Optional[Dict[str, Any]] = None
    ):
        self.build_root = build_root.resolve()
        self.all_modules = all_modules
        self.data_files = data_files
        self.include_dirs = [d.resolve() for d in (include_dirs or []) if d.exists()]
        self.timeout_seconds = timeout_seconds
        self.iverilog_flags = iverilog_flags or ["-g2012", "-Wall"]
        self.explicit_ref_mappings = explicit_ref_mappings or {}
        self.dep_resolver = DependencyResolver(all_modules)

    def extract_testbench_reference_files(self, tb_file: Path) -> Tuple[List[Path], List[str]]:
        """
        Extracts reference files with strict priority:
        1. Explicit configuration / manifest mappings.
        2. Statically identified file references in HDL:
           - $readmemh / $readmemb
           - $fopen
           - $value$plusargs
           - Macros (`define) and parameters
        Returns (resolved_paths, missing_filenames).
        """
        resolved: List[Path] = []
        missing: List[str] = []
        tb_text = tb_file.read_text(encoding="utf-8", errors="replace")

        # 1. PRIORITY 1: Explicit configuration / manifest mappings
        tb_name = tb_file.stem
        if tb_name in self.explicit_ref_mappings:
            raw_val = self.explicit_ref_mappings[tb_name]
            cand_list: List[str] = []
            if isinstance(raw_val, list):
                cand_list = raw_val
            elif isinstance(raw_val, dict) and "references" in raw_val:
                cand_list = raw_val["references"]
            elif isinstance(raw_val, str):
                cand_list = [raw_val]

            for mapped_ref in cand_list:
                cand = Path(mapped_ref).resolve()
                if not cand.exists():
                    cand = (self.build_root.parent / mapped_ref).resolve()
                if not cand.exists():
                    cand = (tb_file.parent / mapped_ref).resolve()
                if not cand.exists() and Path(mapped_ref).name in self.data_files:
                    cand = self.data_files[Path(mapped_ref).name].resolve()

                if cand.exists():
                    if cand not in resolved:
                        resolved.append(cand)
                else:
                    if mapped_ref not in missing:
                        missing.append(mapped_ref)

        # 2. PRIORITY 2: Static analysis of HDL text
        # Extract macro definitions: `define REF_NAME "path"
        macro_defs: Dict[str, str] = {}
        for m_def in re.finditer(r'`define\s+([a-zA-Z_][a-zA-Z0-9_$]*)\s+["\']([^"\']+)["\']', tb_text):
            macro_defs[m_def.group(1)] = m_def.group(2)

        # Extract parameters: parameter FILE = "path";
        for p_def in re.finditer(r'\b(?:parameter|localparam)\s+(?:string\s+)?([a-zA-Z_][a-zA-Z0-9_$]*)\s*=\s*["\']([^"\']+)["\']', tb_text):
            macro_defs[p_def.group(1)] = p_def.group(2)

        raw_candidates: List[str] = []

        # $readmemh / $readmemb calls (always input reference files)
        for mem_call in re.finditer(r'\$(?:readmem[hb])\s*\(\s*["\']([^"\']+)["\']', tb_text):
            raw_candidates.append(mem_call.group(1).strip())

        # $fopen calls: only treat as input candidate if mode is "r" or "rb".
        # Files opened with "w", "a", etc. or classic 1-arg $fopen are output log files written by TB!
        for fopen_call in re.finditer(r'\$fopen\s*\(\s*["\']([^"\']+)["\'](?:\s*,\s*["\']([^"\']+)["\'])?', tb_text):
            fname = fopen_call.group(1).strip()
            mode = fopen_call.group(2)
            if mode:
                mode = mode.strip().lower()
                if "w" in mode or "a" in mode:
                    continue  # Output log created by testbench (e.g. fail_log.txt)
            else:
                # 1-argument $fopen is classic Verilog output descriptor
                continue
            raw_candidates.append(fname)

        # Macro or identifier references in $readmem: $readmemh(`MACRO, ...) or $readmemh(PARAM, ...)
        for id_call in re.finditer(r'\$(?:readmem[hb])\s*\(\s*`?([a-zA-Z_][a-zA-Z0-9_$]*)', tb_text):
            ident = id_call.group(1)
            if ident in macro_defs:
                raw_candidates.append(macro_defs[ident].strip())

        # $value$plusargs calls: $value$plusargs("LUT=%s", filename) -> check default or project files
        for pa_call in re.finditer(r'\$value\$plusargs\s*\(\s*["\'][^=]+=%\w+["\']', tb_text):
            # Known plusarg pattern; look for matching data files with common names
            pass

        # Resolve candidate paths
        for raw_path_str in raw_candidates:
            # Check 1: Relative to testbench file directory
            cand1 = (tb_file.parent / raw_path_str).resolve()
            if cand1.exists():
                if cand1 not in resolved:
                    resolved.append(cand1)
                continue

            # Check 2: Relative to project root
            cand2 = (self.build_root.parent / raw_path_str).resolve()
            if cand2.exists():
                if cand2 not in resolved:
                    resolved.append(cand2)
                continue

            # Check 3: By filename in discovered project data files
            fname = Path(raw_path_str).name
            if fname in self.data_files:
                cand3 = self.data_files[fname].resolve()
                if cand3 not in resolved:
                    resolved.append(cand3)
                continue

            # Check 4: Direct absolute path
            cand4 = Path(raw_path_str).resolve()
            if cand4.exists():
                if cand4 not in resolved:
                    resolved.append(cand4)
                continue

            # File could not be resolved
            if raw_path_str not in missing:
                missing.append(raw_path_str)

        return resolved, missing

    def create_plan(self, match: DUTTestbenchMatch) -> VerificationPlan:
        dut = match.dut
        tb = match.testbench
        compat = match.compatibility

        plan_id = f"{dut.file_path.stem}__{tb.name}"
        work_dir = self.build_root / plan_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve submodule dependencies and recursive includes for the DUT
        dut_dep_res = self.dep_resolver.resolve_dependencies(dut)
        deps = list(dut_dep_res.required_source_files)
        include_files = list(dut_dep_res.include_files)

        # 1b. Also resolve dependencies and includes for the testbench (excluding DUT instantiation)
        ignore_dut = {dut.name, compat.expected_module_name}
        tb_dep_res = self.dep_resolver.resolve_dependencies(tb, ignore_modules=ignore_dut)
        for tb_dep in tb_dep_res.required_source_files:
            if tb_dep not in deps and tb_dep != dut.file_path.resolve() and tb_dep != tb.file_path.resolve():
                deps.append(tb_dep)
        for tb_inc in tb_dep_res.include_files:
            if tb_inc not in include_files:
                include_files.append(tb_inc)

        # Collect all directories containing include files to ensure -I flags cover all locations
        all_include_dirs = list(self.include_dirs)
        for inc_f in include_files:
            inc_dir = inc_f.parent.resolve()
            if inc_dir not in all_include_dirs:
                all_include_dirs.append(inc_dir)

        # 2. Check if a wrapper is needed
        wrapper_path: Optional[Path] = None
        if compat.wrapper_needed and compat.matched:
            wrapper_file = work_dir / f"wrapper_{compat.expected_module_name}.v"
            expected_ports = match.expected_ports if match.expected_ports else (
                self.supporting_modules[compat.expected_module_name].ports
                if compat.expected_module_name in self.supporting_modules
                else dut.ports
            )

            wrapper_path = generate_dut_wrapper(
                expected_module_name=compat.expected_module_name,
                actual_module_name=dut.name,
                expected_ports=expected_ports,
                actual_ports=dut.ports,
                port_mapping=compat.port_mapping,
                output_file=wrapper_file,
                parameters=dut.parameters
            )

        # 3. Assemble required sources: dependencies + DUT + wrapper (if any) + TB
        sources: List[Path] = [*deps, dut.file_path.resolve()]
        if wrapper_path:
            sources.append(wrapper_path.resolve())
        sources.append(tb.file_path.resolve())

        # 4. Associate ONLY reference files specifically needed by this testbench
        associated_data, missing_refs = self.extract_testbench_reference_files(tb.file_path)

        # Track unused project reference files
        all_known_data = set(self.data_files.values())
        unused_refs = [str(p.name) for p in all_known_data if p not in associated_data]

        return VerificationPlan(
            plan_id=plan_id,
            dut_name=dut.file_path.stem,
            dut_module=dut.name,
            dut_file=dut.file_path,
            tb_name=tb.name,
            tb_module=tb.name,
            tb_file=tb.file_path,
            compatibility=compat,
            required_sources=sources,
            data_files=associated_data,
            missing_reference_files=missing_refs,
            unused_reference_files=unused_refs,
            include_files=include_files,
            include_dirs=all_include_dirs,
            build_dir=work_dir,
            timeout_seconds=self.timeout_seconds,
            iverilog_flags=self.iverilog_flags,
            wrapper_path=wrapper_path
        )


# Backwards compatibility alias
RegressionPlanner = VerificationPlanner

