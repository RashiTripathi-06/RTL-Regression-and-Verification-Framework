"""
Independent Extraction Verification Utility
Validates that framework/ is 100% extractable and self-contained,
can be installed in an isolated environment, and can execute both
Path A and Path B on a completely external user RTL project.
"""
import os
import sys
import shutil
import subprocess
import json
from pathlib import Path

def main():
    print("=" * 80)
    print("INDEPENDENT EXTRACTION VERIFICATION")
    print("=" * 80)

    repo_root = Path(__file__).resolve().parents[2]
    temp_dir = Path(os.environ.get("TEMP", "C:/temp")) / "rtl_framework_extract_val"
    extract_dir = temp_dir / "framework_extracted"
    project_dir = temp_dir / "external_test_project"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    project_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1] Copying framework/ from {repo_root / 'framework'} to {extract_dir}")
    shutil.copytree(repo_root / "framework", extract_dir, dirs_exist_ok=True)

    forbidden = ["examples", "extensions", "tools", "docs", "reports", "designs", "tb"]
    for f in forbidden:
        assert not (extract_dir / f).exists(), f"Violation: {f} present in extracted framework!"
    print("    Strict isolation verified: zero non-framework components present.")

    install_target = temp_dir / "installed_pkg"
    pip_cmd = [sys.executable, "-m", "pip", "install", "--no-build-isolation", "--no-deps", "--target", str(install_target), str(extract_dir)]
    res = subprocess.run(pip_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Pip install failed: {res.stderr}"
    print("    Extracted framework installed into isolated target successfully.")

    # Create external project
    (project_dir / "rtl").mkdir(exist_ok=True)
    (project_dir / "tb").mkdir(exist_ok=True)
    (project_dir / "references").mkdir(exist_ok=True)

    (project_dir / "rtl" / "pipelined_alu.v").write_text("""
module pipelined_alu (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        en,
    input  wire [3:0]  a,
    input  wire [3:0]  b,
    input  wire [1:0]  op,
    output reg  [3:0]  result,
    output reg         zero
);
    wire [3:0] res_comb;
    assign res_comb = (op == 2'b00) ? (a + b) :
                      (op == 2'b01) ? (a - b) :
                      (op == 2'b10) ? (a & b) : (a | b);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 4'h0;
            zero   <= 1'b1;
        end else if (en) begin
            result <= res_comb;
            zero   <= (res_comb == 4'h0);
        end
    end
endmodule
""", encoding="utf-8")

    (project_dir / "tb" / "tb_pipelined_alu.v").write_text("""`timescale 1ns/1ps
module tb_pipelined_alu;
    reg        clk;
    reg        rst_n;
    reg        en;
    reg  [3:0] a;
    reg  [3:0] b;
    reg  [1:0] op;
    wire [3:0] result;
    wire       zero;

    pipelined_alu dut (
        .clk(clk), .rst_n(rst_n), .en(en),
        .a(a), .b(b), .op(op), .result(result), .zero(zero)
    );

    always #5 clk = ~clk;

    integer checks, passes, fails;

    task check_vector(input [3:0] in_a, input [3:0] in_b, input [1:0] in_op, input [3:0] exp_res, input exp_zero);
        begin
            @(negedge clk);
            en = 1; a = in_a; b = in_b; op = in_op;
            @(posedge clk); #1;
            checks = checks + 1;
            if (result === exp_res && zero === exp_zero) passes = passes + 1;
            else fails = fails + 1;
        end
    endtask

    initial begin
        clk = 0; rst_n = 0; en = 0; a = 0; b = 0; op = 0;
        checks = 0; passes = 0; fails = 0;
        $display("=== TESTBENCH_START ===");
        #15; rst_n = 1; #10;
        check_vector(4'd3, 4'd2, 2'b00, 4'd5, 1'b0);
        check_vector(4'd4, 4'd4, 2'b01, 4'd0, 1'b1);
        check_vector(4'hC, 4'hA, 2'b10, 4'h8, 1'b0);
        check_vector(4'h5, 4'h2, 2'b11, 4'h7, 1'b0);
        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", checks, passes, fails);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
""", encoding="utf-8")

    (project_dir / "references" / "golden_alu.csv").write_text("""en,a,b,op,expected_result,expected_zero
1,3,2,0,5,0
1,4,4,1,0,1
1,C,A,2,8,0
1,5,2,3,7,0
""", encoding="utf-8")

    config_data = {
        "project_name": "External Independent Pipelined ALU Project",
        "build_dir": "build",
        "reports_dir": "reports",
        "simulator": "icarus",
        "timeout_seconds": 10.0,
        "reference_sources": {
            "primary": {
                "name": "golden_alu",
                "path": "references/golden_alu.csv",
                "priority": 1,
                "type": "direct_io_table",
                "format": "csv",
                "radix": "hex",
                "input_mapping": {"en": "en", "a": "a", "b": "b", "op": "op"},
                "output_mapping": {"expected_result": "result", "expected_zero": "zero"},
                "timing": {
                    "mode": "sequential",
                    "clock_signal": "clk",
                    "reset_signal": "rst_n",
                    "reset_active_level": 0,
                    "reset_duration_cycles": 2,
                    "latency_cycles": 1,
                    "clock_period_ns": 10.0
                }
            }
        }
    }
    (project_dir / "config.json").write_text(json.dumps(config_data, indent=2), encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(install_target)
    run_cmd = [
        sys.executable, "-m", "rtl_framework.cli", "run",
        "--project", str(project_dir),
        "--config", str(project_dir / "config.json"),
        "--force"
    ]
    res_run = subprocess.run(run_cmd, capture_output=True, text=True, env=env)
    print(res_run.stdout)
    assert res_run.returncode == 0, f"CLI run failed with exit code {res_run.returncode}"
    assert "PASS_REFERENCE_VERIFIED" in res_run.stdout, "Missing PASS_REFERENCE_VERIFIED in output"
    assert "PASS_TESTBENCH_ONLY" in res_run.stdout, "Missing PASS_TESTBENCH_ONLY in output"
    print("[SUCCESS] Independent extraction experiment verified 100% successfully!")

if __name__ == "__main__":
    main()
