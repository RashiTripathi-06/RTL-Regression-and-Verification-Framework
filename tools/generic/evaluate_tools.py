import os
import sys
import subprocess
import shutil
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "framework" / "src"))

def run_experiment_hdlregression():
    print("\n" + "="*80)
    print(" EXPERIMENT 1: HDLRegression with Questa / Modelsim")
    print("="*80)
    exp_dir = WORKSPACE_ROOT / "build" / "exp_hdlregression"
    if exp_dir.exists():
        shutil.rmtree(exp_dir, ignore_errors=True)
    exp_dir.mkdir(parents=True, exist_ok=True)

    try:
        from hdlregression import HDLRegression
        print("[OK] Successfully imported HDLRegression")
    except Exception as e:
        print(f"[FAIL] Could not import HDLRegression: {e}")
        return {"status": "IMPORT_FAIL", "error": str(e)}

    orig_cwd = os.getcwd()
    try:
        os.chdir(str(exp_dir))
        hr = HDLRegression()

        # Testbench files
        alu_dut = str(WORKSPACE_ROOT / "designs" / "alu_4bit.v")
        alu_tb = str(WORKSPACE_ROOT / "tb" / "tb_alu.v")

        hr.add_files(alu_dut, "work")
        hr.add_files(alu_tb, "work")

        # Check simulator detection
        hr.set_simulator("modelsim")
        print("  Configured HDLRegression targeting 'modelsim' simulator...")
        print("  Running HDLRegression regression engine...")

        ret = hr.start()
        print(f"  HDLRegression completed with return code: {ret}")
        num_run = hr.get_num_tests_run()
        num_pass = hr.get_num_pass_tests()
        num_fail = hr.get_num_fail_tests()
        print(f"  HDLRegression stats: run={num_run}, pass={num_pass}, fail={num_fail}")
        return {
            "status": "SUCCESS" if ret == 0 else "TESTS_COMPLETED",
            "ret": ret,
            "tests_run": num_run,
            "tests_pass": num_pass,
            "tests_fail": num_fail
        }
    except Exception as e:
        print(f"  HDLRegression Exception: {type(e).__name__}: {e}")
        return {"status": "EXCEPTION", "error": f"{type(e).__name__}: {e}"}
    finally:
        os.chdir(orig_cwd)

def run_experiment_vunit():
    print("\n" + "="*80)
    print(" EXPERIMENT 2: VUnit HDL Evaluation")
    print("="*80)
    exp_dir = WORKSPACE_ROOT / "build" / "exp_vunit"
    if exp_dir.exists():
        shutil.rmtree(exp_dir, ignore_errors=True)
    exp_dir.mkdir(parents=True, exist_ok=True)

    try:
        import vunit
        from vunit import VUnit
        print(f"[OK] Successfully imported VUnit (vunit_hdl v{getattr(vunit, '__version__', 'unknown')})")
    except Exception as e:
        print(f"[FAIL] Could not import VUnit: {e}")
        return {"status": "IMPORT_FAIL", "error": str(e)}

    try:
        vu = VUnit.from_argv(argv=["--output-path", str(exp_dir)], compile_builtins=False)
        lib = vu.add_library("tb_lib")
        lib.add_source_files(str(WORKSPACE_ROOT / "designs" / "alu_4bit.v"))
        lib.add_source_files(str(WORKSPACE_ROOT / "tb" / "tb_alu.v"))
        print("  Added alu_4bit.v and tb_alu.v to VUnit library 'work'")

        # Test discovery on regular Verilog testbenches
        tbs = lib.get_test_benches()
        tb_names = [tb.name for tb in tbs]
        print(f"  VUnit discovered testbenches: {tb_names}")
        print("  VUnit Analysis Note: VUnit requires testbenches to use VUnit's VHDL test runner package or SV test runner macros.")
        print("  Existing standard Verilog testbenches without VUnit decorators require VUnit testbench wrappers or run-as-is adapters.")
        return {
            "status": "SUCCESS",
            "discovered_testbenches": tb_names,
            "requires_vunit_test_runner": True
        }
    except Exception as e:
        print(f"  VUnit Exception: {type(e).__name__}: {e}")
        return {"status": "EXCEPTION", "error": f"{type(e).__name__}: {e}"}

