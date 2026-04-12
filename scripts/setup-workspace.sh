#!/usr/bin/env bash
# OpenSVF Workspace Setup
# Run this once after cloning or after container restart.
# Usage: source scripts/setup-workspace.sh

set -e
REPO=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)
cd "$REPO"

echo "=== OpenSVF Workspace Setup ==="

# ------------------------------------------------------------------ #
# 1. Python virtual environment                                       #
# ------------------------------------------------------------------ #
if [ ! -f ".venv/bin/activate" ]; then
    echo "[1/6] Creating Python venv..."
    python3 -m venv .venv
else
    echo "[1/6] Python venv exists"
fi
source .venv/bin/activate

# ------------------------------------------------------------------ #
# 2. Python dependencies                                              #
# ------------------------------------------------------------------ #
echo "[2/6] Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -e ".[dev]"
pip install -q pyyaml yamcs-client 2>/dev/null || \
    pip install -q pyyaml yamcs-client --break-system-packages

# ------------------------------------------------------------------ #
# 3. Java detection                                                   #
# ------------------------------------------------------------------ #
echo "[3/6] Detecting Java..."
if ! command -v java &>/dev/null; then
    JAVA=$(find /nix /usr /opt /home ~/.nix-profile \
           -name "java" -type f 2>/dev/null | head -1)
    if [ -n "$JAVA" ]; then
        export JAVA_HOME=$(dirname $(dirname "$JAVA"))
        export PATH="$JAVA_HOME/bin:$PATH"
        echo "    Java found: $JAVA"
    else
        echo "    WARNING: Java not found — YAMCS will not start"
    fi
else
    echo "    Java: $(java -version 2>&1 | head -1)"
fi

# ------------------------------------------------------------------ #
# 4. YAMCS installation                                               #
# ------------------------------------------------------------------ #
echo "[4/6] Checking YAMCS..."
YAMCS_BIN=$(find /tmp/yamcs -name "yamcsd" 2>/dev/null | head -1)
if [ -z "$YAMCS_BIN" ]; then
    echo "    Downloading YAMCS 5.12.6..."
    mkdir -p /tmp/yamcs
    curl -sL https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz \
        -o /tmp/yamcs.tar.gz
    tar -xzf /tmp/yamcs.tar.gz -C /tmp/yamcs --strip-components=1
    echo "    YAMCS installed"
else
    echo "    YAMCS: $YAMCS_BIN"
fi

# ------------------------------------------------------------------ #
# 5. XTCE mission database                                            #
# ------------------------------------------------------------------ #
echo "[5/6] Generating XTCE mission database..."
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
# Fix absolute path in instance config
sed -i "s|spec: \".*yamcs/mdb/opensvf.xml\"|spec: \"$REPO/yamcs/mdb/opensvf.xml\"|" \
    yamcs/etc/yamcs.opensvf.yaml
echo "    XTCE: $(wc -l < yamcs/mdb/opensvf.xml) lines → yamcs/mdb/opensvf.xml"

# ------------------------------------------------------------------ #
# 6. Aliases                                                          #
# ------------------------------------------------------------------ #
echo "[6/6] Setting up aliases..."

alias testosvf='pytest tests/ --junitxml=results/junit.xml -v'
alias checkosvf='mypy src/ --config-file pyproject.toml'
alias checkcov='python3 scripts/check_coverage.py'
alias yamcs-start='bash $REPO/scripts/start-yamcs.sh'
alias yamcs-stop='pkill -f yamcsd && echo "YAMCS stopped" || echo "YAMCS not running"'
alias yamcs-log='curl -s http://localhost:8090/api/instances | python3 -m json.tool | grep -E "\"name\"|\"state\""'
alias yamcs-log-follow='tail -f /tmp/yamcs.log'
alias svf-demo-fg='cd $REPO && .venv/bin/python3 scripts/demo_yamcs.py'
alias svf-campaign='svf run'
alias svf-campaign-all='for f in $REPO/campaigns/*.yaml; do svf run "$f"; done'
alias svf-demo='bash $REPO/scripts/demo.sh'
alias regen-xtce='python3 $REPO/tools/generate_xtce.py > $REPO/yamcs/mdb/opensvf.xml && echo "XTCE: $(wc -l < $REPO/yamcs/mdb/opensvf.xml) lines"'

echo ""
echo "=== Setup complete ==="
echo ""
echo "Available commands:"
echo "  testosvf      — run full test suite"
echo "  checkosvf     — run mypy type checker"
echo "  yamcs-start   — start YAMCS ground station"
echo "  yamcs-stop    — stop YAMCS"
echo "  yamcs-log     — check YAMCS instance state"
echo "  svf-demo-fg   — run SVF demo in foreground (needs YAMCS already running)
  svf-campaign  — run a campaign (e.g. svf-campaign campaigns/eps_validation.yaml)
  svf-campaign-all — run all campaigns
  svf-demo      — start full SVF + YAMCS demo (tmux)
  regen-xtce    — regenerate XTCE from SRDB"
echo ""
echo "Quick start:"
echo "  source scripts/setup-workspace.sh"
echo "  yamcs-start"
echo "  python3 scripts/demo_yamcs.py"
