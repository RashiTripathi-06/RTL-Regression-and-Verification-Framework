import os
import sys
import threading
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from executor import QuestaSimulatorAdapter, IsolatedSimulatorExecutor
from models import (
    VerificationPlan,
    CompatibilityEvidence,
    STATUS_COMPILE_ERROR,
    STATUS_TIMEOUT,
    STATUS_PASS,
    EXEC_SUCCESS,
    EXEC_COMPILE_ERROR,
    EXEC_TIMEOUT,
)
from auditor import VerificationAuditor

def validate_questa():
    print("================================================================================")
    print(" NATIVE QUESTA 2025.3 SIMULATOR ADAPTER VALIDATION")
    print("================================================================================")

    adapter = QuestaSimulatorAdapter()

    # 1. Discovery
    print("\n[1] Checking Executable Discovery...")
    print(f"  vlib: {adapter.vlib_path}")
    print(f"  vlog: {adapter.vlog_path}")
    print(f"  vsim: {adapter.vsim_path}")
    assert adapter.is_available(), "Questa executables must be discovered."
    print("  -> Discovery: PASSED")

    # 2. Version Detection
    print("\n[2] Checking Version Detection...")
    version = adapter.get_version()
    print(f"  Questa Version: {version}")
    assert "2025" in version or "Questa" in version, "Version string must identify Questa."
    print("  -> Version: PASSED")

    # 3. License Validation
    print("\n[3] Validating License Environment...")
    lic_env = os.environ.get("SALT_LICENSE_SERVER") or os.environ.get("LM_LICENSE_FILE")
    print(f"  SALT_LICENSE_SERVER = {lic_env}")
    assert lic_env is not None and Path(lic_env).exists(), "License file must exist."
    print(f"  License File Exists: OK ({Path(lic_env).stat().st_size} bytes)")
    print("  -> License Environment: PASSED")

    build_base = WORKSPACE_ROOT / "build" / "questa_validation"
    build_base.mkdir(parents=True, exist_ok=True)
    executor = IsolatedSimulatorExecutor(adapter=adapter)
    auditor = VerificationAuditor()

    # 4. Valid Design Execution
    lic_test_path = WORKSPACE_ROOT / "license_test.v"
    print(f"\n[4] Running Valid Design Simulation ({lic_test_path.name})...")
    valid_plan = VerificationPlan(
        plan_id="questa_valid_test",
        dut_name="license_test",
        dut_module="license_test",
        dut_file=lic_test_path,
        tb_name="license_test",
        tb_module="license_test",
        tb_file=lic_test_path,
        compatibility=CompatibilityEvidence(
            matched=True,
            reason="Self-contained",
            match_type="EXACT_NAME",
            expected_module_name="license_test",
            actual_module_name="license_test"
        ),
        required_sources=[lic_test_path],
        data_files=[],
        build_dir=build_base / "valid_run",
        timeout_seconds=15.0,
        questa_flags=["-sv"]
    )
    t0 = time.perf_counter()
    res_valid = executor.execute(valid_plan)
    t_valid = time.perf_counter() - t0
    print(f"  Compile returncode: {res_valid.compile_returncode}")
    print(f"  Sim returncode:     {res_valid.sim_returncode}")
    print(f"  Elapsed time:       {t_valid:.3f}s")
    print("  Simulator output snippet:")
    for line in res_valid.sim_stdout.splitlines()[-6:]:
        print(f"    {line}")
    assert res_valid.compile_returncode == 0, f"Compilation failed: {res_valid.compile_stderr}"
    assert res_valid.sim_returncode == 0, f"Simulation failed: {res_valid.sim_stderr}"
    assert "QUESTA LICENSE TEST PASSED" in res_valid.sim_stdout, "Expected output sentinel not found."
    print("  -> Valid Design Execution: PASSED")

    # 5. Deliberately Invalid Design (Compilation Error)
    print("\n[5] Running Invalid Design (designs/adder_syntax_error.v)...")
    invalid_plan = VerificationPlan(
        plan_id="questa_invalid_test",
        dut_name="adder_syntax_error",
        dut_module="adder_syntax_error",
        dut_file=WORKSPACE_ROOT / "designs" / "adder_syntax_error.v",
        tb_name="tb_adder",
        tb_module="tb_adder",
        tb_file=WORKSPACE_ROOT / "tb" / "tb_adder.v",
        compatibility=CompatibilityEvidence(
            matched=True,
            reason="Direct",
            match_type="EXACT_NAME",
            expected_module_name="adder_syntax_error",
            actual_module_name="adder_syntax_error"
        ),
        required_sources=[
            WORKSPACE_ROOT / "designs" / "adder_syntax_error.v",
            WORKSPACE_ROOT / "tb" / "tb_adder.v"
        ],
        data_files=[],
        build_dir=build_base / "invalid_run",
        timeout_seconds=10.0,
        questa_flags=["-sv"]
    )
    res_invalid = executor.execute(invalid_plan)
    print(f"  Compile returncode: {res_invalid.compile_returncode} (expected non-zero)")
    print(f"  Compile stderr/stdout snippet: {res_invalid.compile_stderr[:120]}...")
    assert res_invalid.compile_returncode != 0, "Invalid design must fail compilation."
    audit_inv = auditor.audit(res_invalid)
    print(f"  Audited Status:     {audit_inv.status}")
    assert audit_inv.execution_status == EXEC_COMPILE_ERROR, "Execution status must be EXEC_COMPILE_ERROR."
    print("  -> Error Classification (Compile Error): PASSED")

    # 6. Watchdog Timeout Handling
    print("\n[6] Testing Watchdog Timeout Handling (Simulating clock with no $finish)...")
    hang_test_file = build_base / "hang_test.v"
    hang_test_file.write_text(
        "module hang_test;\n"
        "  reg clk;\n"
        "  initial begin\n"
        "    $display(\"=== TESTBENCH_START ===\");\n"
        "    clk = 0;\n"
        "    forever #5 clk = ~clk; // Never calls $finish\n"
        "  end\n"
        "endmodule\n",
        encoding="utf-8"
    )
    timeout_plan = VerificationPlan(
        plan_id="questa_timeout_test",
        dut_name="hang_test",
        dut_module="hang_test",
        dut_file=hang_test_file,
        tb_name="hang_test",
        tb_module="hang_test",
        tb_file=hang_test_file,
        compatibility=CompatibilityEvidence(
            matched=True,
            reason="Direct",
            match_type="EXACT_NAME",
            expected_module_name="hang_test",
            actual_module_name="hang_test"
        ),
        required_sources=[hang_test_file],
        data_files=[],
        build_dir=build_base / "timeout_run",
        timeout_seconds=3.0,  # Short watchdog timeout
        questa_flags=["-sv"]
    )
    t0 = time.perf_counter()
    res_timeout = executor.execute(timeout_plan)
    t_timeout = time.perf_counter() - t0
    print(f"  Compile returncode: {res_timeout.compile_returncode}")
    print(f"  Sim returncode:     {res_timeout.sim_returncode}")
    print(f"  Timed out flag:     {res_timeout.timed_out}")
    print(f"  Elapsed wall clock: {t_timeout:.3f}s")
    if not res_timeout.timed_out:
        print(f"  Compile stdout: {res_timeout.compile_stdout}")
        print(f"  Sim stdout: {res_timeout.sim_stdout}")
        print(f"  Sim stderr: {res_timeout.sim_stderr}")
    assert res_timeout.timed_out is True, "Watchdog must flag timed_out=True."
    audit_to = auditor.audit(res_timeout)
    print(f"  Audited Status:     {audit_to.status}")
    assert audit_to.execution_status == EXEC_TIMEOUT, "Execution status must be EXEC_TIMEOUT."
    print("  -> Watchdog Timeout Handling: PASSED")

    # 7. Sequential Execution under License Constraint Mutex
    print("\n[7] Verifying Single-Session License Mutex Serialization...")
    timestamps = []

    def run_worker(wid: int):
        plan_w = VerificationPlan(
            plan_id=f"questa_mutex_w{wid}",
            dut_name="license_test",
            dut_module="license_test",
            dut_file=lic_test_path,
            tb_name="license_test",
            tb_module="license_test",
            tb_file=lic_test_path,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct",
                match_type="EXACT_NAME",
                expected_module_name="license_test",
                actual_module_name="license_test"
            ),
            required_sources=[lic_test_path],
            data_files=[],
            build_dir=build_base / f"mutex_w{wid}",
            timeout_seconds=15.0,
            questa_flags=["-sv"]
        )
        start = time.perf_counter()
        res_w = executor.execute(plan_w)
        end = time.perf_counter()
        timestamps.append((wid, start, end, res_w.sim_returncode))

    th1 = threading.Thread(target=run_worker, args=(1,))
    th2 = threading.Thread(target=run_worker, args=(2,))
    t_start_all = time.perf_counter()
    th1.start()
    th2.start()
    th1.join()
    th2.join()
    total_time = time.perf_counter() - t_start_all

    print(f"  Thread 1: start={timestamps[0][1] - t_start_all:.2f}s, end={timestamps[0][2] - t_start_all:.2f}s, rc={timestamps[0][3]}")
    print(f"  Thread 2: start={timestamps[1][1] - t_start_all:.2f}s, end={timestamps[1][2] - t_start_all:.2f}s, rc={timestamps[1][3]}")
    print(f"  Total serialized time: {total_time:.2f}s")
    # Both simulations must succeed with exit code 0
    assert timestamps[0][3] == 0 and timestamps[1][3] == 0, "Both serialized simulations must succeed."
    # Total time must reflect sequential execution (t1 + t2), not parallel
    assert total_time >= 4.0, f"Simulations must execute sequentially under license lock (took {total_time:.2f}s)."
    print("  -> Sequential Execution Mutex: PASSED (Zero license checkout conflicts)")

    print("\n================================================================================")
    print(" ALL QUESTA ADAPTER CHECKS PASSED SUCCESSFULLY!")
    print("================================================================================")

if __name__ == "__main__":
    validate_questa()
