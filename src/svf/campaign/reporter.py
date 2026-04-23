from __future__ import annotations
import logging
from pathlib import Path
from datetime import datetime
from jinja2 import Template
from svf.campaign.procedure import Verdict

# Type checking imports
from typing import TYPE_CHECKING, Dict, List, Any
if TYPE_CHECKING:
    from svf.campaign.campaign_runner import CampaignReport

logger = logging.getLogger(__name__)

REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenSVF — {{ record.campaign_name or "Validation Report" }}</title>
<style>
    :root {
        --bg: #f8fafc; --card-bg: #ffffff; --text: #1e293b;
        --primary: #1e293b; --secondary: #64748b;
        --pass: #22c55e; --fail: #ef4444; --error: #f59e0b;
        --tc: #3b82f6; --tm: #10b981; --inject: #8b5cf6;
    }
    body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; line-height: 1.5; }
    .header { margin-bottom: 2rem; border-bottom: 2px solid #e2e8f0; padding-bottom: 1rem; }
    .header h1 { margin: 0; font-size: 1.8rem; }
    .meta { color: #64748b; font-size: 0.9rem; }
    .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
    .stat-card { background: var(--card-bg); padding: 1.25rem; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
    .stat-val { font-size: 1.5rem; font-weight: 700; display: block; }
    .stat-label { font-size: 0.8rem; color: var(--secondary); text-transform: uppercase; }

    .proc-card { background: var(--card-bg); border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 1rem; overflow: hidden; border: 1px solid #e2e8f0; }
    .proc-header { padding: 1rem; cursor: pointer; display: flex; align-items: center; justify-content: space-between; transition: background 0.2s; }
    .proc-header:hover { background: #f1f5f9; }
    .proc-title { font-weight: 600; display: flex; align-items: center; gap: 0.75rem; }
    .proc-meta { color: var(--secondary); font-size: 0.85rem; font-family: monospace; }
    
    .badge { padding: 0.25rem 0.6rem; border-radius: 6px; font-weight: 700; font-size: 0.7rem; color: white; text-transform: uppercase; }
    .bg-pass { background: var(--pass); } .bg-fail { background: var(--fail); } .bg-error { background: var(--error); }
    
    .proc-content { display: none; padding: 1.5rem; border-top: 1px solid #e2e8f0; background: #fafafa; }
    .proc-card.open .proc-content { display: block; }
    
    .timeline { position: relative; padding-left: 1.5rem; border-left: 2px solid #e2e8f0; margin-left: 0.5rem; }
    .step-block { margin-bottom: 1.5rem; position: relative; }
    .step-block::before { content: ''; position: absolute; left: -1.95rem; top: 0.25rem; width: 0.75rem; height: 0.75rem; border-radius: 50%; background: white; border: 2px solid var(--primary); }
    .step-name { font-weight: 700; font-size: 0.95rem; display: block; margin-bottom: 0.5rem; }
    
    .event-row { display: flex; gap: 1rem; font-size: 0.85rem; margin-bottom: 0.25rem; font-family: monospace; padding: 0.25rem; border-radius: 4px; align-items: flex-start; }
    .event-row:hover { background: #f1f5f9; }
    .ev-time { color: var(--secondary); width: 60px; flex-shrink: 0; }
    .ev-type { font-weight: 700; width: 80px; flex-shrink: 0; white-space: nowrap; }
    .type-TC { color: var(--tc); } .type-TM { color: var(--tm); } .type-INJECT { color: var(--inject); } .type-MONITOR { color: var(--fail); } .type-STEP { color: var(--primary); }
    
    .seed-box { background: #1e293b; color: #f8fafc; padding: 0.75rem; border-radius: 8px; font-family: monospace; font-size: 0.85rem; margin-top: 1rem; display: flex; justify-content: space-between; align-items: center; }
    .copy-btn { background: #334155; border: none; color: white; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.7rem; }

    .req-table { width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; margin-top: 2rem; }
    .req-table th { background: #1e293b; color: white; text-align: left; padding: 0.75rem 1rem; font-size: 0.85rem; }
    .req-table td { padding: 0.75rem 1rem; border-bottom: 1px solid #f1f5f9; }

    footer { text-align: center; margin-top: 4rem; color: var(--secondary); font-size: 0.8rem; padding-bottom: 2rem; }
</style>
</head>
<body>
    <div class="header">
        <h1>{{ record.campaign_name or "OpenSVF Validation" }}</h1>
        <div class="meta">Spacecraft: <strong>{{ record.spacecraft }}</strong> | Generated: {{ timestamp }} | Duration: {{ "%.1f"|format(record.duration_s) }}s</div>
    </div>

    <div class="summary-grid">
        <div class="stat-card"><span class="stat-val">{{ record.n_procedures }}</span><span class="stat-label">Total Procedures</span></div>
        <div class="stat-card"><span class="stat-val" style="color:var(--pass)">{{ record.n_pass }}</span><span class="stat-label">Passed</span></div>
        <div class="stat-card"><span class="stat-val" style="color:var(--fail)">{{ record.n_fail }}</span><span class="stat-label">Failed</span></div>
        <div class="stat-card"><span class="stat-val">{{ "%.1f"|format(record.pass_rate * 100) }}%</span><span class="stat-label">Pass Rate</span></div>
    </div>

    <h2>Procedure Results</h2>
    {% for r in record.results %}
    <div class="proc-card" id="card-{{ loop.index }}">
        <div class="proc-header" onclick="document.getElementById('card-{{ loop.index }}').classList.toggle('open')">
            <div class="proc-title">
                <span class="badge bg-{{ r.verdict.value.lower() }}">{{ r.verdict.value }}</span>
                {{ r.procedure_id }}: {{ r.title }}
            </div>
            <div class="proc-meta">REQ: {{ r.requirement }} | {{ "%.1f"|format(r.duration_s) }}s</div>
        </div>
        <div class="proc-content">
            <div class="timeline">
                {% for step in r.steps %}
                <div class="step-block">
                    <span class="step-name">{{ step.step_name }}</span>
                    {% if step.detail %}<div style="color:var(--fail); font-size: 0.85rem; margin-bottom: 0.5rem;">{{ step.detail }}</div>{% endif %}
                    {% for ev in step.events %}
                    <div class="event-row">
                        <span class="ev-time">{{ ev.t }}s</span>
                        <span class="ev-type type-{{ ev.event_type.value }}">{{ ev.event_type.value }}</span>
                        <span class="ev-desc">{{ ev.description }}</span>
                    </div>
                    {% endfor %}
                </div>
                {% endfor %}
            </div>
            
            {% if r.seed %}
            <div class="seed-box">
                <span>Replay seed: <code>{{ r.seed }}</code></span>
                <button class="copy-btn" onclick="navigator.clipboard.writeText('svf run mission_mysat1/spacecraft.yaml --seed {{ r.seed }}')">Copy Replay Cmd</button>
            </div>
            {% endif %}
        </div>
    </div>
    {% endfor %}

    <h2>Requirement Coverage</h2>
    <table class="req-table">
        <thead>
            <tr><th>Requirement ID</th><th style="width: 150px">Status</th></tr>
        </thead>
        <tbody>
            {% for req_id, status in req_summary.items() %}
            <tr>
                <td style="font-family: monospace; font-weight: 700;">{{ req_id }}</td>
                <td><span class="badge bg-{{ 'pass' if status == 'COVERED' else 'fail' }}">{{ status }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    <footer>
        Generated by OpenSVF | <a href="https://github.com/lipofefeyt/opensvf" style="color:var(--secondary)">GitHub</a>
    </footer>
</body>
</html>"""

class CampaignReporter:
    def generate(self, report: CampaignReport, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        req_summary: Dict[str, str] = {}
        for r in report.results:
            if r.requirement:
                current = req_summary.get(r.requirement, "COVERED")
                if r.verdict != Verdict.PASS:
                    req_summary[r.requirement] = "FAILED"
                else:
                    req_summary[r.requirement] = current

        template = Template(REPORT_TEMPLATE)
        html = template.render(
            record=report,
            req_summary=req_summary,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        output_path.write_text(html)
        return output_path

def generate_html_report(report: CampaignReport, output_path: Path) -> Path:
    return CampaignReporter().generate(report, output_path)
