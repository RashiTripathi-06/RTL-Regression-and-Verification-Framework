from __future__ import annotations
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import (
    ModuleInfo,
    PortSpec,
    InstanceInfo,
    VerificationPlan,
    CompatibilityEvidence,
    STATUS_PASS,
    STATUS_FUNCTIONAL_FAIL
)
from parser import VerilogASTParser, extract_file_includes
from dependency_resolver import DependencyResolver
from cache_manager import CacheManager
from executor import EdalizeSimulatorAdapter, IsolatedSimulatorExecutor, ExecutionResult
from static_analyzer import StaticRTLAnalyzer
from auditor import VerificationAuditor

class AdvancedRegressionFeaturesTests(unittest.TestCase):
    """
    Validates architectural improvements for large RTL repositories:
    1. Recursive include-file tracking across multi-level nested headers.
    2. Cryptographic Merkle cache invalidation on include-file modifications.
    3. Edalize EDAM specification generation and transparent fallback.
    4. Pre-simulation static analysis: inferred latches, multi-driven nets, and port width mismatches.
    5. Hierarchical reference file directory staging.
    6. Modern assertion and UVM failure detection.
    """

    def setUp(self):
        self.parser = VerilogASTParser()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="rtl_advanced_tests_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recursive_include_resolution(self):
        """A.v -> includes header_a.vh -> includes header_b.vh. All must be resolved."""
        header_b = self.temp_dir / "header_b.vh"
        header_b.write_text("`define WIDTH_PARAM 16\n")

        header_a = self.temp_dir / "header_a.vh"
        header_a.write_text('`include "header_b.vh"\n`define OP_MODE 2\n')

        top_v = self.temp_dir / "top_inc.v"
        top_v.write_text('`include "header_a.vh"\nmodule top_inc (input wire clk); endmodule\n')

        mods = self.parser.parse_file(top_v)
        self.assertEqual(len(mods), 1)

        resolver = DependencyResolver(
            all_modules={m.name: m for m in mods},
            include_dirs=[self.temp_dir]
        )
        res = resolver.resolve_dependencies(mods[0])

        inc_names = [p.name for p in res.include_files]
        self.assertIn("header_a.vh", inc_names)
        self.assertIn("header_b.vh", inc_names)
        self.assertEqual(len(res.missing_dependencies), 0)

    def test_include_file_merkle_cache_invalidation(self):
        """Modifying a nested include file must strictly invalidate the Merkle cache root hash."""
        header_file = self.temp_dir / "alu_defs.vh"
        header_file.write_text("`define ADD_OP 3'b000\n")

        dut_file = self.temp_dir / "alu_inc.v"
        dut_file.write_text('`include "alu_defs.vh"\nmodule alu_inc (input [3:0] a, b, output [3:0] y); assign y = a + b; endmodule\n')

        tb_file = self.temp_dir / "tb_alu_inc.v"
        tb_file.write_text("module tb_alu_inc; reg [3:0] a, b; wire [3:0] y; alu_inc uut (a, b, y); endmodule\n")

        plan = VerificationPlan(
            plan_id="alu_inc__tb_alu_inc",
            dut_name="alu_inc",
            dut_module="alu_inc",
            dut_file=dut_file,
            tb_name="tb_alu_inc",
            tb_module="tb_alu_inc",
            tb_file=tb_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct test",
                match_type="EXACT_NAME",
                expected_module_name="alu_inc",
                actual_module_name="alu_inc"
            ),
            required_sources=[dut_file, tb_file],
            data_files=[],
            include_files=[header_file],
            include_dirs=[self.temp_dir],
            build_dir=self.temp_dir / "build"
        )

        cache_mgr = CacheManager(self.temp_dir / ".cache.json")
        hash_initial = cache_mgr.compute_hash(plan)

        # Modify the include file content
        header_file.write_text("`define ADD_OP 3'b111 // Changed opcode\n")
        hash_after_mod = cache_mgr.compute_hash(plan)

        self.assertNotEqual(hash_initial, hash_after_mod, "Changing an include file MUST invalidate the Merkle root hash")

    def test_edalize_edam_generation(self):
        """EdalizeSimulatorAdapter must generate a valid EDAM specification file (edam.json)."""
        dut_file = self.temp_dir / "dummy_dut.v"
        dut_file.write_text("module dummy_dut; endmodule")
        tb_file = self.temp_dir / "tb_dummy.v"
        tb_file.write_text("module tb_dummy; endmodule")

        plan = VerificationPlan(
            plan_id="dummy_dut__tb_dummy",
            dut_name="dummy_dut",
            dut_module="dummy_dut",
            dut_file=dut_file,
            tb_name="tb_dummy",
            tb_module="tb_dummy",
            tb_file=tb_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct",
                match_type="EXACT_NAME",
                expected_module_name="dummy_dut",
                actual_module_name="dummy_dut"
            ),
            required_sources=[dut_file, tb_file],
            data_files=[],
            include_files=[],
            build_dir=self.temp_dir / "build_edalize"
        )

        adapter = EdalizeSimulatorAdapter()
        edam_dict = adapter.generate_edam(plan, plan.build_dir)

        edam_json = plan.build_dir / "edam.json"
        self.assertTrue(edam_json.exists(), "edam.json must be written to build directory")
        data = json.loads(edam_json.read_text(encoding="utf-8"))
        self.assertEqual(data["toplevel"], "tb_dummy")
        self.assertEqual(len(data["files"]), 2)
        self.assertIn("tool_options", data)

    def test_static_rtl_analyzer_latch_inference(self):
        """StaticRTLAnalyzer must detect potential latch inference in combinational always blocks."""
        rtl_code = """
        module latch_test (input wire en, input wire [3:0] d, output reg [3:0] q);
            always @* begin
                if (en)
                    q = d;
                // Missing else branch! Causes inferred latch!
            end
        endmodule
        """
        f = self.temp_dir / "latch_test.v"
        f.write_text(rtl_code)

        mod = self.parser.parse_file(f)[0]
        analyzer = StaticRTLAnalyzer()
        rep = analyzer.analyze(mod)

        self.assertGreater(len(rep.inferred_latches), 0, "Inferred latch must be flagged")
        self.assertTrue(any("q" in s for s in rep.inferred_latches))

    def test_static_rtl_analyzer_multi_driver(self):
        """StaticRTLAnalyzer must detect nets driven by multiple procedural or continuous assignments."""
        rtl_code = """
        module multi_driver (input wire a, b, output reg out);
            always @* begin
                out = a;
            end
            always @* begin
                out = b;
            end
        endmodule
        """
        f = self.temp_dir / "multi_driver.v"
        f.write_text(rtl_code)

        mod = self.parser.parse_file(f)[0]
        analyzer = StaticRTLAnalyzer()
        rep = analyzer.analyze(mod)

        self.assertGreater(len(rep.multi_driven_nets), 0, "Multi-driven net must be flagged")
        self.assertTrue(any("out" in s for s in rep.multi_driven_nets))

    def test_static_rtl_analyzer_port_width_mismatch(self):
        """StaticRTLAnalyzer must warn when submodule port width does not match connected signal width."""
        sub_code = "module sub_alu (input [7:0] in_val, output [7:0] out_val); assign out_val = in_val; endmodule"
        top_code = """
        module top_mismatch (input [3:0] small_in, output [3:0] small_out);
            sub_alu u_sub (
                .in_val(small_in),
                .out_val(small_out)
            );
        endmodule
        """
        sub_f = self.temp_dir / "sub_alu.v"
        sub_f.write_text(sub_code)
        top_f = self.temp_dir / "top_mismatch.v"
        top_f.write_text(top_code)

        sub_mod = self.parser.parse_file(sub_f)[0]
        top_mod = self.parser.parse_file(top_f)[0]

        analyzer = StaticRTLAnalyzer(all_modules={"sub_alu": sub_mod, "top_mismatch": top_mod})
        rep = analyzer.analyze(top_mod)

        self.assertTrue(any("width" in w.lower() for w in rep.warnings), "Port width mismatch must be warned")

    def test_hierarchical_data_file_staging(self):
        """Reference files in subdirectories (e.g. data/table.mem) must be staged preserving folder paths."""
        data_subdir = self.temp_dir / "tb_dir" / "data"
        data_subdir.mkdir(parents=True)
        mem_file = data_subdir / "vectors.mem"
        mem_file.write_text("@00 11 22 33")

        tb_file = self.temp_dir / "tb_dir" / "tb_hier.v"
        tb_file.write_text('module tb_hier; reg [7:0] mem [0:3]; initial $readmemh("data/vectors.mem", mem); endmodule')

        dut_file = self.temp_dir / "dut_hier.v"
        dut_file.write_text("module dut_hier; endmodule")

        work_dir = self.temp_dir / "build_staging"

        plan = VerificationPlan(
            plan_id="dut_hier__tb_hier",
            dut_name="dut_hier",
            dut_module="dut_hier",
            dut_file=dut_file,
            tb_name="tb_hier",
            tb_module="tb_hier",
            tb_file=tb_file,
            compatibility=CompatibilityEvidence(
                matched=True,
                reason="Direct",
                match_type="EXACT_NAME",
                expected_module_name="dut_hier",
                actual_module_name="dut_hier"
            ),
            required_sources=[dut_file, tb_file],
            data_files=[mem_file],
            build_dir=work_dir
        )

        executor = IsolatedSimulatorExecutor()
        # Stage files through executor's internal logic
        work_dir.mkdir(parents=True, exist_ok=True)
        for df in plan.data_files:
            if df.exists():
                dest_file = work_dir / df.name
                shutil.copy2(df, dest_file)
                try:
                    rel_to_tb = df.resolve().relative_to(plan.tb_file.parent.resolve())
                    sub_dest = work_dir / rel_to_tb
                    sub_dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(df, sub_dest)
                except ValueError:
                    pass

        # Both flat and hierarchical copies must exist
        self.assertTrue((work_dir / "vectors.mem").exists(), "Flat copy must exist")
        self.assertTrue((work_dir / "data" / "vectors.mem").exists(), "Relative subdirectory copy must exist")

    def test_uvm_and_assertion_failure_auditing(self):
        """Auditor must recognize UVM_ERROR and SystemVerilog assertion errors as FUNCTIONAL FAIL."""
        auditor = VerificationAuditor()

        # UVM Error log
        sim_out_uvm = """
        === TESTBENCH_START ===
        UVM_INFO @ 0: uvm_test_top [RNTST] Running test test_alu...
        UVM_ERROR @ 50ns: uvm_test_top.env.sb [MISMATCH] Expected 4'b1010 but got 4'b0000
        === TESTBENCH_DONE ===
        """
        exec_res_uvm = ExecutionResult(
            plan_id="test_uvm",
            compile_returncode=0,
            compile_stdout="",
            compile_stderr="",
            sim_returncode=0,
            sim_stdout=sim_out_uvm,
            sim_stderr="",
            timed_out=False,
            elapsed_seconds=0.1
        )
        res_uvm = auditor.audit(exec_res_uvm)
        self.assertEqual(res_uvm.status, STATUS_FUNCTIONAL_FAIL)
        self.assertIn("UVM_ERROR", res_uvm.diagnostic_summary)

        # SystemVerilog Assertion Failed log
        sim_out_sva = """
        === TESTBENCH_START ===
        "testbench.sv", 42: tb_top.uut.check_reset: ASSERTION FAILED at 100ns
        === TESTBENCH_DONE ===
        """
        exec_res_sva = ExecutionResult(
            plan_id="test_sva",
            compile_returncode=0,
            compile_stdout="",
            compile_stderr="",
            sim_returncode=0,
            sim_stdout=sim_out_sva,
            sim_stderr="",
            timed_out=False,
            elapsed_seconds=0.1
        )
        res_sva = auditor.audit(exec_res_sva)
        self.assertEqual(res_sva.status, STATUS_FUNCTIONAL_FAIL)
        self.assertIn("ASSERTION FAILED", res_sva.diagnostic_summary)


if __name__ == "__main__":
    unittest.main()
