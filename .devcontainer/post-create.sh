#!/usr/bin/env bash
# .devcontainer/post-create.sh
# Runs once when the dev container is first created.

set -e
echo "=== opensvf dev container setup ==="

# ── System packages ───────────────────────────────────────────────────
sudo apt-get update -qq
sudo apt-get install -y \
    wget curl git default-jdk \
    python3-pip \
    pandoc texlive-xetex texlive-fonts-recommended texlive-fonts-extra texlive-latex-extra \
    2>/dev/null
echo "[1/4] System packages installed"

# ── Eisvogel PDF template ─────────────────────────────────────────────
EISVOGEL_TARGET="$OPENSVF_REPO/docs/datapack/eisvogel.latex"
if [ ! -f "$EISVOGEL_TARGET" ]; then
    echo "    Downloading Eisvogel 2.4.2..."
    mkdir -p "$OPENSVF_REPO/docs/datapack"
    wget -q https://github.com/Wandmalfarbe/pandoc-latex-template/releases/download/2.4.2/Eisvogel-2.4.2.tar.gz -O /tmp/eisvogel.tar.gz
    tar -xzf /tmp/eisvogel.tar.gz -C "$OPENSVF_REPO/docs/datapack" --wildcards "*.latex"
    rm /tmp/eisvogel.tar.gz
fi

# ── Python venv ───────────────────────────────────────────────────────
cd $OPENSVF_REPO
python3 -m venv .venv
source .venv/bin/activate
pip install -q -e ".[dev]"
echo "[2/4] Python venv ready"

# ── Renode ────────────────────────────────────────────────────────────
RENODE_DIR=/opt/renode
if [ ! -f "$RENODE_DIR/renode" ]; then
    echo "    Downloading Renode 1.15.3..."
    wget -q https://github.com/renode/renode/releases/download/v1.15.3/renode-1.15.3.linux-portable.tar.gz -O /tmp/renode.tar.gz
    sudo mkdir -p $RENODE_DIR
    sudo tar -xzf /tmp/renode.tar.gz -C $RENODE_DIR --strip-components=1
    sudo ln -sf $RENODE_DIR/renode /usr/local/bin/renode
    rm /tmp/renode.tar.gz
fi
echo "[3/4] Renode ready"

# ── YAMCS ─────────────────────────────────────────────────────────────
YAMCS_DIR=/opt/yamcs
if [ ! -f "$YAMCS_DIR/bin/yamcsd" ]; then
    echo "    Downloading YAMCS 5.12.6..."
    wget -q https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz -O /tmp/yamcs.tar.gz
    sudo mkdir -p $YAMCS_DIR
    sudo tar -xzf /tmp/yamcs.tar.gz -C $YAMCS_DIR --strip-components=1
    sudo ln -sf $YAMCS_DIR/bin/yamcsd /usr/local/bin/yamcsd
    rm /tmp/yamcs.tar.gz
fi
echo "[4/4] YAMCS ready"

# ── Run tests ─────────────────────────────────────────────────────────
source .venv/bin/activate
source "$OPENSVF_REPO/scripts/activate.sh"
pytest tests/ -q --tb=no 2>&1 | tail -3

# ── Global claude-global setup ────────────────────────────────────────
CLAUDE_GLOBAL=/home/vscode/.claude-global
mkdir -p "$CLAUDE_GLOBAL/contexts"
# Copy staged files to WSL2 host on first use (never overwrite user edits)
for f in "$OPENSVF_REPO/.devcontainer/claude-global/SETUP-NEW-REPO.md" \
          "$OPENSVF_REPO/.devcontainer/claude-global/contexts/openobsw-opensvf.md" \
          "$OPENSVF_REPO/.devcontainer/claude-global/contexts/opensvf-setup-handoff.md"; do
    dest="$CLAUDE_GLOBAL/${f#*claude-global/}"
    [ -f "$dest" ] || cp "$f" "$dest"
done
touch "$CLAUDE_GLOBAL/CLAUDE.md"
ln -sf "$CLAUDE_GLOBAL/CLAUDE.md" /home/vscode/.claude/CLAUDE.md
echo "[+] Global CLAUDE.md linked; context files seeded to WSL2 host"

echo ""
echo "=== opensvf container ready ==="
echo "YAMCS:  yamcsd (config in yamcs/etc/)"
echo "Tests:  testosvf"
echo "Checks: checkosvf && checkcov && checkcons"