from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
from .models import PortSpec

def generate_dut_wrapper(
    expected_module_name: str,
    actual_module_name: str,
    expected_ports: Dict[str, PortSpec],
    actual_ports: Dict[str, PortSpec],
    port_mapping: Dict[str, str], # tb_port -> dut_port
    output_file: Path,
    parameters: Optional[Dict[str, Any]] = None
) -> Path:
    """
    Synthesizes a transparent, verified structural Verilog wrapper module.
    Refuses to generate wrappers for unmapped, width-mismatched, or direction-mismatched ports.
    """
    if not port_mapping:
        raise ValueError("Cannot generate wrapper: port_mapping is empty.")

    # Verify all expected ports are mapped
    missing_tb_ports = set(expected_ports.keys()) - set(port_mapping.keys())
    if missing_tb_ports:
        raise ValueError(f"Cannot generate wrapper: unmapped testbench ports: {sorted(missing_tb_ports)}")

    # Verify all actual DUT ports are mapped
    missing_dut_ports = set(actual_ports.keys()) - set(port_mapping.values())
    if missing_dut_ports:
        raise ValueError(f"Cannot generate wrapper: unmapped DUT ports: {sorted(missing_dut_ports)}")

    # Verify all mapped DUT ports exist and validate directions and bit-widths
    validation_errors = []
    for tb_p, dut_p in port_mapping.items():
        if dut_p not in actual_ports:
            validation_errors.append(f"Mapped DUT port '{dut_p}' not found in actual module '{actual_module_name}'")
            continue

        exp_s = expected_ports[tb_p]
        act_s = actual_ports[dut_p]

        # Direction verification
        if exp_s.direction and act_s.direction and exp_s.direction != act_s.direction:
            validation_errors.append(
                f"Direction mismatch on '{tb_p}' -> '{dut_p}': expected {exp_s.direction}, actual {act_s.direction}"
            )

        # Width verification
        if exp_s.width > 0 and act_s.width > 0 and exp_s.width != act_s.width:
            validation_errors.append(
                f"Width mismatch on '{tb_p}' -> '{dut_p}': expected {exp_s.width}b, actual {act_s.width}b"
            )

    if validation_errors:
        raise ValueError(f"Incompatible wrapper mapping for '{actual_module_name}': " + " ; ".join(validation_errors))

    # Generate Verilog wrapper
    port_decls = []
    inst_conns = []

    for tb_p, exp_s in expected_ports.items():
        w = exp_s.width
        rng = f"[{w - 1}:0] " if w > 1 else ""
        direction = exp_s.direction or "input"
        port_decls.append(f"    {direction} wire {rng}{tb_p}")
        dut_p = port_mapping[tb_p]
        inst_conns.append(f"        .{dut_p}({tb_p})")

    param_str = ""
    if parameters:
        p_pairs = [f".{k}({v})" for k, v in parameters.items()]
        param_str = f" #({', '.join(p_pairs)})"

    content = [
        "`timescale 1ns/1ps",
        f"// Auto-generated verified structural wrapper: '{actual_module_name}' -> '{expected_module_name}'",
        f"module {expected_module_name} (",
        ",\n".join(port_decls),
        ");",
        f"    {actual_module_name}{param_str} u_wrapped_dut (",
        ",\n".join(inst_conns),
        "    );",
        "endmodule\n"
    ]

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(content), encoding="utf-8")
    return output_file
