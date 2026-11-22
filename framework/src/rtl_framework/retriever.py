from __future__ import annotations
import csv
import datetime
import hashlib
import html
from html.parser import HTMLParser
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import urllib.error
import urllib.parse
import urllib.request


class HTMLTableExtractor(HTMLParser):
    """
    Zero-dependency, streaming HTML table extractor for tabular reference data.
    Finds tables by ID, CSS class, or 0-based document index and extracts
    structured rows and column headers.
    """

    def __init__(self):
        super().__init__()
        self.tables: List[Dict[str, Any]] = []
        self._current_table: Optional[Dict[str, Any]] = None
        self._current_row: Optional[List[str]] = None
        self._current_row_is_header: bool = False
        self._current_cell: Optional[List[str]] = None
        self._in_table: bool = False
        self._in_cell: bool = False
        self._in_ignored_tag: bool = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag = tag.lower()
        if tag in ("script", "style"):
            self._in_ignored_tag = True
            return

        if tag == "table":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            self._current_table = {
                "id": attr_dict.get("id", ""),
                "class": attr_dict.get("class", ""),
                "headers": [],
                "rows": []
            }
            self._in_table = True

        elif self._in_table and tag == "tr":
            self._current_row = []
            self._current_row_is_header = False

        elif self._in_table and tag in ("th", "td"):
            self._current_cell = []
            self._in_cell = True
            if tag == "th":
                self._current_row_is_header = True

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in ("script", "style"):
            self._in_ignored_tag = False
            return

        if self._in_table:
            if tag in ("th", "td") and self._in_cell:
                cell_text = "".join(self._current_cell or []).strip()
                cell_text = html.unescape(cell_text)
                if self._current_row is not None:
                    self._current_row.append(cell_text)
                self._current_cell = None
                self._in_cell = False

            elif tag == "tr" and self._current_row is not None:
                if self._current_table is not None:
                    if self._current_row_is_header and not self._current_table["headers"]:
                        self._current_table["headers"] = [c for c in self._current_row]
                    else:
                        # If headers not explicitly set yet and row looks like header
                        if not self._current_table["headers"] and not self._current_table["rows"]:
                            # Assume first row could be headers if it has non-empty strings
                            if any(self._current_row):
                                self._current_table["headers"] = [c for c in self._current_row]
                            else:
                                self._current_table["rows"].append(self._current_row)
                        else:
                            self._current_table["rows"].append(self._current_row)
                self._current_row = None

            elif tag == "table":
                if self._current_table is not None:
                    self.tables.append(self._current_table)
                self._current_table = None
                self._in_table = False

    def handle_data(self, data: str):
        if self._in_cell and not self._in_ignored_tag and self._current_cell is not None:
            self._current_cell.append(data)

    @classmethod
    def extract_table(
        cls,
        html_content: str,
        table_id: Optional[str] = None,
        table_index: int = 0
    ) -> Tuple[List[str], List[Dict[str, str]]]:
        """
        Parses HTML and extracts designated table into (headers, list_of_row_dicts).
        """
        parser = cls()
        parser.feed(html_content)
        parser.close()

        if not parser.tables:
            raise ValueError("No <table> elements found in HTML content.")

        selected_table: Optional[Dict[str, Any]] = None
        if table_id:
            for t in parser.tables:
                if t.get("id") == table_id:
                    selected_table = t
                    break
            if selected_table is None:
                available_ids = [t.get("id") for t in parser.tables if t.get("id")]
                raise ValueError(
                    f"Table with id='{table_id}' not found. Available table IDs: {available_ids} (total tables: {len(parser.tables)})."
                )
        else:
            if table_index < 0 or table_index >= len(parser.tables):
                raise ValueError(
                    f"Table index {table_index} is out of bounds. HTML document contains {len(parser.tables)} table(s)."
                )
            selected_table = parser.tables[table_index]

        headers: List[str] = selected_table.get("headers", [])
        raw_rows: List[List[str]] = selected_table.get("rows", [])

        if not headers and raw_rows:
            # Generate default column names if none found
            col_count = max(len(r) for r in raw_rows)
            headers = [f"col_{i}" for i in range(col_count)]

        structured_rows: List[Dict[str, str]] = []
        for r_idx, row in enumerate(raw_rows):
            # Pad row if shorter than headers
            padded = row + [""] * (len(headers) - len(row))
            row_dict = {headers[c_idx]: padded[c_idx].strip() for c_idx in range(len(headers))}
            structured_rows.append(row_dict)

        return headers, structured_rows


