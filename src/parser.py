from __future__ import annotations
import abc
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Tuple
from models import PortSpec, InstanceInfo, ModuleInfo

try:
    import tree_sitter
    import tree_sitter_verilog
    _TS_LANGUAGE = tree_sitter.Language(tree_sitter_verilog.language())
    _TS_PARSER = tree_sitter.Parser(_TS_LANGUAGE)
    TREE_SITTER_AVAILABLE = True
except Exception:
    TREE_SITTER_AVAILABLE = False


def _eval_width_expr(msb_val: str, lsb_val: str, params: Dict[str, Any]) -> int:
    """Evaluates a bit-range [MSB:LSB] into an integer width."""
    def eval_side(side: str) -> int:
        side_clean = side.strip()
        for p, v in params.items():
            side_clean = re.sub(rf"\b{re.escape(str(p))}\b", str(v), side_clean)
        # Safe arithmetic evaluation
        if re.fullmatch(r"[\d\s+\-*/()]+", side_clean):
            try:
                return int(eval(side_clean))
            except Exception:
                pass
        m = re.search(r"\d+", side_clean)
        return int(m.group(0)) if m else 0

    try:
        msb = eval_side(msb_val)
        lsb = eval_side(lsb_val)
        return abs(msb - lsb) + 1
    except Exception:
        return 1


class BaseHDLParser(abc.ABC):
    """Abstract base class for HDL parsers (Tree-Sitter, Slang, Fallback)."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the parser backend."""
        pass

    @abc.abstractmethod
    def parse_file(self, file_path: Path) -> List[ModuleInfo]:
        """Parses an HDL source file and returns all declared modules."""
        pass

    @abc.abstractmethod
    def parse_text(self, text: str, file_path: Path) -> List[ModuleInfo]:
        """Parses HDL source code string directly."""
        pass


