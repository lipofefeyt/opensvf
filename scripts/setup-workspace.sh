#!/usr/bin/env bash
# OpenSVF Full Setup — run once after clone or container rebuild
# Usage: source scripts/setup-workspace.sh

REPO=$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)
cd "$REPO"

echo "=== OpenSVF Full Setup ==="

# 1. aarch64 toolchain
AARCH64_GCC=$(find /nix/store -name "aarch64-unknown-linux-gnu-gcc" \
    -path "*/gcc-wrapper*/bin/*" -type f 2>/dev/null | head -1)
if [ -z "$AARCH64_GCC" ]; then
    echo "[1/5] Installing aarch64 cross-compiler (once)..."
    nix-env -iA nixpkgs.pkgsCross.aarch64-multiplatform.stdenv.cc > /dev/null 2>&1
    echo "    Done"
else
    echo "[1/5] aarch64 toolchain: already installed"
fi

# 2. Python venv
echo "[2/5] Python venv..."
[ ! -f ".venv/bin/activate" ] && python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -e ".[dev]" pyyaml yamcs-client

# 3. YAMCS
echo "[3/5] YAMCS..."
if [ -z "$(find /tmp/yamcs -name yamcsd 2>/dev/null)" ]; then
    echo "    Downloading YAMCS 5.12.6..."
    mkdir -p /tmp/yamcs
    curl -sL https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz \
        -o /tmp/yamcs.tar.gz
    tar -xzf /tmp/yamcs.tar.gz -C /tmp/yamcs --strip-components=1
fi
echo "    YAMCS: OK"

# 4. XTCE
echo "[4/5] Generating XTCE..."
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
sed -i "s|spec: \".*yamcs/mdb/opensvf.xml\"|spec: \"$REPO/yamcs/mdb/opensvf.xml\"|" \
    yamcs/etc/yamcs.opensvf.yaml
echo "    $(wc -l < yamcs/mdb/opensvf.xml) lines"

# 5. Activate
echo "[5/5] Activating..."
source "$REPO/scripts/activate.sh"

echo ""
echo "=== Setup complete. Future terminals auto-activate via .bashrc ==="
