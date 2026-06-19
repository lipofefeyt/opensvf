#!/usr/bin/env bash
# OpenSVF Full Setup  -  run once after clone or container rebuild
# Usage: source scripts/setup-workspace.sh

REPO=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)
cd "$REPO"

# Suppress the setup noise in the recording
[ -n "$ASCIINEMA_REC" ] && return 0

echo "=== OpenSVF Full Setup ==="

# 1. aarch64 toolchain
AARCH64_GCC=$(find /nix/store -name "aarch64-unknown-linux-gnu-gcc" \
    -path "*/gcc-wrapper*/bin/*" -type f 2>/dev/null | head -1)
if [ -z "$AARCH64_GCC" ]; then
    echo "[1/6] Installing aarch64 cross-compiler (once)..."
    nix-env -iA nixpkgs.pkgsCross.aarch64-multiplatform.stdenv.cc > /dev/null 2>&1
    echo "    Done"
else
    echo "[1/6] aarch64 toolchain: already installed"
fi

# 2. Python venv
echo "[2/6] Python venv..."
[ ! -f ".venv/bin/activate" ] && python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]" pyyaml yamcs-client

# 3. YAMCS
echo "[3/6] YAMCS..."
if [ -z "$(find /tmp/yamcs -name yamcsd 2>/dev/null)" ]; then
    echo "    Downloading YAMCS 5.12.6..."
    mkdir -p /tmp/yamcs
    curl -sL https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz \
        -o /tmp/yamcs.tar.gz
    tar -xzf /tmp/yamcs.tar.gz -C /tmp/yamcs --strip-components=1
fi
echo "    YAMCS: OK"

# 4. Renode
echo "[4/6] Renode..."
if ! command -v renode &>/dev/null; then
    echo "    Installing Renode portable..."
    mkdir -p /opt/renode
    curl -sL https://github.com/renode/renode/releases/download/v1.15.3/renode-1.15.3.linux-portable.tar.gz \
        | tar -xz -C /opt/renode --strip-components=1
    sudo ln -sf /opt/renode/renode /usr/local/bin/renode
fi
echo "    Renode: $(renode --version 2>&1 | head -1)"

# 5. XTCE
echo "[5/6] Generating XTCE..."
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
sed -i "s|spec: \".*yamcs/mdb/opensvf.xml\"|spec: \"$REPO/yamcs/mdb/opensvf.xml\"|" \
    yamcs/etc/yamcs.opensvf.yaml
echo "    $(wc -l < yamcs/mdb/opensvf.xml) lines"

# 6. Activate
echo "[6/6] Activating..."
source "$REPO/scripts/activate.sh"

echo ""
echo "=== Setup complete. Future terminals auto-activate via .bashrc ==="