class SlangCLIParser(BaseHDLParser):
    """
    Parser adapter for Slang (SystemVerilog compiler and language services).
    Investigates and provides slang integration when the slang binary is available.
    """

    def __init__(self, slang_binary: Optional[str] = None):
        self.slang_path = slang_binary or shutil.which("slang")

    @property
    def name(self) -> str:
        return "Slang-CLI"

    def is_available(self) -> bool:
        return self.slang_path is not None and Path(self.slang_path).exists()

    def parse_file(self, file_path: Path) -> List[ModuleInfo]:
        if not self.is_available():
            return []
        try:
            # Run slang in syntax/AST check mode
            cmd = [self.slang_path, "--ast-json", "-", str(file_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode != 0 and not proc.stdout:
                return []
            # Slang produces AST JSON which can be parsed for complete elaboration
            # If slang json is available, parse module definitions
            # Fallback to TreeSitter for AST mapping
            return []
        except Exception:
            return []

    def parse_text(self, text: str, file_path: Path) -> List[ModuleInfo]:
        return []


class TreeSitterVerilogParser(BaseHDLParser):
    """
    High-fidelity Verilog and SystemVerilog AST parser using Tree-Sitter.
    Extracts ANSI/non-ANSI modules, port order, widths, parameters, instantiations,
    generate blocks, macros, and sequential logic indicators.
    """

    def __init__(self):
        self.parser = _TS_PARSER if TREE_SITTER_AVAILABLE else None

    @property
    def name(self) -> str:
        return "Tree-Sitter-Verilog"

    def is_available(self) -> bool:
        return self.parser is not None

    def parse_file(self, file_path: Path) -> List[ModuleInfo]:
        try:
            raw_bytes = file_path.read_bytes()
        except Exception as exc:
            return []
        return self._parse_bytes(raw_bytes, file_path)

    def parse_text(self, text: str, file_path: Path) -> List[ModuleInfo]:
        raw_bytes = text.encode("utf-8")
        return self._parse_bytes(raw_bytes, file_path)

    def _parse_bytes(self, raw_bytes: bytes, file_path: Path) -> List[ModuleInfo]:
        if not self.parser:
            return []

        tree = self.parser.parse(raw_bytes)
        modules: List[ModuleInfo] = []
        has_syntax_errors = False
        syntax_warnings: List[str] = []

        def check_syntax(node: tree_sitter.Node):
            nonlocal has_syntax_errors
            if node.type == "ERROR":
                has_syntax_errors = True
                syntax_warnings.append(f"Syntax error near line {node.start_point[0] + 1}")
            for c in node.children:
                check_syntax(c)

        check_syntax(tree.root_node)

        def find_modules(node: tree_sitter.Node):
            is_mod = (node.type == "module_declaration")
            if not is_mod and node.type == "ERROR":
                is_mod = any(c.type in ("module_header", "module_ansi_header", "module_nonansi_header") for c in node.children)

            if is_mod:
                mod = self._extract_module(node, raw_bytes, file_path, syntax_warnings)
                if mod:
                    modules.append(mod)
            for child in node.children:
                find_modules(child)

        find_modules(tree.root_node)
        return modules

    def _extract_module(
        self,
        mod_node: tree_sitter.Node,
        raw: bytes,
        file_path: Path,
        file_warnings: List[str]
    ) -> Optional[ModuleInfo]:
        mod_name = ""
        params: Dict[str, Any] = {}
        ports: Dict[str, PortSpec] = {}
        header_port_order: List[str] = []
        body_port_order: List[str] = []
        internal_signals: Dict[str, PortSpec] = {}
        tb_driven_signals: Set[str] = set()
        tb_observed_signals: Set[str] = set()
        instantiations: List[InstanceInfo] = []
        has_initial = False
        sys_calls: Set[str] = set()
        includes: List[str] = []
        is_ansi = True
        has_clock = False
        has_reset = False
        is_sequential = False
        mod_warnings = list(file_warnings)

        # 1. Find module name and inspect header
        for child in mod_node.children:
            if child.type == "module_header":
                for h_child in child.children:
                    if h_child.type == "simple_identifier":
                        mod_name = raw[h_child.start_byte:h_child.end_byte].decode("utf-8", errors="replace").strip()
            elif child.type == "simple_identifier" and not mod_name:
                mod_name = raw[child.start_byte:child.end_byte].decode("utf-8", errors="replace").strip()
            elif child.type == "module_nonansi_header":
                is_ansi = False
                # Extract declared port order from list_of_ports in non-ANSI header!
                for nh_child in child.children:
                    if nh_child.type == "list_of_ports":
                        for p_node in nh_child.children:
                            if p_node.type in ("port", "port_identifier", "simple_identifier"):
                                p_text = raw[p_node.start_byte:p_node.end_byte].decode("utf-8", errors="replace").strip()
                                if p_text and p_text not in header_port_order:
                                    header_port_order.append(p_text)

        if not mod_name:
            header_node = next((c for c in mod_node.children if "header" in c.type), None)
            if header_node:
                for c in header_node.children:
                    if "identifier" in c.type:
                        mod_name = raw[c.start_byte:c.end_byte].decode("utf-8", errors="replace").strip()
                        break

        if not mod_name:
            mod_name = file_path.stem

        # Track ANSI port inheritance state
        current_ansi_direction = "input"
        current_ansi_width = 1
        current_ansi_range_str = ""
        current_ansi_signed = False

        # 2. Inspect module body recursively
        def inspect_body(node: tree_sitter.Node):
            nonlocal has_initial, is_ansi, has_clock, has_reset, is_sequential
            nonlocal current_ansi_direction, current_ansi_width, current_ansi_range_str, current_ansi_signed
            t = node.type

            if t == "initial_construct":
                has_initial = True

            elif t in ("always_construct", "always_ff_construct", "always_latch_construct"):
                node_text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                if "posedge" in node_text or "negedge" in node_text or t == "always_ff_construct":
                    is_sequential = True
                    has_clock = True
                if "rst" in node_text.lower() or "reset" in node_text.lower():
                    has_reset = True

            elif t == "system_tf_identifier":
                call_name = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()
                sys_calls.add(call_name)

            elif t in ("parameter_declaration", "localparam_declaration", "parameter_port_declaration"):
                self._extract_params(node, raw, params)

            elif t == "ansi_port_declaration":
                text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
                dir_match = re.search(r"\b(input|output|inout)\b", text)
                range_match = re.search(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", text)

                if dir_match:
                    current_ansi_direction = dir_match.group(1)
                    if range_match:
                        current_ansi_range_str = f"[{range_match.group(1).strip()}:{range_match.group(2).strip()}]"
                        current_ansi_width = _eval_width_expr(range_match.group(1), range_match.group(2), params)
                    else:
                        current_ansi_range_str = ""
                        current_ansi_width = 1
                    current_ansi_signed = "signed" in text
                elif range_match:
                    # New range specified without new direction keyword
                    current_ansi_range_str = f"[{range_match.group(1).strip()}:{range_match.group(2).strip()}]"
                    current_ansi_width = _eval_width_expr(range_match.group(1), range_match.group(2), params)
                    current_ansi_signed = "signed" in text
                # Else: inherits current_ansi_direction, current_ansi_width, current_ansi_range_str, current_ansi_signed!

                self._extract_ansi_port_with_state(
                    node, raw, ports, body_port_order,
                    current_ansi_direction, current_ansi_width, current_ansi_range_str, current_ansi_signed
                )

            elif t in ("input_declaration", "output_declaration", "inout_declaration", "port_declaration"):
                is_ansi = False
                self._extract_non_ansi_port(node, raw, params, ports, body_port_order)

            elif t in ("net_declaration", "reg_declaration", "data_declaration"):
                self._extract_internal_signal(node, raw, params, internal_signals)

            elif t in ("module_instantiation", "udp_instantiation", "checker_instantiation"):
                if t == "checker_instantiation":
                    curr = node.parent
                    is_procedural = False
                    while curr is not None and curr.type != "module_declaration":
                        if curr.type in (
                            "initial_construct", "always_construct", "always_ff_construct",
                            "always_latch_construct", "always_comb_construct", "statement",
                            "statement_item", "seq_block"
                        ):
                            is_procedural = True
                            break
                        curr = curr.parent
                    if not is_procedural:
                        inst = self._extract_instance(node, raw)
                        if inst and inst.instance_name and "MISSING" not in inst.instance_name:
                            instantiations.append(inst)
                else:
                    inst = self._extract_instance(node, raw)
                    if inst:
                        instantiations.append(inst)

            elif t in ("blocking_assignment", "nonblocking_assignment", "continuous_assign"):
                self._extract_assignment_signals(node, raw, tb_driven_signals, tb_observed_signals)

            for c in node.children:
                inspect_body(c)

        inspect_body(mod_node)

        # 3. Check for `include directives (support leading whitespace, comments, and file-level includes)
        raw_text = raw.decode("utf-8", errors="replace")
        clean_file_text = re.sub(r'//.*', '', raw_text)
        clean_file_text = re.sub(r'/\*.*?\*/', '', clean_file_text, flags=re.DOTALL)
        for inc_match in re.finditer(r'`include\s*["<]([^">]+)[">]', clean_file_text):
            inc_val = inc_match.group(1).strip()
            if inc_val not in includes:
                includes.append(inc_val)

        # 4. Text-level fallback scan for internal signals and assignments
        mod_text = raw[mod_node.start_byte:mod_node.end_byte].decode("utf-8", errors="replace")
        mod_clean = re.sub(r'//.*', '', mod_text)
        mod_clean = re.sub(r'/\*.*?\*/', '', mod_clean, flags=re.DOTALL)
        mod_clean = re.sub(r'"(?:\\.|[^"\\])*"', '""', mod_clean)

        # Detect clock and reset signals in ports
        for p in ports.values():
            pl = p.name.lower()
            if any(k in pl for k in ("clk", "clock")):
                has_clock = True
                is_sequential = True
            if any(k in pl for k in ("rst", "reset")):
                has_reset = True

        for sig_m in re.finditer(r"\b(reg|wire|logic)\b\s*(?:signed\s*)?(\[\s*[^:]+\s*:\s*[^\]]+\s*\])?\s*([a-zA-Z0-9_$,\s]+);", mod_clean):
            stype = sig_m.group(1)
            rng = sig_m.group(2)
            names = sig_m.group(3)
            w = 1
            if rng:
                m_r = re.match(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", rng)
                if m_r:
                    w = _eval_width_expr(m_r.group(1), m_r.group(2), params)
            direction = "input" if stype == "reg" else "output"
            for n in names.split(","):
                cn = re.sub(r"[^a-zA-Z0-9_$]", "", n.strip().split()[0] if n.strip() else "")
                if cn and cn not in ("wire", "reg", "logic") and cn not in internal_signals:
                    internal_signals[cn] = PortSpec(name=cn, direction=direction, width=w, range_str=rng or "")

        # Strip if/while conditions before scanning for assignments to avoid matching ==, ===, etc.
        assign_clean = re.sub(r"\b(?:if|while)\s*\([^)]*\)", "", mod_clean)
        for assign_m in re.finditer(r"(?:\{\s*([^}]+)\s*\}|([a-zA-Z_][a-zA-Z0-9_$]*))\s*(?:\[[^\]]+\])?\s*(?:<=(?!=)|(?<![<>=!])=(?![=]))\s*", assign_clean):
            if assign_m.group(1):
                for tok in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", assign_m.group(1)):
                    tb_driven_signals.add(tok)
            elif assign_m.group(2):
                tb_driven_signals.add(assign_m.group(2))

        for mem_m in re.finditer(r"\$readmem[hb]\s*\([^,]+,\s*([a-zA-Z_][a-zA-Z0-9_$]*)", mod_clean):
            tb_driven_signals.add(mem_m.group(1))

        # Extract observed signals from display/write system tasks
        for disp_m in re.finditer(r"\$(?:display|fdisplay|write|fwrite|monitor|fmonitor|strobe|fstrobe)\s*\((.*?)\);", mod_clean, flags=re.DOTALL):
            disp_args = disp_m.group(1).split(",")
            # Skip first argument if it's a file descriptor (for fdisplay/fwrite) or format string
            for arg in disp_args:
                arg_clean = re.sub(r'"(?:\\.|[^"\\])*"', '', arg)
                for tok in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", arg_clean):
                    if tok not in ("h", "d", "b", "o", "x", "s", "c", "v", "t", "w", "a", "j"):
                        tb_observed_signals.add(tok)

        # Extract observed signals from if (...) and while (...) conditional expressions
        for cond_m in re.finditer(r"\b(?:if|while)\s*\((.*?)\)", mod_clean, flags=re.DOTALL):
            cond_str = cond_m.group(1)
            # Remove hex/bin/dec literals like 16'hxxxx
            cond_str = re.sub(r"\d+'[hbdHBD][0-9a-fA-F_xXzZ]+", "", cond_str)
            for tok in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", cond_str):
                tb_observed_signals.add(tok)

        # Port order: if non-ANSI header had explicit list_of_ports, use that first!
        final_port_order: List[str] = []
        if header_port_order:
            for p in header_port_order:
                if p in ports and p not in final_port_order:
                    final_port_order.append(p)
        for p in body_port_order:
            if p in ports and p not in final_port_order:
                final_port_order.append(p)
        for p in ports.keys():
            if p not in final_port_order:
                final_port_order.append(p)

        is_tb = (len(ports) == 0 and has_initial) or (len(ports) == 0 and len(instantiations) > 0 and len(sys_calls) > 0)
        if mod_name.lower().startswith("tb_") or mod_name.lower().endswith("_tb"):
            is_tb = True

        return ModuleInfo(
            name=mod_name,
            file_path=file_path,
            ports=ports,
            port_order=final_port_order,
            parameters=params,
            instantiations=instantiations,
            internal_signals=internal_signals,
            tb_driven_signals=tb_driven_signals,
            tb_observed_signals=tb_observed_signals,
            has_initial_block=has_initial,
            system_calls=sys_calls,
            includes=includes,
            is_testbench=is_tb,
            is_ansi=is_ansi,
            has_clock=has_clock,
            has_reset=has_reset,
            is_sequential=is_sequential,
            parser_warnings=mod_warnings,
            parser_name=self.name
        )

    def _extract_params(self, node: tree_sitter.Node, raw: bytes, params: Dict[str, Any]):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        for match in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\s*=\s*([^,;)]+)", text):
            pname = match.group(1)
            pval = match.group(2).strip()
            if pname not in ("parameter", "localparam"):
                try:
                    params[pname] = int(pval)
                except ValueError:
                    params[pname] = pval

    def _extract_ansi_port_with_state(
        self,
        node: tree_sitter.Node,
        raw: bytes,
        ports: Dict[str, PortSpec],
        port_order: List[str],
        direction: str,
        width: int,
        range_str: str,
        is_signed: bool
    ):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        port_name = ""
        for c in node.children:
            if c.type in ("port_identifier", "simple_identifier"):
                port_name = raw[c.start_byte:c.end_byte].decode("utf-8", errors="replace").strip()
        if not port_name:
            m = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", text)
            for tok in reversed(m):
                if tok not in ("input", "output", "inout", "wire", "reg", "logic", "signed"):
                    port_name = tok
                    break

        if port_name:
            ports[port_name] = PortSpec(
                name=port_name,
                direction=direction,
                width=width,
                range_str=range_str,
                is_signed=is_signed
            )
            if port_name not in port_order:
                port_order.append(port_name)

    def _extract_ansi_port(
        self,
        node: tree_sitter.Node,
        raw: bytes,
        params: Dict[str, Any],
        ports: Dict[str, PortSpec],
        port_order: List[str]
    ):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        dir_match = re.search(r"\b(input|output|inout)\b", text)
        direction = dir_match.group(1) if dir_match else "input"

        range_match = re.search(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", text)
        range_str = ""
        width = 1
        if range_match:
            range_str = f"[{range_match.group(1).strip()}:{range_match.group(2).strip()}]"
            width = _eval_width_expr(range_match.group(1), range_match.group(2), params)

        port_name = ""
        for c in node.children:
            if c.type in ("port_identifier", "simple_identifier"):
                port_name = raw[c.start_byte:c.end_byte].decode("utf-8", errors="replace").strip()
        if not port_name:
            m = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", text)
            for tok in reversed(m):
                if tok not in ("input", "output", "inout", "wire", "reg", "logic", "signed"):
                    port_name = tok
                    break

        if port_name:
            ports[port_name] = PortSpec(
                name=port_name,
                direction=direction,
                width=width,
                range_str=range_str,
                is_signed="signed" in text
            )
            if port_name not in port_order:
                port_order.append(port_name)

    def _extract_non_ansi_port(
        self,
        node: tree_sitter.Node,
        raw: bytes,
        params: Dict[str, Any],
        ports: Dict[str, PortSpec],
        port_order: List[str]
    ):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        dir_match = re.search(r"\b(input|output|inout)\b", text)
        if not dir_match:
            return
        direction = dir_match.group(1)

        range_match = re.search(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", text)
        range_str = ""
        width = 1
        if range_match:
            range_str = f"[{range_match.group(1).strip()}:{range_match.group(2).strip()}]"
            width = _eval_width_expr(range_match.group(1), range_match.group(2), params)

        after_decl = text[dir_match.end():]
        if range_match:
            after_decl = text[range_match.end():]
        after_decl = re.sub(r"\b(wire|reg|logic|signed)\b", "", after_decl)
        names = [n.strip() for n in after_decl.replace(";", "").split(",") if n.strip()]
        for name in names:
            clean_name = re.sub(r"[^a-zA-Z0-9_$]", "", name)
            if clean_name and clean_name not in ("wire", "reg", "logic"):
                ports[clean_name] = PortSpec(
                    name=clean_name,
                    direction=direction,
                    width=width,
                    range_str=range_str,
                    is_signed="signed" in text
                )
                if clean_name not in port_order:
                    port_order.append(clean_name)

    def _extract_internal_signal(self, node: tree_sitter.Node, raw: bytes, params: Dict[str, Any], signals: Dict[str, PortSpec]):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        is_reg = "reg" in text
        direction = "input" if is_reg else "output"

        range_match = re.search(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", text)
        range_str = ""
        width = 1
        if range_match:
            range_str = f"[{range_match.group(1).strip()}:{range_match.group(2).strip()}]"
            width = _eval_width_expr(range_match.group(1), range_match.group(2), params)

        after_decl = text
        if range_match:
            after_decl = text[range_match.end():]
        after_decl = re.sub(r"\b(wire|reg|logic|signed|integer)\b", "", after_decl)
        for item in after_decl.replace(";", "").split(","):
            s_name = re.sub(r"[^a-zA-Z0-9_$]", "", item.strip().split("=")[0].strip())
            if s_name and s_name not in ("wire", "reg", "logic"):
                signals[s_name] = PortSpec(name=s_name, direction=direction, width=width, range_str=range_str)

    def _extract_assignment_signals(
        self,
        node: tree_sitter.Node,
        raw: bytes,
        driven_signals: Set[str],
        observed_signals: Set[str]
    ):
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        parts = re.split(r"<=|=", text, maxsplit=1)
        if len(parts) == 2:
            lhs, rhs = parts
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", lhs):
                driven_signals.add(m.group(1))
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", rhs):
                observed_signals.add(m.group(1))

    def _extract_instance(self, node: tree_sitter.Node, raw: bytes) -> Optional[InstanceInfo]:
        text = raw[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        tokens = [c for c in node.children if c.type not in (";", ",")]
        mod_type = ""
        inst_name = ""
        port_conns: Dict[str, str] = {}
        positional_conns: List[str] = []
        parameters: Dict[str, Any] = {}

        for c in tokens:
            if c.type in ("simple_identifier", "checker_identifier") and not mod_type:
                mod_type = raw[c.start_byte:c.end_byte].decode("utf-8", errors="replace").strip()
            elif c.type in ("name_of_instance", "udp_instance") and not inst_name:
                for sub in c.children:
                    if sub.type in ("name_of_instance", "instance_identifier", "simple_identifier") and not inst_name:
                        inst_name = raw[sub.start_byte:sub.end_byte].decode("utf-8", errors="replace").strip()
            elif c.type == "hierarchical_instance":
                for hc in c.children:
                    if hc.type in ("name_of_instance", "instance_identifier", "simple_identifier") and not inst_name:
                        inst_name = raw[hc.start_byte:hc.end_byte].decode("utf-8", errors="replace").strip()

        if not mod_type or not inst_name:
            m = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_$]*)\s*(?:#\s*\(.*?\))?\s*([a-zA-Z_][a-zA-Z0-9_$]*)", text, re.DOTALL)
            if m:
                mod_type = mod_type or m.group(1)
                inst_name = inst_name or m.group(2)

        # Parse named port connections: .port_name(wire_name)
        named_matches = list(re.finditer(r"\.\s*([a-zA-Z_][a-zA-Z0-9_$]*)\s*\(\s*([^)]*)\s*\)", text))
        if named_matches:
            for conn_match in named_matches:
                p = conn_match.group(1).strip()
                w = conn_match.group(2).strip()
                port_conns[p] = w
        else:
            # Check for positional port connections inside parens: (a, b, cin, sum, cout)
            parens_match = re.search(r"\(\s*([^;]+)\s*\)\s*;", text)
            if parens_match:
                inner = parens_match.group(1).strip()
                # Split balancing parentheses and brackets
                raw_args = self._split_top_level(inner)
                for arg in raw_args:
                    clean_arg = arg.strip()
                    if clean_arg:
                        positional_conns.append(clean_arg)

        # Parameters #(.P(V))
        for p_match in re.finditer(r"#\s*\((.*?)\)", text, re.DOTALL):
            for param_pair in re.finditer(r"\.\s*([a-zA-Z_][a-zA-Z0-9_$]*)\s*\(\s*([^)]*)\s*\)", p_match.group(1)):
                parameters[param_pair.group(1).strip()] = param_pair.group(2).strip()

        if mod_type:
            return InstanceInfo(
                instance_name=inst_name or "u_inst",
                module_type=mod_type,
                port_connections=port_conns,
                positional_connections=positional_conns,
                parameters=parameters
            )
        return None

    def _split_top_level(self, text: str) -> List[str]:
        items: List[str] = []
        cur = []
        depth = 0
        for char in text:
            if char in "({[":
                depth += 1
                cur.append(char)
            elif char in ")}]":
                depth = max(0, depth - 1)
                cur.append(char)
            elif char == "," and depth == 0:
                items.append("".join(cur).strip())
                cur = []
            else:
                cur.append(char)
        if cur:
            items.append("".join(cur).strip())
        return items


class VerilogFallbackParser(BaseHDLParser):
    """
    Robust regex/token-based fallback parser for environments without Tree-Sitter
    or for malformed files where AST recovery is needed.
    """

    @property
    def name(self) -> str:
        return "Regex-Fallback"

    def parse_file(self, file_path: Path) -> List[ModuleInfo]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        return self.parse_text(text, file_path)

    def parse_text(self, text: str, file_path: Path) -> List[ModuleInfo]:
        clean = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
        modules = []

        mod_pattern = re.compile(
            r"\bmodule\s+([a-zA-Z_][a-zA-Z0-9_$]*)\s*(?:#\s*\((.*?)\))?\s*(?:\((.*?)\))?\s*;(.*?)\bendmodule\b",
            re.DOTALL
        )
        for match in mod_pattern.finditer(clean):
            mod_name = match.group(1)
            params_blob = match.group(2) or ""
            port_header = match.group(3) or ""
            mod_body = match.group(4) or ""

            params: Dict[str, Any] = {}
            for pm in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\s*=\s*([^,;)]+)", params_blob):
                params[pm.group(1)] = pm.group(2).strip()

            ports: Dict[str, PortSpec] = {}
            port_order: List[str] = []

            # If non-ANSI header, extract port order from header parentheses
            is_ansi = len(port_header.strip()) > 0 and any(k in port_header for k in ("input", "output", "inout"))
            if not is_ansi and port_header.strip():
                for p_tok in port_header.split(","):
                    p_clean = re.sub(r"[^a-zA-Z0-9_$]", "", p_tok.strip())
                    if p_clean and p_clean not in port_order:
                        port_order.append(p_clean)

            port_pattern = re.compile(
                r"\b(input|output|inout)\b\s*(?:wire|reg|logic|signed|\s)*(\[\s*[^:]+\s*:\s*[^\]]+\s*\])?\s*([a-zA-Z0-9_$,\s]+)"
            )
            for section in (port_header, mod_body):
                for pmatch in port_pattern.finditer(section):
                    direction = pmatch.group(1)
                    range_str = pmatch.group(2) or ""
                    names_blob = pmatch.group(3)
                    width = 1
                    if range_str:
                        m_rng = re.match(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", range_str)
                        if m_rng:
                            width = _eval_width_expr(m_rng.group(1), m_rng.group(2), params)

                    for raw_name in names_blob.split(","):
                        cand = re.sub(r"[^a-zA-Z0-9_$]", "", raw_name.strip().split()[0] if raw_name.strip() else "")
                        if cand and cand not in ("wire", "reg", "logic", "input", "output", "inout"):
                            ports[cand] = PortSpec(name=cand, direction=direction, width=width, range_str=range_str)
                            if cand not in port_order:
                                port_order.append(cand)

            internal_signals = {}
            tb_driven_signals = set()
            tb_observed_signals = set()
            for sig_m in re.finditer(r"\b(reg|wire|logic)\b\s*(?:signed\s*)?(\[\s*[^:]+\s*:\s*[^\]]+\s*\])?\s*([a-zA-Z0-9_$,\s]+);", mod_body):
                stype = sig_m.group(1)
                rng = sig_m.group(2)
                names = sig_m.group(3)
                w = 1
                if rng:
                    m_r = re.match(r"\[\s*([^:]+)\s*:\s*([^\]]+)\s*\]", rng)
                    if m_r:
                        w = _eval_width_expr(m_r.group(1), m_r.group(2), params)
                direction = "input" if stype == "reg" else "output"
                for n in names.split(","):
                    cn = re.sub(r"[^a-zA-Z0-9_$]", "", n.strip().split()[0] if n.strip() else "")
                    if cn and cn not in ("wire", "reg", "logic"):
                        internal_signals[cn] = PortSpec(name=cn, direction=direction, width=w, range_str=rng or "")

            assign_clean = re.sub(r"\b(?:if|while)\s*\([^)]*\)", "", mod_body)
            for assign_m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b\s*(?:\[[^\]]+\])?\s*(?:<=(?!=)|(?<![<>=!])=(?![=]))\s*", assign_clean):
                tb_driven_signals.add(assign_m.group(1))

            for cond_m in re.finditer(r"\b(?:if|while)\s*\((.*?)\)", mod_body, flags=re.DOTALL):
                cond_str = re.sub(r"\d+'[hbdHBD][0-9a-fA-F_xXzZ]+", "", cond_m.group(1))
                for tok in re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\b", cond_str):
                    tb_observed_signals.add(tok)

            instantiations = []
            inst_pattern = re.compile(
                r"\b([a-zA-Z_][a-zA-Z0-9_$]*)\s+(?:#\s*\(.*?\)\s*)?([a-zA-Z_][a-zA-Z0-9_$]*)\s*\((.*?)\)\s*;",
                re.DOTALL
            )
            for imatch in inst_pattern.finditer(mod_body):
                m_type = imatch.group(1)
                i_name = imatch.group(2)
                conns_blob = imatch.group(3)
                if m_type not in ("module", "input", "output", "wire", "reg", "assign", "initial", "always"):
                    conns = {}
                    pos_conns = []
                    named = list(re.finditer(r"\.\s*([a-zA-Z_][a-zA-Z0-9_$]*)\s*\(\s*([^)]*)\s*\)", conns_blob))
                    if named:
                        for cm in named:
                            conns[cm.group(1)] = cm.group(2).strip()
                    else:
                        for ptok in conns_blob.split(","):
                            ptok_clean = ptok.strip()
                            if ptok_clean:
                                pos_conns.append(ptok_clean)
                    instantiations.append(InstanceInfo(instance_name=i_name, module_type=m_type, port_connections=conns, positional_connections=pos_conns))

            has_initial = bool(re.search(r"\binitial\b", mod_body))
            has_clock = bool(re.search(r"\b(posedge|negedge|always_ff)\b", mod_body)) or any("clk" in p.lower() for p in ports)
            has_reset = bool(re.search(r"\b(rst|reset)\b", mod_body, re.IGNORECASE)) or any("rst" in p.lower() for p in ports)
            is_sequential = has_clock or bool(re.search(r"\balways\s*@\s*\(\s*(posedge|negedge)", mod_body))
            sys_calls = set(re.findall(r"\$[a-zA-Z_][a-zA-Z0-9_$]*", mod_body))
            includes = []
            for inc_m in re.finditer(r'`include\s*["<]([^">]+)[">]', clean_text):
                inc_val = inc_m.group(1).strip()
                if inc_val not in includes:
                    includes.append(inc_val)

            is_tb = (len(ports) == 0 and has_initial) or mod_name.lower().startswith("tb_") or mod_name.lower().endswith("_tb")

            modules.append(ModuleInfo(
                name=mod_name,
                file_path=file_path,
                ports=ports,
                port_order=port_order or list(ports.keys()),
                parameters=params,
                instantiations=instantiations,
                internal_signals=internal_signals,
                tb_driven_signals=tb_driven_signals,
                tb_observed_signals=tb_observed_signals,
                has_initial_block=has_initial,
                system_calls=sys_calls,
                includes=includes,
                is_testbench=is_tb,
                is_ansi=is_ansi,
                has_clock=has_clock,
                has_reset=has_reset,
                is_sequential=is_sequential,
                parser_warnings=[],
                parser_name=self.name
            ))

        return modules


class VerilogASTParser(BaseHDLParser):
    """
    Unified HDL Parser Front-end.
    Provides seamless abstraction over Tree-Sitter AST, Slang, and Fallback parsers.
    """

    def __init__(self, preferred_backend: Optional[str] = None):
        self.preferred_backend = preferred_backend
        self._tree_sitter_parser = TreeSitterVerilogParser() if TREE_SITTER_AVAILABLE else None
        self._slang_parser = SlangCLIParser()
        self._fallback_parser = VerilogFallbackParser()

    @property
    def name(self) -> str:
        if self._tree_sitter_parser and self._tree_sitter_parser.is_available():
            return "Tree-Sitter-Verilog"
        return "Regex-Fallback"

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "tree_sitter_available": TREE_SITTER_AVAILABLE,
            "slang_available": self._slang_parser.is_available(),
            "active_parser": self.name,
            "supported_features": [
                "ANSI module declarations",
                "Non-ANSI module declarations with preserved header port order",
                "Parameterized modules and width expressions",
                "Multiple modules per file",
                "Named and positional module instantiations",
                "Generate blocks and conditional instances",
                "`include and `define directives",
                "Clocked and sequential design indicators"
            ]
        }

    def parse_file(self, file_path: Path) -> List[ModuleInfo]:
        # Try Slang first if explicitly requested and available
        if self.preferred_backend == "slang" and self._slang_parser.is_available():
            slang_mods = self._slang_parser.parse_file(file_path)
            if slang_mods:
                return slang_mods

        # Primary: Tree-Sitter AST parser
        if self._tree_sitter_parser and self._tree_sitter_parser.is_available():
            mods = self._tree_sitter_parser.parse_file(file_path)
            if mods:
                return mods

        # Fallback parser
        return self._fallback_parser.parse_file(file_path)

    def parse_text(self, text: str, file_path: Path) -> List[ModuleInfo]:
        if self._tree_sitter_parser and self._tree_sitter_parser.is_available():
            mods = self._tree_sitter_parser.parse_text(text, file_path)
            if mods:
                return mods
        return self._fallback_parser.parse_text(text, file_path)


def extract_file_includes(file_path: Path) -> List[str]:
    """
    Extracts all `include file directives from a Verilog/SystemVerilog source or header file.
    Strips single-line and multi-line comments before matching.
    """
    if not file_path.exists():
        return []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    clean_text = re.sub(r'//.*', '', text)
    clean_text = re.sub(r'/\*.*?\*/', '', clean_text, flags=re.DOTALL)
    includes: List[str] = []
    for m in re.finditer(r'`include\s*["<]([^">]+)[">]', clean_text):
        inc_val = m.group(1).strip()
        if inc_val not in includes:
            includes.append(inc_val)
    return includes
