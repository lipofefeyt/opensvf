#!/usr/bin/env bash
# .devcontainer/post-create.sh
# Runs once when the dev container is first created.

set -e
echo "=== opensvf dev container setup ==="

# ── System packages ───────────────────────────────────────────────────
sudo apt-get update -qq
sudo apt-get install -y \
    wget curl git \
    python3-pip \
    2>/dev/null
echo "[1/4] System packages installed"

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
pytest tests/ -q --tb=no 2>&1 | tail -3

echo ""
echo "=== opensvf container ready ==="
echo "YAMCS:  yamcsd (config in yamcs/etc/)"
echo "Tests:  testosvf"
echo "Checks: checkosvf && checkcov && checkcons"