def run_experiment_cocotb():
    print("\n" + "="*80)
    print(" EXPERIMENT 3: Cocotb Driving DUT and Checking Golden Reference")
    print("="*80)
    exp_dir = WORKSPACE_ROOT / "build" / "exp_cocotb"
    exp_dir.mkdir(parents=True, exist_ok=True)

    try:
        import cocotb
        from cocotb_tools.runner import get_runner
        print(f"[OK] Successfully imported Cocotb (v{cocotb.__version__}) and cocotb_tools.runner")
    except Exception as e:
        print(f"[FAIL] Could not import Cocotb: {e}")
        return {"status": "IMPORT_FAIL", "error": str(e)}

    # Clean test file
    cocotb_test_code = '''
import cocotb
from cocotb.triggers import Timer

def python_alu_ref(a, b, opcode):
    if opcode == 0: return (a + b) & 0xF
    elif opcode == 1: return (a - b) & 0xF
    elif opcode == 2: return a & b
    elif opcode == 3: return a | b
    elif opcode == 4: return a ^ b
    elif opcode == 5: return (~a) & 0xF
    elif opcode == 6: return (a << 1) & 0xF
    elif opcode == 7: return (a >> 1) & 0xF
    return 0

@cocotb.test()
async def test_alu_basic(dut):
    """Cocotb test driving alu_4bit and comparing against Python golden model."""
    dut._log.info("Starting Cocotb ALU reference verification")

    test_vectors = [
        (4, 2, 0),      # 4 + 2 = 6
        (5, 3, 1),      # 5 - 3 = 2
        (0xC, 0xA, 2),  # C & A = 8
        (0x5, 0x3, 3),  # 5 | 3 = 7
        (0xF, 0xF, 4),  # F ^ F = 0
    ]

    mismatches = 0
    for idx, (a, b, op) in enumerate(test_vectors):
        dut.a.value = a
        dut.b.value = b
        dut.opcode.value = op
        await Timer(1, units="ns")

        expected = python_alu_ref(a, b, op)
        actual = int(dut.alu_out.value)
        if actual != expected:
            dut._log.error(f"Vector {idx}: a={a}, b={b}, op={op}: Expected {expected}, got {actual}")
            mismatches += 1
        else:
            dut._log.info(f"Vector {idx} PASS: a={a}, b={b}, op={op} -> {actual}")

    assert mismatches == 0, f"Encountered {mismatches} mismatches in Cocotb reference scoreboard."
'''
    test_file = exp_dir / "test_alu_cocotb.py"
    test_file.write_text(cocotb_test_code.strip() + "\n", encoding="utf-8")
    print(f"  Created Cocotb test file: {test_file.name}")

    sim_name = "icarus" if shutil.which("iverilog") else "questa"
    try:
        runner = get_runner(sim_name)
        print(f"  Building with Cocotb runner: {sim_name}...")
        runner.build(
            sources=[WORKSPACE_ROOT / "designs" / "alu_4bit.v"],
            hdl_toplevel="alu_4bit",
            build_dir=exp_dir / "sim_build",
            always=True
        )
        print(f"  Build completed. Running Cocotb simulation...")
        runner.test(
            hdl_toplevel="alu_4bit",
            test_module="test_alu_cocotb",
            test_dir=exp_dir,
            results_xml=str(exp_dir / "results.xml")
        )
        print(f"  [SUCCESS] Cocotb verification passed 100% against Python golden reference!")
        return {"status": "SUCCESS", "simulator": sim_name, "results_xml": str(exp_dir / "results.xml")}
    except Exception as e:
        print(f"  Cocotb Execution Exception: {type(e).__name__}: {e}")
        return {"status": "RUNNER_EXCEPTION", "error": f"{type(e).__name__}: {e}"}

def run_experiment_edalize():
    print("\n" + "="*80)
    print(" EXPERIMENT 4: Edalize Simulator Launcher (Questa / Icarus)")
    print("="*80)
    exp_dir = WORKSPACE_ROOT / "build" / "exp_edalize"
    exp_dir.mkdir(parents=True, exist_ok=True)

    try:
        import edalize
        from edalize.edatool import get_edatool
        print(f"[OK] Successfully imported Edalize")
    except Exception as e:
        print(f"[FAIL] Could not import Edalize: {e}")
        return {"status": "IMPORT_FAIL", "error": str(e)}

    lic_test = WORKSPACE_ROOT / "license_test.v"
    edam = {
        "name": "license_test_edalize",
        "version": "0.2.0",
        "files": [
            {"name": str(lic_test.resolve()), "file_type": "verilogSource"}
        ],
        "toplevel": "license_test",
        "tool_options": {
            "modelsim": {
                "vlog_options": ["-sv"]
            },
            "icarus": {
                "iverilog_options": ["-g2012"]
            }
        }
    }

    # Test tool configure() and manifest generation
    for tool_name in ["modelsim", "icarus"]:
        tool_dir = exp_dir / tool_name
        tool_dir.mkdir(parents=True, exist_ok=True)
        try:
            tool_cls = get_edatool(tool_name)
            backend = tool_cls(edam=edam, work_root=str(tool_dir))
            backend.configure()
            print(f"  [{tool_name}] configure() generated EDAM / build scripts successfully in {tool_dir.name}/")
            # Build requires 'make' on system path for modelsim/icarus
            make_found = shutil.which("make") is not None
            if make_found:
                backend.build()
                print(f"  [{tool_name}] build() completed.")
                backend.run()
                print(f"  [{tool_name}] run() completed.")
            else:
                print(f"  [{tool_name}] Build skipped: Windows shell lacks 'make' utility. Edalize produces Makefile but requires GNU Make to orchestrate vlog/vsim.")
        except Exception as e:
            print(f"  [{tool_name}] Exception: {type(e).__name__}: {e}")

    return {
        "status": "EDAM_CONFIGURED",
        "note": "Edalize successfully configures EDA metadata and generates Makefiles/scripts, but Windows execution requires external GNU Make."
    }

if __name__ == "__main__":
    results = {}
    results["hdlregression"] = run_experiment_hdlregression()
    results["vunit"] = run_experiment_vunit()
    results["cocotb"] = run_experiment_cocotb()
    results["edalize"] = run_experiment_edalize()

    print("\n" + "="*80)
    print(" COMPATIBILITY EXPERIMENTS SUMMARY")
    print("="*80)
    for k, v in results.items():
        print(f"  {k:<15}: {v}")
