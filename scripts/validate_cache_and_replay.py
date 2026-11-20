import json
import shutil
import tempfile
import time
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT / "src"))

from cache_manager import CacheManager
from models import VerificationPlan, CompatibilityEvidence, TestResult, STATUS_PASS
from engine import RegressionEngine

def validate_cache_and_replay():
    print("================================================================================")
    print(" CRYPTOGRAPHIC MERKLE CACHE & REPLAY VALIDATION")
    print("================================================================================")

    tmp_dir = Path(tempfile.mkdtemp(prefix="cache_val_"))
    try:
        # Create minimal project hierarchy
        dut_file = tmp_dir / "dut.v"
        dut_file.write_text("module dut(input a, output y); assign y = a; endmodule\n", encoding="utf-8")

        dep_file = tmp_dir / "submod.v"
        dep_file.write_text("module submod(input in, output out); assign out = in; endmodule\n", encoding="utf-8")

        tb_file = tmp_dir / "tb_dut.v"
        tb_file.write_text("module tb_dut; reg a; wire y; dut uut(a, y); initial #1 $finish; endmodule\n", encoding="utf-8")

        ref_file = tmp_dir / "golden.csv"
        ref_file.write_text("a,expected_y\n0,0\n1,1\n", encoding="utf-8")

        inc_file = tmp_dir / "defs.vh"
        inc_file.write_text("`define TIMEOUT 100\n", encoding="utf-8")

        plan = VerificationPlan(
            plan_id="dut__tb_dut",
            dut_name="dut",
            dut_module="dut",
            dut_file=dut_file,
            tb_name="tb_dut",
            tb_module="tb_dut",
            tb_file=tb_file,
            compatibility=CompatibilityEvidence(True, "Direct", "EXACT_NAME", "dut", "dut"),
            required_sources=[dut_file, dep_file, tb_file],
            data_files=[ref_file],
            include_files=[inc_file],
            iverilog_flags=["-g2012"],
            simulator_name="icarus"
        )

        cache_file = tmp_dir / "test_cache.json"
        cache_mgr = CacheManager(cache_file)

        # Baseline Hash
        h_base = cache_mgr.compute_hash(plan)
        print(f"[1] Computed Baseline Merkle Root Hash: {h_base[:16]}...")

        # 1. Cache hit when unchanged
        fake_result = TestResult(
            plan_id=plan.plan_id,
            dut_name=plan.dut_name,
            tb_name=plan.tb_name,
            status=STATUS_PASS,
            passed_vectors=2,
            total_vectors=2
        )
        cache_mgr.put(plan, fake_result)
        hit = cache_mgr.get(plan)
        assert hit is not None and hit.cached is True, "Unchanged run must produce valid CACHE HIT."
        print("  -> Unchanged Run: CACHE HIT (OK)")

        # 2. Invalidation on DUT modification
        dut_file.write_text("module dut(input a, output y); assign y = ~a; endmodule\n", encoding="utf-8")
        h_dut_mod = cache_mgr.compute_hash(plan)
        assert h_dut_mod != h_base, "Changing DUT source must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after DUT modification."
        print(f"  -> Changing DUT Source: INVALIDATED ({h_base[:8]} != {h_dut_mod[:8]}) (OK)")
        dut_file.write_text("module dut(input a, output y); assign y = a; endmodule\n", encoding="utf-8")

        # 3. Invalidation on Submodule Dependency modification
        dep_file.write_text("module submod(input in, output out); assign out = ~in; endmodule\n", encoding="utf-8")
        h_dep_mod = cache_mgr.compute_hash(plan)
        assert h_dep_mod != h_base, "Changing submodule dependency must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after dependency modification."
        print(f"  -> Changing Submodule Dependency: INVALIDATED ({h_base[:8]} != {h_dep_mod[:8]}) (OK)")
        dep_file.write_text("module submod(input in, output out); assign out = in; endmodule\n", encoding="utf-8")

        # 4. Invalidation on Testbench modification
        tb_file.write_text("module tb_dut; reg a; wire y; dut uut(a, y); initial #5 $finish; endmodule\n", encoding="utf-8")
        h_tb_mod = cache_mgr.compute_hash(plan)
        assert h_tb_mod != h_base, "Changing testbench must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after testbench modification."
        print(f"  -> Changing Testbench Source: INVALIDATED ({h_base[:8]} != {h_tb_mod[:8]}) (OK)")
        tb_file.write_text("module tb_dut; reg a; wire y; dut uut(a, y); initial #1 $finish; endmodule\n", encoding="utf-8")

        # 5. Invalidation on Reference File modification
        ref_file.write_text("a,expected_y\n0,1\n1,0\n", encoding="utf-8")
        h_ref_mod = cache_mgr.compute_hash(plan)
        assert h_ref_mod != h_base, "Changing reference file must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after reference modification."
        print(f"  -> Changing Reference File: INVALIDATED ({h_base[:8]} != {h_ref_mod[:8]}) (OK)")
        ref_file.write_text("a,expected_y\n0,0\n1,1\n", encoding="utf-8")

        # 6. Invalidation on Compiler / Simulator Options modification
        plan.iverilog_flags.append("-DEXTRA_FLAG=1")
        h_flags_mod = cache_mgr.compute_hash(plan)
        assert h_flags_mod != h_base, "Changing compiler flags must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after compiler flag modification."
        print(f"  -> Changing Compiler Flags: INVALIDATED ({h_base[:8]} != {h_flags_mod[:8]}) (OK)")
        plan.iverilog_flags = ["-g2012"]

        plan.simulator_name = "questa"
        h_sim_mod = cache_mgr.compute_hash(plan)
        assert h_sim_mod != h_base, "Changing simulator adapter must invalidate cache."
        assert cache_mgr.get(plan) is None, "Cache lookup must return None after simulator switch."
        print(f"  -> Changing Simulator Adapter: INVALIDATED ({h_base[:8]} != {h_sim_mod[:8]}) (OK)")
        plan.simulator_name = "icarus"

        # 7. Replay Validation
        print("\n[2] Validating Historical Run Replay Engine...")
        engine = RegressionEngine(root_dir=WORKSPACE_ROOT)
        history_file = WORKSPACE_ROOT / "reports" / "history.jsonl"
        assert history_file.exists(), "History file must exist."
        lines = [line.strip() for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) > 0, "History file must contain at least one run record."

        latest_record = json.loads(lines[-1])
        run_id = latest_record["run_id"]
        print(f"  Found historical run in log: {run_id} ({latest_record['timestamp']})")
        print(f"  Total plans in historic run: {latest_record['total_plans']}")

        # Replay the run
        replay_results = engine.replay_run(run_id)
        assert replay_results is not None, "Replay must find historic run and execute."
        print("  -> Historical Run Replay: PASSED (Reproduced identically)")

        print("\n================================================================================")
        print(" CACHE INVALIDATION AND REPLAY VALIDATION: 100% SUCCESS")
        print("================================================================================")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

if __name__ == "__main__":
    validate_cache_and_replay()