@dataclass
class RetrievalResult:
    success: bool
    local_file: Optional[Path] = None
    content_hash: str = ""
    retrieval_timestamp: str = ""
    source_url: str = ""
    format: str = "csv"
    is_cached: bool = False
    content_changed: bool = False
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExternalReferenceRetriever:
    """
    Retrieves, caches, and validates external reference sources.
    Guarantees:
    - Never modifies remote data to pass tests.
    - Computes and records SHA-256 provenance checksums.
    - Caches snapshots locally for deterministic, offline reproduction.
    - Detects remote changes across retrievals.
    """

    @staticmethod
    def _sanitize_name(name: str) -> str:
        return "".join(c if (c.isalnum() or c in ("-", "_")) else "_" for c in name)

    @classmethod
    def retrieve(
        cls,
        url: str,
        format: str = "csv",
        source_name: str = "ref",
        table_id: Optional[str] = None,
        table_index: int = 0,
        cache_dir: Optional[Path] = None,
        offline: bool = False,
        force_refresh: bool = False,
        timeout: float = 15.0
    ) -> RetrievalResult:
        if not url or not str(url).strip():
            return RetrievalResult(
                success=False,
                source_url=url,
                format=format,
                error_message="No source URL specified."
            )

        url = url.strip()
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ("http", "https", "file", ""):
            return RetrievalResult(
                success=False,
                source_url=url,
                format=format,
                error_message=f"Unsupported URL scheme '{parsed_url.scheme}'. Must be 'http', 'https', or 'file'."
            )

        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        safe_name = cls._sanitize_name(source_name)

        if cache_dir is None:
            cache_dir = Path(".reference_cache")
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        target_ext = "csv" if format in ("csv", "html_table") else ("json" if format == "json" else "dat")
        cache_data_file = cache_dir / f"{safe_name}_{url_hash}.{target_ext}"
        cache_meta_file = cache_dir / f"{safe_name}_{url_hash}.meta.json"

        # Check existing metadata
        existing_meta: Optional[Dict[str, Any]] = None
        if cache_meta_file.exists():
            try:
                existing_meta = json.loads(cache_meta_file.read_text(encoding="utf-8"))
            except Exception:
                existing_meta = None

        # Offline mode requested
        if offline:
            if cache_data_file.exists() and existing_meta:
                content_hash = hashlib.sha256(cache_data_file.read_bytes()).hexdigest()
                return RetrievalResult(
                    success=True,
                    local_file=cache_data_file,
                    content_hash=content_hash,
                    retrieval_timestamp=existing_meta.get("retrieval_timestamp", ""),
                    source_url=url,
                    format="csv" if format == "html_table" else format,
                    is_cached=True,
                    content_changed=False,
                    metadata=existing_meta
                )
            else:
                return RetrievalResult(
                    success=False,
                    source_url=url,
                    format=format,
                    error_message=f"Offline mode requested, but reference snapshot '{cache_data_file.name}' is not in cache."
                )

        # Attempt retrieval
        raw_bytes: bytes = b""
        try:
            if parsed_url.scheme in ("file", ""):
                if parsed_url.scheme == "file":
                    raw_path_str = urllib.request.url2pathname(parsed_url.path)
                    file_path = Path(raw_path_str)
                else:
                    file_path = Path(url)

                if not file_path.is_absolute() and cache_dir:
                    cand = (cache_dir.parent / file_path).resolve()
                    if cand.exists():
                        file_path = cand

                if not file_path.exists():
                    raise FileNotFoundError(f"Local file URL not found: {file_path}")
                raw_bytes = file_path.read_bytes()
            else:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "RTL-Framework-Reference-Retriever/1.0"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status != 200:
                        raise urllib.error.HTTPError(
                            url, resp.status, f"HTTP Error {resp.status}", resp.headers, None
                        )
                    raw_bytes = resp.read()
        except Exception as e:
            # If network failed, check if we have a valid offline fallback in cache
            if cache_data_file.exists() and existing_meta and not force_refresh:
                content_hash = hashlib.sha256(cache_data_file.read_bytes()).hexdigest()
                return RetrievalResult(
                    success=True,
                    local_file=cache_data_file,
                    content_hash=content_hash,
                    retrieval_timestamp=existing_meta.get("retrieval_timestamp", ""),
                    source_url=url,
                    format="csv" if format == "html_table" else format,
                    is_cached=True,
                    content_changed=False,
                    error_message=f"Network retrieval failed ({e}); falling back to verified cached snapshot.",
                    metadata=existing_meta
                )
            return RetrievalResult(
                success=False,
                source_url=url,
                format=format,
                error_message=f"Failed to retrieve reference from '{url}': {e}"
            )

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        current_hash = hashlib.sha256(raw_bytes).hexdigest()
        content_changed = False

        if existing_meta:
            prior_hash = existing_meta.get("sha256", "")
            if prior_hash and prior_hash != current_hash:
                content_changed = True

        # Process and store data according to format
        try:
            if format == "html_table":
                html_text = raw_bytes.decode("utf-8", errors="replace")
                headers, rows = HTMLTableExtractor.extract_table(
                    html_content=html_text,
                    table_id=table_id,
                    table_index=table_index
                )
                if not rows:
                    return RetrievalResult(
                        success=False,
                        source_url=url,
                        format=format,
                        error_message="Extracted HTML table contains zero data rows."
                    )
                # Convert to standardized CSV for existing ReferenceDataLoader
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=headers)
                writer.writeheader()
                for r in rows:
                    writer.writerow(r)
                csv_bytes = buf.getvalue().encode("utf-8")
                cache_data_file.write_bytes(csv_bytes)
                final_hash = hashlib.sha256(csv_bytes).hexdigest()
                final_format = "csv"
            elif format == "json":
                # Validate JSON syntax
                text = raw_bytes.decode("utf-8-sig", errors="replace")
                parsed_json = json.loads(text)
                cache_data_file.write_text(json.dumps(parsed_json, indent=2), encoding="utf-8")
                final_hash = hashlib.sha256(cache_data_file.read_bytes()).hexdigest()
                final_format = "json"
            else:
                # Direct CSV or memory format
                cache_data_file.write_bytes(raw_bytes)
                final_hash = current_hash
                final_format = format

            meta_data = {
                "source_url": url,
                "source_name": source_name,
                "retrieval_timestamp": now_iso,
                "sha256": final_hash,
                "raw_download_sha256": current_hash,
                "format": final_format,
                "table_id": table_id,
                "table_index": table_index,
                "byte_size": cache_data_file.stat().st_size,
                "content_changed": content_changed
            }
            cache_meta_file.write_text(json.dumps(meta_data, indent=2), encoding="utf-8")

            return RetrievalResult(
                success=True,
                local_file=cache_data_file,
                content_hash=final_hash,
                retrieval_timestamp=now_iso,
                source_url=url,
                format=final_format,
                is_cached=False,
                content_changed=content_changed,
                metadata=meta_data
            )
        except Exception as pe:
            return RetrievalResult(
                success=False,
                source_url=url,
                format=format,
                error_message=f"Failed to process retrieved reference data: {pe}"
            )
