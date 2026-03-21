"""
SVF GitHub Setup Script
Creates milestones, labels, and issues via the GitHub REST API.
Requires env vars: GH_TOKEN, REPO (e.g. "username/reponame")
"""

import json
import os
import sys
import urllib.request
import urllib.error
import time

# ── Configuration ─────────────────────────────────────────────────────────────

MILESTONES = [
    {"title": "M1 - Simulation Master",      "description": "fmpy stepping a single FMU, outputs logged to CSV"},
    {"title": "M2 - DDS Integration",         "description": "Cyclone DDS publishing FMU outputs as typed topics"},
    {"title": "M3 - pytest Plugin",           "description": "Simulation lifecycle fixture and verdict engine"},
    {"title": "M4 - First Real Model",        "description": "Spacecraft power or thermal FMU, full stack validation"},
    {"title": "M5 - Campaign and Reporting",  "description": "YAML campaign loader, JUnit XML and traceability matrix"},
]

LABELS = [
    {"name": "type: feature",         "color": "0075ca"},
    {"name": "type: bug",             "color": "d73a4a"},
    {"name": "type: spike",           "color": "e4e669"},
    {"name": "type: docs",            "color": "cfd3d7"},
    {"name": "type: refactor",        "color": "f9d0c4"},
    {"name": "layer: sim-core",       "color": "0e8a16"},
    {"name": "layer: comm-bus",       "color": "1d7d1d"},
    {"name": "layer: orchestration",  "color": "2ea44f"},
    {"name": "layer: model-authoring","color": "3cb371"},
    {"name": "layer: reporting",      "color": "5aab61"},
    {"name": "priority: now",         "color": "e05d0a"},
    {"name": "priority: next",        "color": "f4a261"},
    {"name": "priority: later",       "color": "fce8d5"},
    {"name": "req: sim-core",         "color": "7057ff"},
    {"name": "req: comm-bus",         "color": "9b59b6"},
    {"name": "req: orchestration",    "color": "b39ddb"},
]

# ── GitHub API helpers ─────────────────────────────────────────────────────────

TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
REPO  = os.environ.get("REPO")

if not TOKEN or not REPO:
    print("ERROR: GH_TOKEN and REPO environment variables must be set.")
    sys.exit(1)

BASE_URL = f"https://api.github.com/repos/{REPO}"
HEADERS  = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept":        "application/vnd.github+json",
    "Content-Type":  "application/json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def api(method, path, data=None):
    url = BASE_URL + path
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def get_all(path):
    results = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        status, data = api("GET", f"{path}{sep}per_page=100&page={page}")
        if status != 200 or not data:
            break
        results.extend(data)
        if len(data) < 100:
            break
        page += 1
    return results

# ── Step 1: Milestones ────────────────────────────────────────────────────────

print("\n=== Creating Milestones ===")
existing_milestones = {m["title"]: m["number"] for m in get_all("/milestones?state=all")}
milestone_map = dict(existing_milestones)

for m in MILESTONES:
    if m["title"] in existing_milestones:
        print(f"  ⊘ Exists:  {m['title']}")
        continue
    status, resp = api("POST", "/milestones", m)
    if status == 201:
        milestone_map[m["title"]] = resp["number"]
        print(f"  ✓ Created: {m['title']}")
    else:
        print(f"  ✗ Failed:  {m['title']} — HTTP {status}: {resp.get('message', resp)}")

# ── Step 2: Labels ────────────────────────────────────────────────────────────

print("\n=== Creating Labels ===")
existing_labels = {l["name"] for l in get_all("/labels")}

for l in LABELS:
    if l["name"] in existing_labels:
        print(f"  ⊘ Exists:  {l['name']}")
        continue
    status, resp = api("POST", "/labels", l)
    if status == 201:
        print(f"  ✓ Created: {l['name']}")
    else:
        print(f"  ✗ Failed:  {l['name']} — HTTP {status}: {resp.get('message', resp)}")

# ── Step 3: Issues ────────────────────────────────────────────────────────────

print("\n=== Creating Issues ===")

with open("issues.json", "r", encoding="utf-8") as f:
    issues = json.load(f)

existing_issues = {i["title"] for i in get_all("/issues?state=all")}

created = skipped = failed = 0

for issue in issues:
    title = issue["title"]

    if title in existing_issues:
        print(f"  ⊘ Skipped: {title}")
        skipped += 1
        continue

    milestone_title = issue.get("milestone", "")
    milestone_number = milestone_map.get(milestone_title)

    payload = {
        "title":  title,
        "body":   issue.get("body", ""),
        "labels": issue.get("labels", []),
    }
    if milestone_number:
        payload["milestone"] = milestone_number

    status, resp = api("POST", "/issues", payload)
    time.sleep(0.5)  # Stay well within GitHub rate limits

    if status == 201:
        print(f"  ✓ Created: {title}")
        created += 1
    else:
        print(f"  ✗ Failed:  {title} — HTTP {status}: {resp.get('message', resp)}")
        failed += 1

# ── Summary ───────────────────────────────────────────────────────────────────

print(f"\n=== Done: {created} created, {skipped} skipped, {failed} failed ===")
if failed > 0:
    sys.exit(1)
