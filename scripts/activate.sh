#!/usr/bin/env bash
# OpenSVF fast activation — runs every terminal
# Usage: source scripts/activate.sh (or auto-sourced from .bashrc)

REPO=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)

echo "[1/4] Activating Venv"

# Venv
[ -f "$REPO/.venv/bin/activate" ] && source "$REPO/.venv/bin/activate"

echo "[2/4] Adding Nix Profile"

# Nix profile (cross compiler)
[ -d "$HOME/.nix-profile/bin" ] && export PATH="$HOME/.nix-profile/bin:$PATH"

echo "[3/4] Adding Java environment"

# Java
if ! command -v java &>/dev/null; then
    JAVA=$(find /nix /usr /opt -name "java" -type f 2>/dev/null | head -1)
    [ -n "$JAVA" ] && export JAVA_HOME=$(dirname $(dirname "$JAVA")) && \
        export PATH="$JAVA_HOME/bin:$PATH"
fi

echo "[4/4] Adding aarch64 glibc for QEMU"

# aarch64 glibc for QEMU
export AARCH64_GLIBC=$(find /nix/store -name "ld-linux-aarch64.so.1" \
    2>/dev/null | head -1 | sed 's|/lib/ld-linux-aarch64.so.1||')

# Aliases
alias testosvf='pytest tests/ --junitxml=results/junit.xml -v'
alias checkosvf='mypy src/ --config-file pyproject.toml'
alias checkcov='python3 scripts/check_coverage.py'
alias svf-campaign='svf run'
alias svf-campaign-all='for f in $REPO/campaigns/*.yaml; do svf run "$f"; done'
alias yamcs-start='bash $REPO/scripts/start-yamcs.sh'
alias yamcs-stop='pkill -f yamcsd 2>/dev/null || true'
alias yamcs-log-follow='tail -f /tmp/yamcs.log'
alias regen-xtce='python3 $REPO/tools/generate_xtce.py > $REPO/yamcs/mdb/opensvf.xml'
alias svf-demo-fg='cd $REPO && .venv/bin/python3 scripts/demo_yamcs.py'
alias svf-demo='bash $REPO/scripts/demo.sh'
[ -n "$AARCH64_GLIBC" ] && \
    alias omksim-aarch64='qemu-aarch64 -L $AARCH64_GLIBC $REPO/obsw_sim_aarch64'
