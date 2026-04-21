"""
SVF Mission-Level HTML Report Generator

Generates a self-contained HTML report from a CampaignReport.
No internet connection required — all assets inline.

Usage:
    from svf.test.report import generate_html_report
    from svf.test.campaign_runner import CampaignRunner

    runner = CampaignRunner.from_yaml("campaign.yaml")
    report = runner.run()
    generate_html_report(report, Path("results/report.html"))

Implements: SVF-DEV-122
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from svf.test.campaign_runner import CampaignReport
from svf.test.procedure import Verdict


VERDICT_COLOR = {
    Verdict.PASS:         "#22c55e",
    Verdict.FAIL:         "#ef4444",
    Verdict.ERROR:        "#f97316",
    Verdict.INCONCLUSIVE: "#94a3b8",
}

VERDICT_BG = {
    Verdict.PASS:         "#f0fdf4",
    Verdict.FAIL:         "#fef2f2",
    Verdict.ERROR:        "#fff7ed",
    Verdict.INCONCLUSIVE: "#f8fafc",
}


def generate_html_report(
    report: CampaignReport,
    output_path: Path,
) -> Path:
    """
    Generate a self-contained HTML report from a CampaignReport.

    Args:
        report:      CampaignReport from CampaignRunner.run()
        output_path: Where to write the HTML file

    Returns:
        Path to the generated HTML file
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    verdict_color = VERDICT_COLOR.get(
        Verdict(report.results[0].verdict) if report.results else Verdict.INCONCLUSIVE,
        "#94a3b8"
    )
    overall_verdict = (
        Verdict.PASS if report.n_fail == 0 and report.n_error == 0
        else Verdict.FAIL
    )
    overall_color = VERDICT_COLOR[overall_verdict]

    # Build procedure rows
    procedure_rows = ""
    for r in report.results:
        v = Verdict(r.verdict)
        color  = VERDICT_COLOR[v]
        bg     = VERDICT_BG[v]
        procedure_rows += f"""
        <tr style="background:{bg}">
          <td style="font-family:monospace;font-weight:600">{r.procedure_id}</td>
          <td>{r.title}</td>
          <td style="font-family:monospace">{r.requirement}</td>
          <td style="color:{color};font-weight:700">{r.verdict}</td>
          <td style="text-align:right">{r.duration_s:.1f}s</td>
          <td style="color:#64748b;font-size:0.85em">{r.error or ''}</td>
        </tr>"""

    # Build requirement coverage
    req_rows = ""
    req_map: dict[str, list[str]] = {}
    for r in report.results:
        if r.requirement:
            if r.requirement not in req_map:
                req_map[r.requirement] = []
            req_map[r.requirement].append(
                f"{r.procedure_id} [{r.verdict}]"
            )
    for req, procs in sorted(req_map.items()):
        all_pass = all("PASS" in p for p in procs)
        color = "#22c55e" if all_pass else "#ef4444"
        req_rows += f"""
        <tr>
          <td style="font-family:monospace;font-weight:600">{req}</td>
          <td>{', '.join(procs)}</td>
          <td style="color:{color};font-weight:700">
            {'COVERED' if all_pass else 'FAILED'}
          </td>
        </tr>"""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{report.campaign_name} — SVF Campaign Report</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f8fafc; color: #1e293b; padding: 2rem; }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1.1rem; font-weight: 600; margin: 2rem 0 0.75rem;
          color: #475569; border-bottom: 1px solid #e2e8f0; padding-bottom: 0.5rem; }}
    .header {{ margin-bottom: 2rem; }}
    .meta {{ color: #64748b; font-size: 0.9rem; margin-top: 0.25rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, 1fr);
              gap: 1rem; margin-bottom: 2rem; }}
    .card {{ background: white; border-radius: 8px; padding: 1.25rem;
             box-shadow: 0 1px 3px rgba(0,0,0,0.08); }}
    .card-value {{ font-size: 2rem; font-weight: 700; }}
    .card-label {{ font-size: 0.8rem; color: #64748b; margin-top: 0.25rem; }}
    .verdict-badge {{ display: inline-block; padding: 0.25rem 0.75rem;
                      border-radius: 4px; font-weight: 700; font-size: 0.9rem; }}
    table {{ width: 100%; border-collapse: collapse; background: white;
             border-radius: 8px; overflow: hidden;
             box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 2rem; }}
    th {{ background: #1e293b; color: white; text-align: left;
          padding: 0.75rem 1rem; font-size: 0.85rem; font-weight: 600; }}
    td {{ padding: 0.75rem 1rem; border-bottom: 1px solid #f1f5f9;
          font-size: 0.9rem; }}
    tr:last-child td {{ border-bottom: none; }}
    .footer {{ color: #94a3b8; font-size: 0.8rem; margin-top: 2rem;
               text-align: center; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>{report.campaign_name}</h1>
    <div class="meta">
      Spacecraft: <strong>{report.spacecraft}</strong> &nbsp;|&nbsp;
      Generated: {timestamp} &nbsp;|&nbsp;
      Duration: {report.duration_s:.1f}s
    </div>
  </div>

  <div class="cards">
    <div class="card">
      <div class="card-value">{report.n_procedures}</div>
      <div class="card-label">Total procedures</div>
    </div>
    <div class="card">
      <div class="card-value" style="color:#22c55e">{report.n_pass}</div>
      <div class="card-label">PASS</div>
    </div>
    <div class="card">
      <div class="card-value" style="color:#ef4444">{report.n_fail}</div>
      <div class="card-label">FAIL</div>
    </div>
    <div class="card">
      <div class="card-value" style="color:{overall_color}">
        {overall_verdict.value}
      </div>
      <div class="card-label">Overall verdict</div>
    </div>
  </div>

  <h2>Procedure Results</h2>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Title</th><th>Requirement</th>
        <th>Verdict</th><th>Duration</th><th>Detail</th>
      </tr>
    </thead>
    <tbody>{procedure_rows}</tbody>
  </table>

  <h2>Requirement Coverage</h2>
  <table>
    <thead>
      <tr><th>Requirement</th><th>Covered By</th><th>Status</th></tr>
    </thead>
    <tbody>{req_rows}</tbody>
  </table>

  <div class="footer">
    Generated by OpenSVF &nbsp;|&nbsp;
    <a href="https://github.com/lipofefeyt/opensvf" style="color:#94a3b8">
      github.com/lipofefeyt/opensvf
    </a>
  </div>
</body>
</html>"""

    output_path.write_text(html)
    print(f"[report] HTML report: {output_path}")
    return output_path
