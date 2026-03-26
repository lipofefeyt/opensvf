"""
SVF Campaign Reporter
Generates a self-contained HTML report from a CampaignRecord.
Implements: SVF-DEV-071, SVF-DEV-073, SVF-DEV-074, SVF-DEV-075
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Template

from svf.campaign.executor import CampaignRecord
from svf.plugin.verdict import Verdict

logger = logging.getLogger(__name__)

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SVF Campaign Report — {{ record.campaign_id }}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  .header { background: #1a1d2e; border-bottom: 1px solid #2d3748; padding: 2rem; }
  .header h1 { font-size: 1.5rem; font-weight: 700; color: #fff; }
  .header .meta { color: #94a3b8; font-size: 0.85rem; margin-top: 0.5rem; }
  .content { max-width: 1100px; margin: 0 auto; padding: 2rem; }
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 2rem; }
  .card { background: #1a1d2e; border-radius: 8px; padding: 1.25rem; text-align: center; }
  .card .count { font-size: 2rem; font-weight: 700; }
  .card .label { font-size: 0.8rem; color: #94a3b8; margin-top: 0.25rem; }
  .pass { color: #4ade80; }
  .fail { color: #f87171; }
  .error { color: #fb923c; }
  .inconclusive { color: #94a3b8; }
  .section-title { font-size: 1rem; font-weight: 600; color: #94a3b8;
                   text-transform: uppercase; letter-spacing: 0.05em;
                   margin-bottom: 1rem; margin-top: 2rem; }
  table { width: 100%; border-collapse: collapse; background: #1a1d2e; border-radius: 8px; overflow: hidden; }
  th { background: #232638; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase;
       letter-spacing: 0.05em; padding: 0.75rem 1rem; text-align: left; }
  td { padding: 0.875rem 1rem; border-top: 1px solid #2d3748; font-size: 0.875rem; }
  tr:hover td { background: #232638; }
  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px;
           font-size: 0.75rem; font-weight: 600; }
  .badge-pass { background: #14532d; color: #4ade80; }
  .badge-fail { background: #450a0a; color: #f87171; }
  .badge-error { background: #431407; color: #fb923c; }
  .badge-inconclusive { background: #1e293b; color: #94a3b8; }
  .verdict-banner { padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 2rem;
                    font-weight: 600; font-size: 1rem; }
  .verdict-pass { background: #14532d; color: #4ade80; }
  .verdict-fail { background: #450a0a; color: #f87171; }
  .verdict-error { background: #431407; color: #fb923c; }
  .verdict-inconclusive { background: #1e293b; color: #94a3b8; }
  .hash { font-family: monospace; font-size: 0.75rem; color: #64748b; }
  .error-msg { color: #f87171; font-size: 0.8rem; font-style: italic; }
</style>
</head>
<body>

<div class="header">
  <h1>SVF Campaign Report</h1>
  <div class="meta">
    {{ record.campaign_id }} &nbsp;·&nbsp;
    {{ record.model_baseline }} &nbsp;·&nbsp;
    SVF {{ record.svf_version }} &nbsp;·&nbsp;
    {{ record.started_at[:19].replace('T', ' ') }} UTC &nbsp;·&nbsp;
    {{ "%.1f"|format(record.duration) }}s total
  </div>
</div>

<div class="content">

  <div class="verdict-banner verdict-{{ record.overall_verdict.value.lower() }}">
    Overall Verdict: {{ record.overall_verdict.value }}
  </div>

  <div class="summary">
    <div class="card">
      <div class="count pass">{{ record.passed }}</div>
      <div class="label">PASS</div>
    </div>
    <div class="card">
      <div class="count fail">{{ record.failed }}</div>
      <div class="label">FAIL</div>
    </div>
    <div class="card">
      <div class="count error">{{ record.errors }}</div>
      <div class="label">ERROR</div>
    </div>
    <div class="card">
      <div class="count inconclusive">{{ record.inconclusive }}</div>
      <div class="label">INCONCLUSIVE</div>
    </div>
  </div>

  <div class="section-title">Test Cases</div>
  <table>
    <thead>
      <tr>
        <th>ID</th>
        <th>Test</th>
        <th>Verdict</th>
        <th>Duration</th>
        <th>Notes</th>
      </tr>
    </thead>
    <tbody>
    {% for result in record.results %}
      <tr>
        <td><strong>{{ result.id }}</strong></td>
        <td class="hash">{{ result.test.split("::")[-1] }}</td>
        <td>
          <span class="badge badge-{{ result.verdict.value.lower() }}">
            {{ result.verdict.value }}
          </span>
        </td>
        <td>{{ "%.1f"|format(result.duration) }}s</td>
        <td>
          {% if result.error %}
            <span class="error-msg">{{ result.error }}</span>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  {% if requirements %}
  <div class="section-title">Requirements Traceability</div>
  <table>
    <thead>
      <tr>
        <th>Requirement</th>
        <th>Test Case</th>
        <th>Verdict</th>
      </tr>
    </thead>
    <tbody>
    {% for req_id, tc_id, verdict in requirements %}
      <tr>
        <td><strong>{{ req_id }}</strong></td>
        <td>{{ tc_id }}</td>
        <td>
          <span class="badge badge-{{ verdict.lower() }}">{{ verdict }}</span>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% endif %}

  <div class="section-title">Campaign Metadata</div>
  <table>
    <tbody>
      <tr><td><strong>Campaign ID</strong></td><td>{{ record.campaign_id }}</td></tr>
      <tr><td><strong>Model Baseline</strong></td><td>{{ record.model_baseline }}</td></tr>
      <tr><td><strong>SVF Version</strong></td><td>{{ record.svf_version }}</td></tr>
      <tr><td><strong>Started</strong></td><td>{{ record.started_at[:19].replace('T', ' ') }} UTC</td></tr>
      <tr><td><strong>Finished</strong></td><td>{{ record.finished_at[:19].replace('T', ' ') }} UTC</td></tr>
      <tr><td><strong>File Hash</strong></td><td class="hash">{{ record.file_hash }}</td></tr>
    </tbody>
  </table>

</div>
</body>
</html>"""


class CampaignReporter:
    """
    Generates a self-contained HTML report from a CampaignRecord.

    Usage:
        reporter = CampaignReporter()
        report_path = reporter.generate(record, campaign, output_dir)
        print(f"Report: {report_path}")
    """

    def generate(
        self,
        record: CampaignRecord,
        campaign: "CampaignDefinition",  # type: ignore[name-defined]
        output_dir: Path,
    ) -> Path:
        """
        Render the HTML report and write to output_dir/report.html.
        Returns the path to the generated report.
        """
        from svf.campaign.definitions import CampaignDefinition

        # Build requirements traceability rows
        # Map test node -> test case ID
        node_to_id = {tc.test: tc.id for tc in campaign.test_cases}
        id_to_verdict = {r.id: r.verdict.value for r in record.results}

        requirements: list[tuple[str, str, str]] = []
        for req_id in campaign.requirements:
            for tc in campaign.test_cases:
                tc_verdict = id_to_verdict.get(tc.id, "INCONCLUSIVE")
                requirements.append((req_id, tc.id, tc_verdict))

        template = Template(REPORT_TEMPLATE)
        html = template.render(
            record=record,
            requirements=requirements,
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        report_path = output_dir / "report.html"
        report_path.write_text(html, encoding="utf-8")

        logger.info(f"Report written to {report_path}")
        return report_path
