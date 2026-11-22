import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from rtl_framework.engine import RegressionEngine
from rtl_framework.executor import IcarusSimulatorAdapter
from rtl_framework.models import (
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_REFERENCE_UNAVAILABLE,
    STATUS_FUNCTIONAL_FAIL
)


class MockHTTPResponse(io.BytesIO):
    """Mock HTTP response simulating remote reference server."""

    def __init__(self, data: bytes, status: int = 200, headers: dict = None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(data))}
        self.url = ""

    def info(self):
        return self.headers

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class TestExternalReferenceIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        adapter = IcarusSimulatorAdapter()
        if not adapter.is_available():
            raise unittest.SkipTest("Icarus Verilog is not available in environment.")

    def setUp(self):
        self.project_dir = Path(tempfile.mkdtemp(prefix="integ_ext_ref_"))
        self.rtl_dir = self.project_dir / "rtl"
        self.tb_dir = self.project_dir / "tb"
        self.rtl_dir.mkdir(parents=True)
        self.tb_dir.mkdir(parents=True)
        self.base_url = "http://127.0.0.1:8080"

        # Patch urlopen to serve deterministic mock responses without external network dependencies
        self.patcher = patch("urllib.request.urlopen", side_effect=self._mock_urlopen)
        self.patcher.start()

        # 1. Write Priority Encoder DUT
        (self.rtl_dir / "priority_encoder_4bit.v").write_text("""
module priority_encoder_4bit (
    input  wire [3:0] req,
    output reg  [1:0] grant,
    output reg        valid
);
    always @(*) begin
        if (req[3]) begin
            grant = 2'b11;
            valid = 1'b1;
        end else if (req[2]) begin
            grant = 2'b10;
            valid = 1'b1;
        end else if (req[1]) begin
            grant = 2'b01;
            valid = 1'b1;
        end else if (req[0]) begin
            grant = 2'b00;
            valid = 1'b1;
        end else begin
            grant = 2'b00;
            valid = 1'b0;
        end
    end
endmodule
""", encoding="utf-8")

        # 2. Write Standard Self-Checking Testbench with auditor sentinels
        (self.tb_dir / "tb_priority_encoder.v").write_text("""
`timescale 1ns/1ps
module tb_priority_encoder;
    reg  [3:0] req;
    wire [1:0] grant;
    wire       valid;

    integer pass_count;
    integer fail_count;

    priority_encoder_4bit uut (
        .req(req),
        .grant(grant),
        .valid(valid)
    );

    initial begin
        $display("=== TESTBENCH_START ===");
        pass_count = 0;
        fail_count = 0;

        req = 4'b0000; #10;
        if (valid !== 1'b0) begin
            $display("[FAIL] req=0 valid should be 0");
            fail_count = fail_count + 1;
        end else begin
            $display("[PASS] req=0 valid is 0");
            pass_count = pass_count + 1;
        end

        req = 4'b0001; #10;
        if (valid !== 1'b1 || grant !== 2'b00) begin
            $display("[FAIL] req=1 fail");
            fail_count = fail_count + 1;
        end else begin
            $display("[PASS] req=1 pass");
            pass_count = pass_count + 1;
        end

        $display("=== TESTBENCH_SUMMARY: total=%0d pass=%0d fail=%0d ===", pass_count + fail_count, pass_count, fail_count);
        $display("=== TESTBENCH_DONE ===");
        $finish;
    end
endmodule
""", encoding="utf-8")

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _mock_urlopen(self, req_or_url, timeout=15.0):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path

        if path == "/encoder_truth_table.html":
            content = """<!DOCTYPE html>
<html>
<head><title>Priority Encoder</title></head>
<body>
<table id="enc_truth_table">
  <tr><th>req</th><th>grant</th><th>valid</th></tr>
  <tr><td>0</td><td>0</td><td>0</td></tr>
  <tr><td>1</td><td>0</td><td>1</td></tr>
  <tr><td>2</td><td>1</td><td>1</td></tr>
  <tr><td>4</td><td>2</td><td>1</td></tr>
  <tr><td>8</td><td>3</td><td>1</td></tr>
  <tr><td>F</td><td>3</td><td>1</td></tr>
  <tr><td>7</td><td>2</td><td>1</td></tr>
</table>
</body>
</html>"""
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/html"})

        elif path == "/buggy_table.csv":
            # Intentional mismatch: req=8 -> grant=0 instead of 3
            content = "req,grant,valid\n1,0,1\n2,1,1\n4,2,1\n8,0,1\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    def test_end_to_end_html_table_path_b_success(self):
        table_url = f"{self.base_url}/encoder_truth_table.html"
        config = {
            "project_name": "encoder_integration_test",
            "simulator": "icarus",
            "reference_sources": {
                "primary": {
                    "priority": 1,
                    "type": "direct_io_table",
                    "url": table_url,
                    "format": "html_table",
                    "table_id": "enc_truth_table",
                    "radix": "hex",
                    "input_mapping": {"req": "req"},
                    "output_mapping": {"grant": "grant", "valid": "valid"}
                }
            }
        }
        (self.project_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        engine = RegressionEngine(root_dir=self.project_dir)
        results = engine.run_regression(force_rerun=True)

        # Path A should pass
        path_a_results = [r for r in results if r.tb_name == "tb_priority_encoder"]
        self.assertEqual(len(path_a_results), 1)
        self.assertEqual(path_a_results[0].status, STATUS_PASS_TESTBENCH_ONLY)

        # Path B should execute against the HTML table and pass
        path_b_results = [r for r in results if r.plan_id.startswith("ref_harness__")]
        self.assertEqual(len(path_b_results), 1)
        res_b = path_b_results[0]
        self.assertEqual(res_b.status, STATUS_PASS_REFERENCE_VERIFIED)
        self.assertEqual(res_b.passed_vectors, 7)
        self.assertEqual(res_b.total_vectors, 7)

        # Verify provenance was captured
        self.assertIn("reference_provenance", res_b.__dict__)
        prov = res_b.reference_provenance
        self.assertEqual(prov.get("primary_source"), "primary")
        self.assertIn("primary_provenance", prov)
        self.assertEqual(prov["primary_provenance"].get("source_url"), table_url)
        self.assertEqual(len(prov.get("primary_hash", "")), 64)

    def test_path_b_mismatch_detection_from_external_source(self):
        csv_url = f"{self.base_url}/buggy_table.csv"
        config = {
            "project_name": "encoder_buggy_ref_test",
            "simulator": "icarus",
            "reference_sources": {
                "primary": {
                    "priority": 1,
                    "type": "direct_io_table",
                    "url": csv_url,
                    "format": "csv",
                    "radix": "hex",
                    "input_mapping": {"req": "req"},
                    "output_mapping": {"grant": "grant", "valid": "valid"}
                }
            }
        }
        (self.project_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        engine = RegressionEngine(root_dir=self.project_dir)
        results = engine.run_regression(force_rerun=True)

        path_b_results = [r for r in results if r.plan_id.startswith("ref_harness__")]
        self.assertEqual(len(path_b_results), 1)
        res_b = path_b_results[0]
        # Should detect the vector mismatch on req=8
        self.assertEqual(res_b.status, STATUS_FUNCTIONAL_FAIL)
        self.assertEqual(res_b.failed_vectors, 1)
        self.assertEqual(res_b.passed_vectors, 3)

    def test_unavailable_external_url_diagnostic(self):
        missing_url = f"{self.base_url}/nonexistent_table.csv"
        config = {
            "project_name": "encoder_missing_url_test",
            "simulator": "icarus",
            "reference_sources": {
                "primary": {
                    "priority": 1,
                    "type": "direct_io_table",
                    "url": missing_url,
                    "format": "csv",
                    "radix": "hex",
                    "input_mapping": {"req": "req"},
                    "output_mapping": {"grant": "grant", "valid": "valid"}
                }
            }
        }
        (self.project_dir / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

        engine = RegressionEngine(root_dir=self.project_dir)
        results = engine.run_regression(force_rerun=True)

        path_b_results = [r for r in results if r.plan_id.startswith("ref_harness__")]
        self.assertEqual(len(path_b_results), 1)
        res_b = path_b_results[0]
        self.assertEqual(res_b.status, STATUS_REFERENCE_UNAVAILABLE)
        self.assertIn("404", res_b.diagnostic_summary)


if __name__ == "__main__":
    unittest.main()
