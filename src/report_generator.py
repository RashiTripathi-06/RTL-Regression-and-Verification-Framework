from __future__ import annotations
import csv
import datetime
import hashlib
import html
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple
from models import (
    TestResult,
    ALL_STATUSES,
    STATUS_PASS,
    STATUS_PASS_REFERENCE_VERIFIED,
    STATUS_PASS_TESTBENCH_ONLY,
    STATUS_FUNCTIONAL_FAIL,
    STATUS_COMPILE_ERROR,
    STATUS_SIMULATION_ERROR,
    STATUS_TIMEOUT,
    STATUS_INCOMPLETE,
    STATUS_INVALID_RESULTS,
    STATUS_INTERFACE_ERROR,
    STATUS_NO_MATCH,
    STATUS_AMBIGUOUS_MATCH,
    STATUS_MISSING_REFERENCE,
    STATUS_NOT_VERIFIED,
    STATUS_LICENSE_ERROR
)

class ReportGenerator:
    """Generates CSV, JSON, persistent JSONL history, and standalone HTML dashboards."""

    def __init__(self, reports_dir: Path, history_file: Path):
        self.reports_dir = reports_dir.resolve()
        self.history_file = history_file.resolve()
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

    def generate(self, results: List[TestResult], project_name: str = "Automated RTL Regression Suite") -> Tuple[Path, Path, Path]:
        csv_path = self.reports_dir / "regression_summary.csv"
        json_path = self.reports_dir / "regression_summary.json"
        html_path = self.reports_dir / "regression_report.html"

        # 1. Consolidated CSV
        fieldnames = [
            "plan_id", "dut_name", "tb_name", "status", "confidence", "cached",
            "passed_vectors", "total_vectors", "failed_vectors",
            "elapsed_seconds", "wrapper_used",
            "execution_status", "functional_status", "audit_status",
            "simulator_name", "diagnostic_summary", "log_file", "content_hash", "timestamp"
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                row = asdict(r)
                row.pop("failing_vectors", None)
                writer.writerow(row)

        # 2. Machine-readable JSON summary
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        run_id = f"run_{now_dt.strftime('%Y%m%d_%H%M%S')}_{hashlib.sha256(str(time.time()).encode()).hexdigest()[:6]}"
        summary_payload = {
            "run_id": run_id,
            "project_name": project_name,
            "timestamp": now_dt.isoformat(),
            "total_plans": len(results),
            "status_counts": {
                status: sum(1 for r in results if r.status == status)
                for status in ALL_STATUSES
            },
            "results": [asdict(r) for r in results]
        }
        json_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

        # 3. Persistent JSONL history
        passed_count = (
            summary_payload["status_counts"].get(STATUS_PASS, 0) +
            summary_payload["status_counts"].get(STATUS_PASS_REFERENCE_VERIFIED, 0) +
            summary_payload["status_counts"].get(STATUS_PASS_TESTBENCH_ONLY, 0)
        )
        history_record = {
            "run_id": run_id,
            "timestamp": summary_payload["timestamp"],
            "total_plans": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "results": [asdict(r) for r in results]
        }
        history_line = json.dumps(history_record) + "\n"
        with self.history_file.open("a", encoding="utf-8") as hf:
            hf.write(history_line)

        alt_history = self.reports_dir / "history.jsonl"
        if alt_history.resolve() != self.history_file.resolve():
            with alt_history.open("a", encoding="utf-8") as ahf:
                ahf.write(history_line)

        # Also write alias filenames
        shutil.copy2(json_path, self.reports_dir / "summary.json")
        shutil.copy2(csv_path, self.reports_dir / "summary.csv")

        # 4. Standalone HTML dashboard
        self._generate_html(html_path, results, project_name, summary_payload["status_counts"])
        shutil.copy2(html_path, self.reports_dir / "report.html")

        return csv_path, json_path, html_path

    def _generate_html(self, html_path: Path, results: List[TestResult], project_name: str, counts: Dict[str, int]):
        total_runs = len(results)
        passed_runs = counts.get(STATUS_PASS, 0) + counts.get(STATUS_PASS_REFERENCE_VERIFIED, 0) + counts.get(STATUS_PASS_TESTBENCH_ONLY, 0)
        failed_runs = total_runs - passed_runs

        rows_html = []
        for r in results:
            # Color mapping
            if r.status in (STATUS_PASS, STATUS_PASS_REFERENCE_VERIFIED):
                badge_bg = "#10b981"
            elif r.status == STATUS_PASS_TESTBENCH_ONLY:
                badge_bg = "#059669"
            elif r.status == STATUS_LICENSE_ERROR:
                badge_bg = "#dc2626"
            elif r.status == STATUS_FUNCTIONAL_FAIL:
                badge_bg = "#ef4444"
            elif r.status == STATUS_COMPILE_ERROR:
                badge_bg = "#8b5cf6"
            elif r.status == STATUS_INTERFACE_ERROR:
                badge_bg = "#7c3aed"
            elif r.status == STATUS_SIMULATION_ERROR:
                badge_bg = "#f43f5e"
            elif r.status in (STATUS_TIMEOUT, STATUS_INCOMPLETE):
                badge_bg = "#f59e0b"
            elif r.status == STATUS_INVALID_RESULTS:
                badge_bg = "#ec4899"
            elif r.status == STATUS_AMBIGUOUS_MATCH:
                badge_bg = "#6366f1"
            elif r.status == STATUS_MISSING_REFERENCE:
                badge_bg = "#f97316"
            elif r.status == STATUS_NOT_VERIFIED:
                badge_bg = "#64748b"
            else:
                badge_bg = "#6b7280"

            mismatch_section = ""
            if r.failing_vectors:
                mm_rows = []
                for v in r.failing_vectors[:15]:
                    if "inputs" in v and "actual_outputs" in v and "expected_outputs" in v:
                        in_str = ", ".join(f"{k}={val}" for k, val in v["inputs"].items())
                        act_str = ", ".join(f"{k}={val}" for k, val in v["actual_outputs"].items())
                        exp_str = ", ".join(f"{k}={val}" for k, val in v["expected_outputs"].items())
                        mm_rows.append(
                            f"<tr><td>{v.get('index', '-')}</td><td>{html.escape(in_str)}</td>"
                            f"<td><strong>{html.escape(act_str)}</strong></td>"
                            f"<td>{html.escape(exp_str)}</td></tr>"
                        )
                    elif "raw" in v:
                        mm_rows.append(f"<tr><td colspan='4'><code>{html.escape(str(v['raw']))}</code></td></tr>")
                mismatch_section = f"""
                <details style="margin-top: 6px; font-size: 0.82rem;">
                  <summary style="cursor: pointer; color: #ef4444; font-weight: 600;">View Failing Vectors ({len(r.failing_vectors)})</summary>
                  <table class="subtable">
                    <thead><tr><th>Index</th><th>Inputs</th><th>Actual Output</th><th>Expected Output</th></tr></thead>
                    <tbody>{''.join(mm_rows)}</tbody>
                  </table>
                </details>
                """

            static_section = ""
            if getattr(r, "static_analysis", None):
                sa = r.static_analysis
                sa_warnings = sa.get("warnings", [])
                if sa_warnings:
                    sa_list = "".join(f"<li>{html.escape(w)}</li>" for w in sa_warnings[:8])
                    static_section = f"""
                    <details style="margin-top: 4px; font-size: 0.80rem;">
                      <summary style="cursor: pointer; color: #f59e0b; font-weight: 500;">Static Lint Warnings ({len(sa_warnings)})</summary>
                      <ul style="margin: 4px 0 0 16px; padding: 0; color: #cbd5e1;">{sa_list}</ul>
                    </details>
                    """

            cache_badge = '<span class="badge" style="background:#0284c7;">CACHE HIT</span>' if r.cached else '<span class="badge" style="background:#475569;">RUN</span>'
            wrap_badge = '<span class="badge" style="background:#d97706;">WRAPPER</span>' if r.wrapper_used else '<span class="badge" style="background:#334155;">DIRECT</span>'

            rows_html.append(f"""
            <tr>
              <td><strong>{html.escape(r.dut_name)}</strong></td>
              <td><code>{html.escape(r.tb_name)}</code></td>
              <td><span class="badge" style="background:{badge_bg};">{html.escape(r.status)}</span></td>
              <td><span class="badge" style="background:#1e293b;">{html.escape(r.confidence)}</span></td>
              <td>{cache_badge}</td>
              <td>{wrap_badge}</td>
              <td>{r.passed_vectors} / {r.total_vectors}</td>
              <td>{r.elapsed_seconds:.3f}s</td>
              <td>
                <div class="diag-text">{html.escape(r.diagnostic_summary)}</div>
                {mismatch_section}
                {static_section}
              </td>
            </tr>
            """)

        stat_cards = []
        for st in ALL_STATUSES:
            cnt = counts.get(st, 0)
            if cnt > 0:
                stat_cards.append(f"""
                <div class="stat-card">
                  <div class="stat-label">{html.escape(st)}</div>
                  <div class="stat-value">{cnt}</div>
                </div>
                """)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{html.escape(project_name)} - Regression Dashboard</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      margin: 0; padding: 24px; background: #0f172a; color: #f8fafc;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
    .subtitle {{ color: #94a3b8; font-size: 0.9rem; margin-bottom: 24px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .stat-card {{ background: #1e293b; padding: 12px 16px; border-radius: 8px; border: 1px solid #334155; }}
    .stat-label {{ font-size: 0.72rem; text-transform: uppercase; color: #94a3b8; font-weight: 600; letter-spacing: 0.05em; }}
    .stat-value {{ font-size: 1.5rem; font-weight: 700; margin-top: 4px; color: #f8fafc; }}
    table.main-table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; border: 1px solid #334155; }}
    th, td {{ padding: 10px 14px; text-align: left; font-size: 0.88rem; border-bottom: 1px solid #334155; }}
    th {{ background: #0f172a; color: #cbd5e1; font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }}
    tr:hover {{ background: #24324d; }}
    .badge {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.72rem; font-weight: 700; color: #fff; text-shadow: 0 1px 1px rgba(0,0,0,0.3); }}
    .diag-text {{ color: #cbd5e1; max-width: 450px; word-break: break-word; }}
    table.subtable {{ width: 100%; border-collapse: collapse; margin-top: 6px; background: #0f172a; border-radius: 4px; }}
    table.subtable th, table.subtable td {{ padding: 4px 8px; font-size: 0.75rem; border: 1px solid #334155; }}
    table.subtable th {{ background: #182234; color: #94a3b8; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{html.escape(project_name)}</h1>
    <div class="subtitle">Generated on {now_str} • Industrial Zero-Touch RTL Regression Framework</div>
    
    <div class="stats-grid">
      <div class="stat-card" style="border-left: 4px solid #10b981;">
        <div class="stat-label">Total Plans</div>
        <div class="stat-value">{total_runs}</div>
      </div>
      <div class="stat-card" style="border-left: 4px solid #10b981;">
        <div class="stat-label">Passed</div>
        <div class="stat-value">{passed_runs}</div>
      </div>
      <div class="stat-card" style="border-left: 4px solid #ef4444;">
        <div class="stat-label">Non-Pass / Errs</div>
        <div class="stat-value">{failed_runs}</div>
      </div>
      {''.join(stat_cards)}
    </div>

    <table class="main-table">
      <thead>
        <tr>
          <th>DUT Module</th>
          <th>Testbench</th>
          <th>Status</th>
          <th>Confidence</th>
          <th>Cache</th>
          <th>Adapter</th>
          <th>Vectors</th>
          <th>Time</th>
          <th>Diagnostics & Failing Vectors</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
  </div>
</body>
</html>"""
        html_path.write_text(doc, encoding="utf-8")
