import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from rtl_framework.retriever import HTMLTableExtractor, ExternalReferenceRetriever, RetrievalResult
from rtl_framework.reference_verifier import ReferenceConfig, ReferenceDataLoader, ModuleInfo, PortSpec


class MockHTTPResponse(io.BytesIO):
    """Deterministic mock HTTP response conforming to urllib response interface."""

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


class TestExternalReferenceRetriever(unittest.TestCase):

    dynamic_content = "initial_version"

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_retriever_"))
        self.cache_dir = self.temp_dir / ".ref_cache"
        self.base_url = "http://127.0.0.1:8080"
        self.__class__.dynamic_content = "initial_version"

        # Patch urllib.request.urlopen to serve deterministic mock responses without external network dependencies
        self.patcher = patch("urllib.request.urlopen", side_effect=self._mock_urlopen)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _mock_urlopen(self, req_or_url, timeout=15.0):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else str(req_or_url)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path

        if path == "/vectors.csv":
            content = "req,grant,valid\n1,0,1\n2,1,1\n4,2,1\n8,3,1\n0,0,0\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/vectors.json":
            data = [
                {"req": "1", "grant": "0", "valid": "1"},
                {"req": "2", "grant": "1", "valid": "1"},
                {"req": "4", "grant": "2", "valid": "1"},
                {"req": "8", "grant": "3", "valid": "1"},
                {"req": "0", "grant": "0", "valid": "0"}
            ]
            content = json.dumps(data)
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "application/json"})

        elif path == "/truth_table.html":
            content = """<!DOCTYPE html>
<html>
<head><title>Priority Encoder Truth Table</title></head>
<body>
<h1>Specs</h1>
<table id="metadata_table">
  <tr><th>Key</th><th>Value</th></tr>
  <tr><td>Designer</td><td>Research Team</td></tr>
</table>
<table id="encoder_table">
  <tr>
    <th>req</th>
    <th>grant</th>
    <th>valid</th>
  </tr>
  <tr>
    <td>0</td>
    <td>0</td>
    <td>0</td>
  </tr>
  <tr>
    <td>1</td>
    <td>0</td>
    <td>1</td>
  </tr>
  <tr>
    <td>2</td>
    <td>1</td>
    <td>1</td>
  </tr>
  <tr>
    <td>4</td>
    <td>2</td>
    <td>1</td>
  </tr>
  <tr>
    <td>8</td>
    <td>3</td>
    <td>1</td>
  </tr>
</table>
</body>
</html>"""
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/html"})

        elif path == "/dynamic_table.csv":
            content = f"req,grant,valid\n1,0,{self.__class__.dynamic_content}\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/missing_column.csv":
            content = "req,grant\n1,0\n2,1\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/missing_value.csv":
            content = "req,grant,valid\n1,,1\n2,1,1\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/malformed.csv":
            content = "req,grant,valid\n1,INVALID_VAL,1\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/overflow.csv":
            content = "req,grant,valid\n20,0,1\n"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/csv"})

        elif path == "/empty_table.html":
            content = "<html><body><table id='empty'></table></body></html>"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/html"})

        elif path == "/no_table.html":
            content = "<html><body><p>No table here</p></body></html>"
            return MockHTTPResponse(content.encode("utf-8"), 200, {"Content-Type": "text/html"})

        elif path == "/error500":
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {}, None)

        else:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    def test_csv_retrieval_success(self):
        url = f"{self.base_url}/vectors.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="test_csv",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.local_file)
        self.assertTrue(res.local_file.exists())
        self.assertEqual(res.format, "csv")
        self.assertFalse(res.is_cached)
        self.assertEqual(len(res.content_hash), 64)

        # Verify content was saved accurately
        content = res.local_file.read_text(encoding="utf-8")
        self.assertIn("req,grant,valid", content)

    def test_json_retrieval_success(self):
        url = f"{self.base_url}/vectors.json"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="json",
            source_name="test_json",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.local_file)
        self.assertTrue(res.local_file.exists())
        self.assertEqual(res.format, "json")

        data = json.loads(res.local_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 5)
        self.assertEqual(data[0]["req"], "1")

    def test_html_table_extraction_by_id(self):
        url = f"{self.base_url}/truth_table.html"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="html_table",
            table_id="encoder_table",
            source_name="test_html_by_id",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        self.assertIsNotNone(res.local_file)
        self.assertEqual(res.format, "csv")

        # Verify extracted CSV contents
        lines = res.local_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines[0], "req,grant,valid")
        self.assertEqual(len(lines), 6)  # header + 5 rows

    def test_html_table_extraction_by_index(self):
        url = f"{self.base_url}/truth_table.html"
        # Index 0 is metadata_table
        res0 = ExternalReferenceRetriever.retrieve(
            url=url,
            format="html_table",
            table_index=0,
            source_name="test_html_idx0",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res0.success)
        lines0 = res0.local_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines0[0], "Key,Value")

        # Index 1 is encoder_table
        res1 = ExternalReferenceRetriever.retrieve(
            url=url,
            format="html_table",
            table_index=1,
            source_name="test_html_idx1",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res1.success)
        lines1 = res1.local_file.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(lines1[0], "req,grant,valid")

    def test_html_table_id_not_found(self):
        url = f"{self.base_url}/truth_table.html"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="html_table",
            table_id="nonexistent_table_id",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res.success)
        self.assertIn("not found", res.error_message.lower())

    def test_html_table_empty_or_missing(self):
        url_empty = f"{self.base_url}/empty_table.html"
        res_empty = ExternalReferenceRetriever.retrieve(
            url=url_empty,
            format="html_table",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res_empty.success)

        url_no = f"{self.base_url}/no_table.html"
        res_no = ExternalReferenceRetriever.retrieve(
            url=url_no,
            format="html_table",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res_no.success)
        self.assertIn("no <table>", res_no.error_message.lower())

    def test_invalid_url_scheme(self):
        res = ExternalReferenceRetriever.retrieve(
            url="ftp://example.com/data.csv",
            format="csv",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res.success)
        self.assertIn("Unsupported URL scheme", res.error_message)

    def test_http_404_error(self):
        url = f"{self.base_url}/nonexistent.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res.success)
        self.assertIn("404", res.error_message)

    def test_http_500_error(self):
        url = f"{self.base_url}/error500"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            cache_dir=self.cache_dir
        )
        self.assertFalse(res.success)
        self.assertIn("500", res.error_message)

    def test_offline_mode_with_cache(self):
        url = f"{self.base_url}/vectors.csv"
        # First retrieve online
        res_online = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="cached_source",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res_online.success)
        self.assertFalse(res_online.is_cached)

        # Now retrieve offline
        res_offline = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="cached_source",
            cache_dir=self.cache_dir,
            offline=True
        )
        self.assertTrue(res_offline.success)
        self.assertTrue(res_offline.is_cached)
        self.assertEqual(res_online.content_hash, res_offline.content_hash)

    def test_offline_mode_missing_cache(self):
        url = f"{self.base_url}/vectors.csv"
        res_offline = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="never_cached",
            cache_dir=self.cache_dir,
            offline=True
        )
        self.assertFalse(res_offline.success)
        self.assertIn("Offline mode requested", res_offline.error_message)

    def test_content_change_detection(self):
        url = f"{self.base_url}/dynamic_table.csv"
        self.__class__.dynamic_content = "v1"

        res1 = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="dyn_source",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res1.success)
        self.assertFalse(res1.content_changed)

        # Change remote content
        self.__class__.dynamic_content = "v2"

        res2 = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="dyn_source",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res2.success)
        self.assertTrue(res2.content_changed)
        self.assertNotEqual(res1.content_hash, res2.content_hash)

    def test_file_url_scheme(self):
        sample_file = self.temp_dir / "local_sample.csv"
        sample_file.write_text("req,grant,valid\n1,0,1\n", encoding="utf-8")
        file_url = sample_file.as_uri()

        res = ExternalReferenceRetriever.retrieve(
            url=file_url,
            format="csv",
            source_name="local_file_test",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        self.assertEqual(res.local_file.read_text(encoding="utf-8"), "req,grant,valid\n1,0,1\n")

    def test_reference_validation_missing_columns(self):
        url = f"{self.base_url}/missing_column.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="missing_col",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        ref_cfg = ReferenceConfig(
            file=res.local_file,
            format="csv",
            radix="hex",
            input_mapping={"req": "req"},
            output_mapping={"grant": "grant", "valid": "valid"}  # 'valid' is missing from CSV!
        )
        with self.assertRaises(ValueError) as ctx:
            ReferenceDataLoader.load(ref_cfg, strict=True)
        self.assertIn("missing configured output column 'valid'", str(ctx.exception).lower())

    def test_reference_validation_missing_value(self):
        url = f"{self.base_url}/missing_value.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="missing_val",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        ref_cfg = ReferenceConfig(
            file=res.local_file,
            format="csv",
            radix="hex",
            input_mapping={"req": "req"},
            output_mapping={"grant": "grant", "valid": "valid"}
        )
        with self.assertRaises(ValueError) as ctx:
            ReferenceDataLoader.load(ref_cfg, strict=True)
        self.assertIn("missing configured expected-output field", str(ctx.exception).lower())

    def test_reference_validation_malformed_numeric_value(self):
        url = f"{self.base_url}/malformed.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="malformed",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        ref_cfg = ReferenceConfig(
            file=res.local_file,
            format="csv",
            radix="hex",
            input_mapping={"req": "req"},
            output_mapping={"grant": "grant", "valid": "valid"}
        )
        with self.assertRaises(ValueError) as ctx:
            ReferenceDataLoader.load(ref_cfg, strict=True)
        self.assertIn("invalid or non-numeric value", str(ctx.exception).lower())

    def test_reference_validation_bitwidth_overflow(self):
        url = f"{self.base_url}/overflow.csv"
        res = ExternalReferenceRetriever.retrieve(
            url=url,
            format="csv",
            source_name="overflow",
            cache_dir=self.cache_dir
        )
        self.assertTrue(res.success)
        # DUT with 4-bit req port (max allowed value is 15 = 0xF)
        dut = ModuleInfo(
            name="test_dut",
            file_path=Path("dummy.v"),
            ports={
                "req": PortSpec(name="req", direction="input", width=4),
                "grant": PortSpec(name="grant", direction="output", width=2),
                "valid": PortSpec(name="valid", direction="output", width=1)
            }
        )
        ref_cfg = ReferenceConfig(
            file=res.local_file,
            format="csv",
            radix="dec",
            input_mapping={"req": "req"},
            output_mapping={"grant": "grant", "valid": "valid"}
        )
        with self.assertRaises(ValueError) as ctx:
            ReferenceDataLoader.load(ref_cfg, dut=dut, strict=True)
        self.assertIn("exceeds configured port width of 4 bits", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
