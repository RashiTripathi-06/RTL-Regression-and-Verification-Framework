from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from .models import ModuleInfo, PortSpec, CompatibilityEvidence, InstanceInfo
from .dependency_resolver import DependencyResolver

@dataclass
class DUTTestbenchMatch:
    dut: ModuleInfo
    testbench: ModuleInfo
    target_instantiation: str # Expected module name in the testbench
    compatibility: CompatibilityEvidence
    expected_ports: Dict[str, PortSpec] = field(default_factory=dict)
    is_ambiguous: bool = False
    ambiguity_reason: str = ""

class DUTTestbenchMatcher:
    """
    Matches discovered RTL designs with compatible testbenches using a strict priority order:
    1. Explicit user-provided mapping / configuration manifest.
    2. Actual DUT instantiation and named/positional port connections in testbench.
    3. Validated interface, bit-widths, and positional port-order contracts.
    4. Structural and semantic evidence (clock/reset consistency, driven vs observed signals).
    5. Names and file paths only as weak discovery hints.

    Never silently chooses between ambiguous candidates. Identical interfaces on distinct modules
    without explicit mapping or semantic distinction are classified as AMBIGUOUS MATCH.
    """

    def __init__(
        self,
        all_modules: Dict[str, ModuleInfo],
        supporting_modules: Dict[str, ModuleInfo],
        user_mappings: Optional[Dict[str, Any]] = None
    ):
        self.all_modules = all_modules
        self.supporting_modules = supporting_modules
        self.user_mappings = user_mappings or {}
        self.dep_resolver = DependencyResolver(all_modules)

    def extract_tb_dut_requirements(
        self,
        tb: ModuleInfo
    ) -> List[Tuple[str, Dict[str, PortSpec], List[str], str]]:
        """
        Extracts candidate DUT target module names, expected ports, port ordering, and confidence level.
        Returns list of tuples: (expected_module_name, expected_ports_dict, port_order, confidence).
        """
        requirements: List[Tuple[str, Dict[str, PortSpec], List[str], str]] = []

        for inst in tb.instantiations:
            exp_mod_name = inst.module_type
            expected_ports: Dict[str, PortSpec] = {}
            port_order: List[str] = []
            confidence = "CONFIRMED"

            # Check if canonical reference module exists in supporting modules (e.g. golden models/common libs)
            ref_mod = self.supporting_modules.get(exp_mod_name)
            if ref_mod and ref_mod.ports:
                expected_ports = dict(ref_mod.ports)
                port_order = list(ref_mod.port_order)
                confidence = "CONFIRMED"

            # 1. Named port connections: .port_name(signal_name)
            if inst.port_connections:
                for port_name, connected_expr in inst.port_connections.items():
                    clean_sig = connected_expr.split("[")[0].strip()
                    sig_info = tb.internal_signals.get(clean_sig)

                    # Determine width
                    width = sig_info.width if sig_info else -1
                    range_str = sig_info.range_str if sig_info else ""

                    # Determine direction:
                    if clean_sig in tb.tb_driven_signals and clean_sig not in tb.tb_observed_signals:
                        direction = "input" # TB drives it -> DUT input
                    elif clean_sig in tb.tb_observed_signals and clean_sig not in tb.tb_driven_signals:
                        direction = "output" # TB only monitors it -> DUT output
                    elif sig_info and sig_info.direction:
                        direction = sig_info.direction
                    else:
                        direction = "input" if clean_sig in tb.tb_driven_signals else ("output" if clean_sig in tb.tb_observed_signals else "")

                    expected_ports[port_name] = PortSpec(
                        name=port_name,
                        direction=direction,
                        width=width if width > 0 else (ref_mod.ports[port_name].width if (ref_mod and port_name in ref_mod.ports) else 1),
                        range_str=range_str
                    )
                    if port_name not in port_order:
                        port_order.append(port_name)

                confidence = "CONFIRMED"

            # 2. Positional port connections: uut (sig1, sig2, ...)
            elif inst.positional_connections:
                if ref_mod and len(ref_mod.port_order) == len(inst.positional_connections):
                    # We have a confirmed port order from the reference module declaration!
                    port_order = list(ref_mod.port_order)
                    for idx, port_name in enumerate(port_order):
                        clean_sig = inst.positional_connections[idx].split("[")[0].strip()
                        sig_info = tb.internal_signals.get(clean_sig)
                        base_spec = ref_mod.ports.get(port_name)
                        w = base_spec.width if (base_spec and base_spec.width > 0) else (sig_info.width if sig_info else 1)
                        d = base_spec.direction if (base_spec and base_spec.direction) else ("input" if clean_sig in tb.tb_driven_signals else "output")
                        expected_ports[port_name] = PortSpec(name=port_name, direction=d, width=w)
                    confidence = "CONFIRMED"
                else:
                    # Inferred positional ports
                    confidence = "HEURISTIC"
                    for idx, conn_sig in enumerate(inst.positional_connections):
                        clean_sig = conn_sig.split("[")[0].strip()
                        sig_info = tb.internal_signals.get(clean_sig)
                        p_name = f"pin_{idx}"
                        port_order.append(p_name)
                        w = sig_info.width if sig_info else -1
                        d = "input" if clean_sig in tb.tb_driven_signals else ("output" if clean_sig in tb.tb_observed_signals else "")
                        expected_ports[p_name] = PortSpec(name=p_name, direction=d, width=w)

            requirements.append((exp_mod_name, expected_ports, port_order, confidence))

        return requirements

    def evaluate_compatibility(
        self,
        dut: ModuleInfo,
        expected_module_name: str,
        expected_ports: Dict[str, PortSpec],
        tb_port_order: List[str],
        base_confidence: str = "CONFIRMED",
        tb: Optional[ModuleInfo] = None
    ) -> CompatibilityEvidence:
        """
        Evaluates whether candidate dut is compatible with the expected interface contract.
        Purely structural and semantic: completely independent of filenames.
        """
        mismatches: List[str] = []
        port_mapping: Dict[str, str] = {}
        wrapper_needed = False
        is_ambiguous = False
        ambiguity_reason = ""

        if not expected_ports:
            return CompatibilityEvidence(
                matched=False,
                reason="Testbench target interface has no detectable ports.",
                match_type="INCOMPATIBLE",
                confidence="HEURISTIC",
                expected_module_name=expected_module_name,
                actual_module_name=dut.name,
                mismatches=["Empty interface contract."]
            )

        # Semantic check: Clock & Sequential consistency
        tb_has_clock = any("clk" in p.lower() or "clock" in p.lower() for p in expected_ports) or (tb and tb.has_clock)
        dut_has_clock = any("clk" in p.lower() or "clock" in p.lower() for p in dut.ports) or dut.has_clock

        # If testbench has a clock and DUT is purely combinational with completely different interface,
        # or if DUT requires a clock but TB has no clock, record semantic mismatch:
        if dut_has_clock and not tb_has_clock:
            mismatches.append(f"Semantic mismatch: DUT '{dut.name}' requires clock/sequential control, but testbench '{tb.name if tb else expected_module_name}' is purely combinational.")
        elif tb_has_clock and not dut_has_clock and len(expected_ports) != len(dut.ports):
            mismatches.append(f"Semantic mismatch: Testbench '{tb.name if tb else expected_module_name}' drives clock/reset, but DUT '{dut.name}' is combinational.")

        # Case 0: Positional port mapping (when testbench connects ports positionally)
        is_positional = any(p.startswith("pin_") for p in expected_ports.keys())
        if is_positional:
            if len(dut.port_order) != len(expected_ports):
                mismatches.append(f"Positional port count mismatch: expected {len(expected_ports)}, got {len(dut.port_order)}")
            else:
                for idx, exp_pname in enumerate(tb_port_order):
                    exp_pspec = expected_ports[exp_pname]
                    act_pname = dut.port_order[idx]
                    act_pspec = dut.ports[act_pname]

                    # Direction check
                    if exp_pspec.direction and act_pspec.direction and exp_pspec.direction != act_pspec.direction:
                        mismatches.append(f"Port '{act_pname}' (pos {idx}) direction mismatch: expected '{exp_pspec.direction}', found '{act_pspec.direction}'")

                    # Width check
                    if exp_pspec.width > 0 and act_pspec.width > 0 and exp_pspec.width != act_pspec.width:
                        mismatches.append(f"Port '{act_pname}' (pos {idx}) bit-width mismatch: expected {exp_pspec.width}b, found {act_pspec.width}b")

                    port_mapping[exp_pname] = act_pname

                if not mismatches:
                    if dut.name != expected_module_name and base_confidence != "EXPLICIT_CONFIG":
                        is_ambiguous = True
                        ambiguity_reason = (
                            f"Positional mapping between '{dut.name}' and '{expected_module_name}' "
                            f"relies only on port widths/directions without named port or explicit instantiation evidence; mapping is ambiguous."
                        )
                    return CompatibilityEvidence(
                        matched=True,
                        reason="Positional interface match in declaration order.",
                        match_type="EXACT_NAME" if dut.name == expected_module_name else "WRAPPER_COMPATIBLE",
                        confidence="CONFIRMED" if base_confidence == "EXPLICIT_CONFIG" else base_confidence,
                        expected_module_name=expected_module_name,
                        actual_module_name=dut.name,
                        port_mapping=port_mapping,
                        mismatches=[],
                        wrapper_needed=(dut.name != expected_module_name),
                        is_ambiguous=is_ambiguous,
                        ambiguity_reason=ambiguity_reason,
                    )
                else:
                    return CompatibilityEvidence(
                        matched=False,
                        reason=" ; ".join(mismatches),
                        match_type="INCOMPATIBLE",
                        confidence=base_confidence,
                        expected_module_name=expected_module_name,
                        actual_module_name=dut.name,
                        port_mapping=port_mapping,
                        mismatches=mismatches,
                        wrapper_needed=False
                    )

        # Case 1: Same module name (Candidate claims to be the target module)
        if dut.name == expected_module_name:
            for exp_pname, exp_pspec in expected_ports.items():
                if exp_pname not in dut.ports:
                    mismatches.append(f"Missing required port '{exp_pname}' ({exp_pspec.direction} [{exp_pspec.width}b])")
                    continue

                act_pspec = dut.ports[exp_pname]
                # Direction check
                if exp_pspec.direction and act_pspec.direction:
                    if exp_pspec.direction != act_pspec.direction:
                        mismatches.append(
                            f"Port '{exp_pname}' direction mismatch: expected '{exp_pspec.direction}', found '{act_pspec.direction}'"
                        )

                # Width check
                if exp_pspec.width > 0 and act_pspec.width > 0:
                    if exp_pspec.width != act_pspec.width:
                        mismatches.append(
                            f"Port '{exp_pname}' bit-width mismatch: expected {exp_pspec.width}b, found {act_pspec.width}b"
                        )

                port_mapping[exp_pname] = exp_pname

            # Check extra ports on DUT
            extra_ports = set(dut.ports.keys()) - set(expected_ports.keys())
            if extra_ports:
                mismatches.append(f"Unexpected extra ports on DUT: {sorted(extra_ports)}")

            if mismatches:
                return CompatibilityEvidence(
                    matched=False,
                    reason=" ; ".join(mismatches),
                    match_type="INCOMPATIBLE",
                    confidence=base_confidence,
                    expected_module_name=expected_module_name,
                    actual_module_name=dut.name,
                    port_mapping=port_mapping,
                    mismatches=mismatches,
                    wrapper_needed=False
                )

            return CompatibilityEvidence(
                matched=True,
                reason="Direct interface and module name match.",
                match_type="EXACT_NAME",
                confidence=base_confidence,
                expected_module_name=expected_module_name,
                actual_module_name=dut.name,
                port_mapping=port_mapping,
                mismatches=[],
                wrapper_needed=False
            )

        # Case 2: Distinct module name (Wrapper Candidate)
        # Check if DUT port interface matches the expected contract
        common_ports = set(dut.ports.keys()) & set(expected_ports.keys())
        if common_ports == set(expected_ports.keys()) and len(dut.ports) == len(expected_ports):
            # Perfect name match across all ports!
            for exp_pname, exp_pspec in expected_ports.items():
                act_pspec = dut.ports[exp_pname]
                if exp_pspec.direction and act_pspec.direction and exp_pspec.direction != act_pspec.direction:
                    mismatches.append(f"Port '{exp_pname}' direction mismatch: expected '{exp_pspec.direction}', found '{act_pspec.direction}'")
                if exp_pspec.width > 0 and act_pspec.width > 0 and exp_pspec.width != act_pspec.width:
                    mismatches.append(f"Port '{exp_pname}' bit-width mismatch: expected {exp_pspec.width}b, found {act_pspec.width}b")
                port_mapping[exp_pname] = exp_pname

            if mismatches:
                return CompatibilityEvidence(
                    matched=False,
                    reason=" ; ".join(mismatches),
                    match_type="INCOMPATIBLE",
                    confidence=base_confidence,
                    expected_module_name=expected_module_name,
                    actual_module_name=dut.name,
                    port_mapping=port_mapping,
                    mismatches=mismatches,
                    wrapper_needed=False
                )

            return CompatibilityEvidence(
                matched=True,
                reason=f"Compatible interface; wrapper needed to map '{dut.name}' -> '{expected_module_name}'.",
                match_type="WRAPPER_COMPATIBLE",
                confidence=base_confidence,
                expected_module_name=expected_module_name,
                actual_module_name=dut.name,
                port_mapping=port_mapping,
                mismatches=[],
                wrapper_needed=True
            )

        # Case 3: Positional port matching across distinct port names is ONLY allowed if:
        #   - the testbench itself used positional connections (is_positional), OR
        #   - the user explicitly configured this DUT-TB mapping (EXPLICIT_CONFIG).
        # Port width and direction alone are insufficient evidence when the testbench
        # explicitly instantiated a different module with named port connections.
        if (is_positional or base_confidence == "EXPLICIT_CONFIG") and len(dut.ports) == len(expected_ports) and len(tb_port_order) == len(dut.port_order):
            positional_map: Dict[str, str] = {}
            pos_mismatches = []
            for tb_p, dut_p in zip(tb_port_order, dut.port_order):
                exp_s = expected_ports[tb_p]
                act_s = dut.ports[dut_p]
                if exp_s.direction and act_s.direction and exp_s.direction != act_s.direction:
                    pos_mismatches.append(f"Positional port '{dut_p}' direction mismatch: expected '{exp_s.direction}', found '{act_s.direction}'")
                if exp_s.width > 0 and act_s.width > 0 and exp_s.width != act_s.width:
                    pos_mismatches.append(f"Positional port '{dut_p}' width mismatch: expected {exp_s.width}b, found {act_s.width}b")
                positional_map[tb_p] = dut_p

            if not pos_mismatches and len(positional_map) == len(expected_ports):
                if base_confidence != "EXPLICIT_CONFIG":
                    # Positional mapping to a differently-named module without explicit config
                    # is never silently trusted: check for symmetrical ports or distinct names.
                    input_widths = [dut.ports[p].width for p in dut.port_order if dut.ports[p].direction == "input"]
                    output_widths = [dut.ports[p].width for p in dut.port_order if dut.ports[p].direction == "output"]
                    has_symmetrical_inputs = len(input_widths) != len(set(input_widths))
                    has_symmetrical_outputs = len(output_widths) != len(set(output_widths))

                    if (has_symmetrical_inputs or has_symmetrical_outputs) or not (set(dut.ports.keys()) & set(expected_ports.keys())):
                        is_ambiguous = True
                        ambiguity_reason = (
                            f"Positional mapping between '{dut.name}' and '{expected_module_name}' "
                            f"relies only on port widths/directions without named port or explicit instantiation evidence; mapping is ambiguous."
                        )

                return CompatibilityEvidence(
                    matched=True,
                    reason=f"Positional interface match; wrapper mapping '{dut.name}' -> '{expected_module_name}'.",
                    match_type="WRAPPER_COMPATIBLE",
                    confidence="CONFIRMED" if base_confidence == "EXPLICIT_CONFIG" else "HEURISTIC",
                    expected_module_name=expected_module_name,
                    actual_module_name=dut.name,
                    port_mapping=positional_map,
                    mismatches=[],
                    wrapper_needed=True,
                    is_ambiguous=is_ambiguous,
                    ambiguity_reason=ambiguity_reason
                )

        # Incompatible
        missing = set(expected_ports.keys()) - set(dut.ports.keys())
        extra = set(dut.ports.keys()) - set(expected_ports.keys())
        msg_parts = []
        if missing:
            msg_parts.append(f"Missing ports: {sorted(missing)}")
        if extra:
            msg_parts.append(f"Extra ports: {sorted(extra)}")
        diag = " ; ".join(msg_parts) if msg_parts else "Port count, directions, or widths incompatible."

        return CompatibilityEvidence(
            matched=False,
            reason=diag,
            match_type="INCOMPATIBLE",
            confidence=base_confidence,
            expected_module_name=expected_module_name,
            actual_module_name=dut.name,
            port_mapping={},
            mismatches=[diag],
            wrapper_needed=False,
            is_ambiguous=is_ambiguous,
            ambiguity_reason=ambiguity_reason
        )

    def match_all(
        self,
        candidate_duts: List[ModuleInfo],
        testbenches: List[ModuleInfo]
    ) -> Tuple[List[DUTTestbenchMatch], List[DUTTestbenchMatch], List[ModuleInfo]]:
        """
        Matches candidate DUTs against all testbenches.
        Prioritizes:
        1. Explicit configuration mappings.
        2. Direct module name and port contract.
        3. Wrapper-compatible structural matches.
        Detects ambiguous candidates and marks is_ambiguous=True.
        Returns:
            (valid_matches, interface_error_matches, unmatched_duts)
        """
        valid_matches: List[DUTTestbenchMatch] = []
        interface_error_matches: List[DUTTestbenchMatch] = []
        fully_matched_dut_keys: Set[str] = set()

        # Check explicit user mappings first
        explicit_mappings = self.user_mappings.get("dut_tb_mapping", {})
        if not explicit_mappings and "explicit_mappings" in self.user_mappings:
            for item in self.user_mappings["explicit_mappings"]:
                if isinstance(item, dict) and "dut" in item and "tb" in item:
                    explicit_mappings[item["dut"]] = item["tb"]

        for tb in testbenches:
            tb_reqs = self.extract_tb_dut_requirements(tb)
            if not tb_reqs:
                continue

            for expected_name, expected_ports, port_order, confidence in tb_reqs:
                wrapper_matches_for_this_req: List[DUTTestbenchMatch] = []

                for dut in candidate_duts:
                    # Never match a testbench with itself
                    if dut.file_path == tb.file_path or dut.name == tb.name:
                        continue

                    # Check explicit user mapping
                    is_explicit = (
                        explicit_mappings.get(dut.name) == tb.name or
                        explicit_mappings.get(dut.file_path.stem) == tb.name or
                        explicit_mappings.get(dut.file_path.name) == tb.name
                    )

                    compat = self.evaluate_compatibility(
                        dut=dut,
                        expected_module_name=expected_name,
                        expected_ports=expected_ports,
                        tb_port_order=port_order,
                        base_confidence="EXPLICIT_CONFIG" if is_explicit else confidence,
                        tb=tb
                    )

                    if compat.matched:
                        match_obj = DUTTestbenchMatch(
                            dut=dut,
                            testbench=tb,
                            target_instantiation=expected_name,
                            compatibility=compat,
                            expected_ports=dict(expected_ports),
                            is_ambiguous=compat.is_ambiguous,
                            ambiguity_reason=compat.ambiguity_reason
                        )
                        if is_explicit:
                            match_obj.compatibility.confidence = "CONFIRMED"
                            valid_matches.append(match_obj)
                            fully_matched_dut_keys.add(dut.design_id)
                        elif compat.match_type == "EXACT_NAME":
                            valid_matches.append(match_obj)
                            fully_matched_dut_keys.add(dut.design_id)
                        else:
                            wrapper_matches_for_this_req.append(match_obj)
                    else:
                        # If explicitly named or explicitly mapped, report as INTERFACE ERROR
                        if dut.name == expected_name or is_explicit:
                            interface_error_matches.append(DUTTestbenchMatch(
                                dut=dut,
                                testbench=tb,
                                target_instantiation=expected_name,
                                compatibility=compat,
                                expected_ports=dict(expected_ports),
                                is_ambiguous=False
                            ))
                            fully_matched_dut_keys.add(dut.design_id)

                # Ambiguity handling among wrapper candidates for this testbench target:
                # If two or more completely distinct designs match solely via WRAPPER_COMPATIBLE
                # and neither has explicit user mapping, check if their interfaces are identical
                # and they come from different functional families or lack family hint.
                for w_match in wrapper_matches_for_this_req:
                    # If already marked ambiguous, keep it
                    if not w_match.is_ambiguous and len(wrapper_matches_for_this_req) > 1:
                        # Check if other candidates share identical port interface
                        conflicting = [
                            m.dut.name for m in wrapper_matches_for_this_req
                            if m.dut.design_id != w_match.dut.design_id
                            and set(m.dut.ports.keys()) == set(w_match.dut.ports.keys())
                            # Disambiguate if design stems share family substring with expected_name
                            and not (expected_name.lower().split("_")[0] in w_match.dut.name.lower()
                                     and expected_name.lower().split("_")[0] in m.dut.name.lower())
                        ]
                        if conflicting:
                            w_match.is_ambiguous = True
                            w_match.ambiguity_reason = (
                                f"Ambiguous candidate match: Multiple distinct modules "
                                f"({w_match.dut.name}, {', '.join(conflicting)}) match target '{expected_name}' "
                                f"with identical port contracts. Explicit mapping or manifest required."
                            )
                            w_match.compatibility.is_ambiguous = True
                            w_match.compatibility.ambiguity_reason = w_match.ambiguity_reason

                    valid_matches.append(w_match)
                    fully_matched_dut_keys.add(w_match.dut.design_id)

        unmatched_duts = [d for d in candidate_duts if d.design_id not in fully_matched_dut_keys]
        return valid_matches, interface_error_matches, unmatched_duts
