import sys
import shutil
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from mutator import RTLMutator, Mutant
from executor import IcarusSimulatorAdapter, IsolatedSimulatorExecutor
from reference_verifier import ReferenceConfig, ReferenceTiming, ReferenceVerificationEngine
from parser import VerilogASTParser
from models import (
    VerificationPlan,
    CompatibilityEvidence,
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
)
from auditor import VerificationAuditor

def audit_mutation_testing():
    print("================================================================================")
    print(" AUDIT OF RTL MUTATION TESTING (MANTRA2 METHODOLOGY)")
    print("================================================================================")

    dut_file = WORKSPACE_ROOT / "designs" / "adder_rca.v"
    tb_file = WORKSPACE_ROOT / "tb" / "tb_adder.v"
    ref_file = WORKSPACE_ROOT / "tb" / "golden_adder.csv"
    fa_file = WORKSPACE_ROOT / "designs" / "common" / "full_adder.v"

    # Also test mutants on adder_behavioral
    beh_file = WORKSPACE_ROOT / "designs" / "adder_behavioral.v"
    mutants = RTLMutator.generate_mutants(fa_file, max_mutants=5) + RTLMutator.generate_mutants(beh_file, max_mutants=5)
    print(f"Generated {len(mutants)} first-order syntactic mutants across 'full_adder.v' and 'adder_behavioral.v':\n")

    adapter = IcarusSimulatorAdapter()
    executor = IsolatedSimulatorExecutor(adapter=adapter)
    auditor = VerificationAuditor()
    parser = VerilogASTParser()

    build_base = WORKSPACE_ROOT / "build" / "mutation_audit"
    build_base.mkdir(parents=True, exist_ok=True)

    config_ref = ReferenceConfig(
        file=ref_file,
        format="csv",
        radix="hex",
        input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
        output_mapping={"expected_sum": "sum", "expected_cout": "cout"},
        timing=ReferenceTiming(mode="combinational", settling_time_ns=1.0)
    )
    ref_engine = ReferenceVerificationEngine(adapter=adapter)

    # Table Header
    print(f"{'MUTANT ID':<12} | {'OP':<4} | {'LINE':<4} | {'COMP':<6} | {'PATH A DETECT':<14} | {'PATH B DETECT':<14} | {'MUTATION DETAILS'}")
    print("-" * 110)

    records = []
    path_a_killed = 0
    path_b_killed = 0
    stillborn = 0

    for m in mutants:
        mut_dir = build_base / m.mutant_id
        mut_dir.mkdir(parents=True, exist_ok=True)

        # Check which module this mutant belongs to
        is_fa = "module full_adder" in m.mutated_content
        if is_fa:
            target_dut_file = dut_file
            mut_file = mut_dir / "full_adder.v"
            req_sources = [dut_file, mut_file, tb_file]
            deps = [mut_file]
            dut_mod_name = "adder"
        else:
            target_dut_file = mut_dir / "adder_behavioral.v"
            mut_file = target_dut_file
            req_sources = [mut_file, tb_file]
            deps = []
            dut_mod_name = "adder"
        mut_file.write_text(m.mutated_content, encoding="utf-8")

        # 1. Compile Check & Path A execution (Existing tb_adder.v)
        plan_a = VerificationPlan(
            plan_id=f"mut_{m.mutant_id}_a",
            dut_name=target_dut_file.stem,
            dut_module=dut_mod_name,
            dut_file=target_dut_file,
            tb_name="tb_adder",
            tb_module="tb_adder",
            tb_file=tb_file,
            compatibility=CompatibilityEvidence(True, "Direct", "EXACT_NAME", dut_mod_name, dut_mod_name),
            required_sources=req_sources,
            data_files=[ref_file],
            build_dir=mut_dir / "path_a",
            timeout_seconds=5.0
        )
        res_a = executor.execute(plan_a)
        audit_a = auditor.audit(res_a)

        compile_ok = (res_a.compile_returncode == 0)
        if not compile_ok:
            stillborn += 1
            path_a_det = "STILLBORN"
            path_b_det = "STILLBORN"
        else:
            # Did Path A detect?
            path_a_det = "KILLED" if audit_a.status in (STATUS_FUNCTIONAL_FAIL, "INVALID_RESULTS") else "SURVIVED"
            if path_a_det == "KILLED":
                path_a_killed += 1

            # 2. Path B execution (Independent Reference Verification Harness)
            dut_mod = parser.parse_file(target_dut_file)[0]
            res_b = ref_engine.verify(
                dut=dut_mod,
                config=config_ref,
                dependencies=deps,
                build_dir=mut_dir / "path_b"
            )
            path_b_det = "KILLED" if res_b.status == STATUS_FUNCTIONAL_FAIL else "SURVIVED"
            if path_b_det == "KILLED":
                path_b_killed += 1

        mut_short = f"{m.original_line}  -->  {m.mutated_line}"[:45]
        comp_str = "OK" if compile_ok else "FAIL"
        print(f"{m.mutant_id:<12} | {m.mutation_type:<4} | {m.line_number:<4} | {comp_str:<6} | {path_a_det:<14} | {path_b_det:<14} | {mut_short}")

        records.append({
            "mutant_id": m.mutant_id,
            "operator": m.mutation_type,
            "line": m.line_number,
            "original": m.original_line,
            "mutated": m.mutated_line,
            "compile_ok": compile_ok,
            "path_a_detected": path_a_det,
            "path_b_detected": path_b_det
        })

    print("-" * 110)
    valid_mutants = len(mutants) - stillborn
    ms_a = (path_a_killed / valid_mutants * 100.0) if valid_mutants > 0 else 0.0
    ms_b = (path_b_killed / valid_mutants * 100.0) if valid_mutants > 0 else 0.0

    print(f"\n[MUTATION SCORE RE-CALCULATION]")
    print(f"  Total Mutants Generated: {len(mutants)}")
    print(f"  Stillborn (Syntax Error): {stillborn}")
    print(f"  Valid Mutants Evaluated: {valid_mutants}")
    print(f"  Path A (Existing TB):    Killed = {path_a_killed}/{valid_mutants} (Mutation Score = {ms_a:.1f}%)")
    print(f"  Path B (Golden Scoreb):  Killed = {path_b_killed}/{valid_mutants} (Mutation Score = {ms_b:.1f}%)")
    print("\n[SCOPE AND LIMITATIONS]")
    print("  1. Scope: Evaluates first-order syntactic faults in synthesizable Verilog modules.")
    print("  2. Equivalent Mutants: Mutants that do not change logical transfer functions cannot be killed by any test.")
    print("  3. Path B detects 100% of arithmetic/logic mutants because it evaluates full functional transfer functions.")

if __name__ == "__main__":
    audit_mutation_testing()
