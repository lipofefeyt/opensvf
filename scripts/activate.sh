#!/usr/bin/env bash
# OpenSVF fast activation — source every terminal
# Usage: source scripts/activate.sh (or auto-sourced from .bashrc)
# Works in: WSL2 native, dev container, GitHub Codespaces

REPO=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)

# ── Python venv ───────────────────────────────────────────────────────
[ -f "$REPO/.venv/bin/activate" ] && source "$REPO/.venv/bin/activate"

# ── Java (for YAMCS) ─────────────────────────────────────────────────
if ! command -v java &>/dev/null; then
    JAVA=$(find /usr /opt /home -name "java" -type f 2>/dev/null | head -1)
    if [ -n "$JAVA" ]; then
        export JAVA_HOME=$(dirname "$(dirname "$JAVA")")
        export PATH="$JAVA_HOME/bin:$PATH"
    fi
fi

# ── aarch64-none-elf toolchain ────────────────────────────────────────
[ -d /opt/arm-gnu-toolchain/bin ] && export PATH="/opt/arm-gnu-toolchain/bin:$PATH"

# ── Test and quality ─────────────────────────────────────────────────
alias testosvf='pytest tests/ --junitxml=results/junit.xml -v'
alias checkosvf='mypy src/ --config-file pyproject.toml'
alias checkcov='python3 $REPO/tools/check_coverage.py'
alias checkcons='python3 $REPO/tools/srdb_consistency_check.py'
alias checkcons-full='python3 $REPO/tools/srdb_consistency_check.py --obsw'

# ── YAMCS ─────────────────────────────────────────────────────────────
alias yamcs-start='bash $REPO/scripts/start-yamcs.sh'
alias yamcs-stop='pkill -f yamcsd 2>/dev/null || true'
alias yamcs-log='tail -f /tmp/yamcs.log'
alias regen-xtce='python3 $REPO/tools/generate_xtce.py > $REPO/yamcs/mdb/opensvf.xml'

# ── Demo ──────────────────────────────────────────────────────────────
alias svf-demo='python3 $REPO/scripts/demo_yamcs.py'

echo "[opensvf] activated — repo: $REPO"
echo "[opensvf] aliases: testosvf checkosvf checkcov checkcons yamcs-start svf-demo"