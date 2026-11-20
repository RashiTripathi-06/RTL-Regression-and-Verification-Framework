import sys
import json
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from executor import IcarusSimulatorAdapter, IsolatedSimulatorExecutor
from models import (
    VerificationPlan,
    CompatibilityEvidence,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL,
    EXEC_SUCCESS,
    VERIF_PASS,
    VERIF_FAIL,
)
from auditor import VerificationAuditor
from reference_verifier import (
    ReferenceConfig,
    ReferenceTiming,
    ReferenceVerificationEngine,
)
from parser import VerilogASTParser

def validate_paths():
    print("================================================================================")
    print(" INDEPENDENT VALIDATION OF PATH A AND PATH B")
    print("================================================================================")

    auditor = VerificationAuditor()
    adapter = IcarusSimulatorAdapter()
    executor = IsolatedSimulatorExecutor(adapter=adapter)
    parser = VerilogASTParser()

    build_base = WORKSPACE_ROOT / "build" / "path_validation"
    build_base.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # PATH A: Existing Testbench Execution without Modifications
    # -------------------------------------------------------------------------
    print("\n--- PATH A: Existing Researcher Testbench Execution ---")
    dut_file_a = WORKSPACE_ROOT / "designs" / "alu_4bit.v"
    tb_file_a = WORKSPACE_ROOT / "tb" / "tb_alu.v"

    plan_a = VerificationPlan(
        plan_id="alu_4bit__tb_alu_path_a",
        dut_name="alu_4bit",
        dut_module="alu_4bit",
        dut_file=dut_file_a,
        tb_name="tb_alu",
        tb_module="tb_alu",
        tb_file=tb_file_a,
        compatibility=CompatibilityEvidence(
            matched=True,
            reason="Exact instantiation",
            match_type="EXACT_NAME",
            expected_module_name="alu_4bit",
            actual_module_name="alu_4bit"
        ),
        required_sources=[dut_file_a, tb_file_a],
        data_files=[],
        build_dir=build_base / "path_a_run",
        timeout_seconds=10.0,
        verification_path="PATH_A"
    )

    print("  Executing existing testbench 'tb_alu.v' for 'alu_4bit'...")
    res_a = executor.execute(plan_a)
    audit_a = auditor.audit(res_a)

    print(f"  Simulation returncode:  {res_a.sim_returncode}")
    print(f"  Execution Status:       {audit_a.execution_status} (Process exited cleanly)")
    print(f"  Audited Overall Status: {audit_a.status}")
    print(f"  Functional Status:      {audit_a.functional_status}")
    print(f"  Diagnostic Summary:     {audit_a.diagnostic_summary}")

    # Path A Assertions
    assert res_a.compile_returncode == 0, f"Compilation failed: {res_a.compile_stderr}"
    assert res_a.sim_returncode == 0, f"Simulation failed: {res_a.sim_stderr}"
    assert audit_a.execution_status == EXEC_SUCCESS, "Execution status must be EXEC_SUCCESS."
    assert audit_a.status == STATUS_PASS_TESTBENCH_ONLY, f"Expected PASS_TESTBENCH_ONLY, got {audit_a.status}."
    assert "self-checking testbench assertions passed" in audit_a.diagnostic_summary, \
        "Diagnostic must state that self-checking assertions passed without independent golden reference."
    print("  -> Path A Integrity: PASSED (Self-checking assertions classified as PASS_TESTBENCH_ONLY, not reference-verified)")

    # -------------------------------------------------------------------------
    # PATH B: Independent Golden Reference Verification
    # -------------------------------------------------------------------------
    print("\n--- PATH B: Independent Golden Reference Verification Engine ---")
    ref_engine = ReferenceVerificationEngine(adapter=adapter)
    csv_ref = WORKSPACE_ROOT / "tb" / "golden_adder.csv"

    config_b = ReferenceConfig(
        file=csv_ref,
        format="csv",
        radix="hex",
        input_mapping={"operand_a": "a", "operand_b": "b", "cin": "cin"},
        output_mapping={"expected_sum": "sum", "expected_cout": "cout"},
        timing=ReferenceTiming(mode="combinational", settling_time_ns=1.0)
    )

    # 1. Valid CLA Adder
    cla_file = WORKSPACE_ROOT / "designs" / "adder_cla.v"
    mods_cla = parser.parse_file(cla_file)
    dut_cla = mods_cla[0]
    print(f"  Verifying {dut_cla.name} against golden reference (512 vectors)...")
    res_b_pass = ref_engine.verify(
        dut=dut_cla,
        config=config_b,
        dependencies=[],
        build_dir=build_base / "path_b_cla"
    )
    print(f"  Execution Status:   {res_b_pass.execution_status}")
    print(f"  Overall Status:     {res_b_pass.status}")
    print(f"  Functional Status:  {res_b_pass.functional_status}")
    print(f"  Vectors Passed:     {res_b_pass.passed_vectors} / {res_b_pass.total_vectors}")
    print(f"  Diagnostic:         {res_b_pass.diagnostic_summary}")

    assert res_b_pass.execution_status == EXEC_SUCCESS
    assert res_b_pass.status == STATUS_PASS_REFERENCE_VERIFIED
    assert res_b_pass.functional_status == VERIF_PASS
    assert res_b_pass.passed_vectors == 512
    print("  -> Path B Golden Reference Pass: PASSED")

    # 2. Buggy Adder (Functional Defect Detection)
    buggy_file = WORKSPACE_ROOT / "designs" / "adder_buggy.v"
    mods_buggy = parser.parse_file(buggy_file)
    dut_buggy = mods_buggy[0]
    print(f"\n  Verifying {dut_buggy.name} against golden reference (512 vectors)...")
    res_b_fail = ref_engine.verify(
        dut=dut_buggy,
        config=config_b,
        dependencies=[],
        build_dir=build_base / "path_b_buggy"
    )
    print(f"  Execution Status:   {res_b_fail.execution_status} (Simulation executed to end)")
    print(f"  Overall Status:     {res_b_fail.status} (Functional bug caught!)")
    print(f"  Functional Status:  {res_b_fail.functional_status}")
    print(f"  Vectors Passed:     {res_b_fail.passed_vectors} / {res_b_fail.total_vectors}")
    print(f"  Vectors Failed:     {res_b_fail.failed_vectors}")
    print(f"  Diagnostic:         {res_b_fail.diagnostic_summary}")
    print(f"  First Mismatch Record:")
    m0 = res_b_fail.failing_vectors[0]
    print(f"    Index:    {m0['index']}")
    print(f"    Inputs:   {m0['inputs']}")
    print(f"    Actual:   {m0.get('actual_outputs', m0.get('actual'))}")
    print(f"    Expected: {m0.get('expected_outputs', m0.get('expected'))}")

    assert res_b_fail.execution_status == EXEC_SUCCESS, "Simulation completed without crashing."
    assert res_b_fail.status == STATUS_FUNCTIONAL_FAIL, "Status must be STATUS_FUNCTIONAL_FAIL."
    assert res_b_fail.functional_status == VERIF_FAIL, "Functional status must be VERIF_FAIL."
    assert res_b_fail.failed_vectors == 128, f"Expected 128 failures, got {res_b_fail.failed_vectors}."
    assert len(res_b_fail.failing_vectors) > 0, "Mismatch records must be captured."
    print("  -> Path B Functional Defect Detection: PASSED")

    print("\n================================================================================")
    print(" PATH A AND PATH B INDEPENDENT VALIDATION COMPLETE!")
    print("================================================================================")

if __name__ == "__main__":
    validate_paths()
