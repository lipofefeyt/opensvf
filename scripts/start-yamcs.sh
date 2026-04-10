#!/usr/bin/env bash
# Start YAMCS ground station for OpenSVF
set -e

# Java detection
if ! command -v java &>/dev/null; then
    JAVA=$(find /nix /usr /opt /home ~/.nix-profile \
           -name "java" -type f 2>/dev/null | head -1)
    if [ -n "$JAVA" ]; then
        export JAVA_HOME=$(dirname $(dirname "$JAVA"))
        export PATH="$JAVA_HOME/bin:$PATH"
    else
        echo "ERROR: Java not found"; exit 1
    fi
fi

# YAMCS binary detection
YAMCS_BIN=$(find /tmp/yamcs -name "yamcsd" 2>/dev/null | head -1)
if [ -z "$YAMCS_BIN" ]; then
    echo "YAMCS not found — downloading..."
    mkdir -p /tmp/yamcs
    curl -sL https://github.com/yamcs/yamcs/releases/download/yamcs-5.12.6/yamcs-5.12.6-linux-x86_64.tar.gz \
        -o /tmp/yamcs.tar.gz
    tar -xzf /tmp/yamcs.tar.gz -C /tmp/yamcs --strip-components=1
    YAMCS_BIN=$(find /tmp/yamcs -name "yamcsd" | head -1)
fi

REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

# Regenerate XTCE
python3 tools/generate_xtce.py > yamcs/mdb/opensvf.xml
sed -i "s|spec: \".*yamcs/mdb/opensvf.xml\"|spec: \"$REPO/yamcs/mdb/opensvf.xml\"|" \
    yamcs/etc/yamcs.opensvf.yaml
echo "XTCE regenerated ($(wc -l < yamcs/mdb/opensvf.xml) lines)"

# Kill ALL existing YAMCS and free ports
echo "Stopping any existing YAMCS..."
pkill -9 -f yamcsd 2>/dev/null || true
sleep 1

# Wait for port 8090 to be free
for i in $(seq 1 10); do
    if ! ss -tlnp 2>/dev/null | grep -q ':8090' && \
       ! netstat -tlnp 2>/dev/null | grep -q ':8090'; then
        break
    fi
    echo "  Waiting for port 8090 to be released... ($i)"
    fuser -k 8090/tcp 2>/dev/null || true
    sleep 1
done

# Clean RocksDB locks
rm -f /tmp/yamcs-data/_global.rdb/LOCK
rm -f /tmp/yamcs-data/opensvf.rdb/LOCK

echo "Starting YAMCS 5.12.6..."
"$YAMCS_BIN" --etc-dir "$REPO/yamcs/etc" > /tmp/yamcs.log 2>&1 &
YAMCS_PID=$!
echo "YAMCS PID: $YAMCS_PID"

# Wait for YAMCS HTTP — but only count it ready AFTER new process starts
sleep 2
for i in $(seq 1 20); do
    if kill -0 $YAMCS_PID 2>/dev/null && \
       curl -sf http://localhost:8090/api/ > /dev/null 2>&1; then
        echo "YAMCS ready at http://localhost:8090"
        echo "Log: /tmp/yamcs.log"
        exit 0
    fi
    if ! kill -0 $YAMCS_PID 2>/dev/null; then
        echo "ERROR: YAMCS process died. Last log:"
        tail -20 /tmp/yamcs.log
        exit 1
    fi
    sleep 1
done

echo "ERROR: YAMCS did not start within 20s. Last log:"
tail -20 /tmp/yamcs.log
exit 1
