from __future__ import annotations
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Any
from models import ModuleInfo, StaticAnalysisReport

class StaticRTLAnalyzer:
    """
    Static RTL Analyzer providing pre-simulation linting and formal structural analysis.
    Evaluates Yosys integration when installed, and provides a built-in AST/semantic
    static analysis engine for environments where external EDA synthesis tools are unavailable.
    """

    def __init__(self, all_modules: Optional[Dict[str, ModuleInfo]] = None):
        self.all_modules = all_modules or {}
        self.yosys_bin = shutil.which("yosys")

    @property
    def has_yosys(self) -> bool:
        return self.yosys_bin is not None

    def analyze(self, target_module: ModuleInfo, dependencies: Optional[List[Path]] = None) -> StaticAnalysisReport:
        """
        Runs static RTL analysis on target_module and returns a structured StaticAnalysisReport.
        """
        if self.has_yosys:
            return self._analyze_with_yosys(target_module, dependencies or [])
        else:
            return self._analyze_with_builtin(target_module)

    def _analyze_with_yosys(self, target_module: ModuleInfo, dependencies: List[Path]) -> StaticAnalysisReport:
        report = StaticAnalysisReport(
            module_name=target_module.name,
            tool_used=f"Yosys ({self.yosys_bin})",
            passed=True
        )

        all_sources = list(dependencies)
        if target_module.file_path.resolve() not in [p.resolve() for p in all_sources]:
            all_sources.append(target_module.file_path)

        sources_str = " ".join(f'"{s.resolve()}"' for s in all_sources if s.exists())
        cmd = f'read_verilog -sv {sources_str}; hierarchy -check -top {target_module.name}; proc; check'

        try:
            proc = subprocess.run(
                [self.yosys_bin, "-p", cmd],
                capture_output=True,
                text=True,
                timeout=10.0,
                encoding="utf-8",
                errors="replace"
            )
            stdout = proc.stdout
            stderr = proc.stderr

            for line in stdout.splitlines():
                line_str = line.strip()
                if "Warning: Latch inferred" in line_str:
                    report.inferred_latches.append(line_str)
                    report.warnings.append(line_str)
                elif "Warning: Multiple drivers" in line_str:
                    report.multi_driven_nets.append(line_str)
                    report.warnings.append(line_str)
                elif "Warning:" in line_str:
                    report.warnings.append(line_str)
                elif "ERROR:" in line_str:
                    report.errors.append(line_str)
                    report.passed = False

            if proc.returncode != 0:
                report.passed = False
                if stderr.strip():
                    report.errors.append(stderr.strip())

        except Exception as exc:
            report.warnings.append(f"Yosys execution exception: {str(exc)}; falling back to built-in analyzer.")
            return self._analyze_with_builtin(target_module)

        return report

    def _analyze_with_builtin(self, mod: ModuleInfo) -> StaticAnalysisReport:
        report = StaticAnalysisReport(
            module_name=mod.name,
            tool_used="Built-in AST Static Lint Engine (Yosys offline)",
            passed=True
        )

        try:
            raw_text = mod.file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return report

        # Extract module text specifically
        m_match = re.search(rf"\bmodule\s+{re.escape(mod.name)}\b.*?\bendmodule\b", raw_text, flags=re.DOTALL)
        mod_text = m_match.group(0) if m_match else raw_text

        # Strip comments
        clean_text = re.sub(r'//.*', '', mod_text)
        clean_text = re.sub(r'/\*.*?\*/', '', clean_text, flags=re.DOTALL)

        # 1. Check for Inferred Latches in Combinational Blocks
        comb_blocks = re.findall(r'\balways\s*@\s*(?:\*\s*|\(\s*\*\s*\)|\(\s*[^)]+\))(.*?)\bend\b', clean_text, flags=re.DOTALL)
        for block in comb_blocks:
            # Skip clocked blocks
            if re.search(r'\b(posedge|negedge)\b', block):
                continue

            # Check if block contains 'if' statements without 'else'
            if_matches = re.finditer(r'\bif\s*\([^)]+\)\s*(?:begin\s*)?([^;]+;)(?!\s*else)', block)
            for if_m in if_matches:
                stmt = if_m.group(1).strip()
                assign_target = re.match(r'([a-zA-Z_][a-zA-Z0-9_$]*)\s*(?:<=|=)', stmt)
                if assign_target:
                    var_name = assign_target.group(1)
                    latch_msg = f"Potential latch inferred for signal '{var_name}' (incomplete conditional assignment in combinational always block)"
                    if latch_msg not in report.inferred_latches:
                        report.inferred_latches.append(latch_msg)
                        report.warnings.append(latch_msg)

            # Check case statements without default
            case_blocks = re.findall(r'\bcase\s*\([^)]+\)(.*?)\bendcase\b', block, flags=re.DOTALL)
            for cb in case_blocks:
                if "default" not in cb:
                    latch_msg = "Incomplete case statement without 'default' branch in combinational block (inferred latch risk)"
                    if latch_msg not in report.inferred_latches:
                        report.inferred_latches.append(latch_msg)
                        report.warnings.append(latch_msg)

        # 2. Check for Multi-driven Nets
        assigned_targets: Dict[str, List[str]] = {}

        # Continuous assignments: assign x = ...
        for assign_m in re.finditer(r'\bassign\s+([a-zA-Z_][a-zA-Z0-9_$]*)', clean_text):
            tgt = assign_m.group(1)
            assigned_targets.setdefault(tgt, []).append("continuous assignment")

        # Procedural blocks
        for idx, ab_match in enumerate(re.finditer(r'\balways\b(?:.*?\bend\b|.*?;\s*)', clean_text, flags=re.DOTALL)):
            ab = ab_match.group(0)
            targets_in_block = set(re.findall(r'([a-zA-Z_][a-zA-Z0-9_$]*)\s*(?:<=|=)', ab))
            for tgt in targets_in_block:
                if tgt in mod.ports or tgt in mod.internal_signals:
                    assigned_targets.setdefault(tgt, []).append(f"always block #{idx+1}")

        for tgt, sources in assigned_targets.items():
            if len(sources) > 1:
                warn = f"Multiple driver sources detected for net '{tgt}': {', '.join(sources)}"
                report.multi_driven_nets.append(warn)
                report.warnings.append(warn)

        # 3. Check for Sensitivity List Anomalies
        # Mixed edge and level signals
        for sens_m in re.finditer(r'\balways\s*@\s*\(([^)]+)\)', clean_text):
            sens_expr = sens_m.group(1)
            tokens = [t.strip() for t in sens_expr.split("or") if t.strip()]
            has_edge = any("posedge" in t or "negedge" in t for t in tokens)
            has_level = any("posedge" not in t and "negedge" not in t and t != "*" for t in tokens)
            if has_edge and has_level:
                warn = f"Anomalous sensitivity list mixing edge-triggered and level-sensitive signals: @({sens_expr})"
                report.warnings.append(warn)

        # 4. Check Port Width Mismatches on Submodule Instantiations
        for inst in mod.instantiations:
            sub_type = inst.module_type
            if sub_type in self.all_modules:
                sub_mod = self.all_modules[sub_type]
                for p_name, wire_name in inst.port_connections.items():
                    if p_name in sub_mod.ports:
                        sub_p_width = sub_mod.ports[p_name].width
                        # Look up wire width
                        wire_width = None
                        if wire_name in mod.ports:
                            wire_width = mod.ports[wire_name].width
                        elif wire_name in mod.internal_signals:
                            wire_width = mod.internal_signals[wire_name].width

                        if wire_width is not None and sub_p_width > 0 and wire_width > 0:
                            if wire_width != sub_p_width:
                                warn = (f"Instantiation '{inst.instance_name}' ({sub_type}): port '{p_name}' "
                                        f"width {sub_p_width} does not match connected wire '{wire_name}' width {wire_width}")
                                report.warnings.append(warn)

        # 5. Check for Floating Inputs or Unassigned Outputs
        for p in mod.ports.values():
            if p.direction == "input":
                # Check if input is never mentioned in module body
                if not re.search(rf"\b{re.escape(p.name)}\b", clean_text[clean_text.find(";"):]) if ";" in clean_text else False:
                    report.unused_ports.append(f"Input port '{p.name}' is declared but never read in module body")
            elif p.direction == "output":
                # Check if output is never assigned
                if p.name not in assigned_targets:
                    report.unused_ports.append(f"Output port '{p.name}' is declared but never assigned in module body")

        return report
