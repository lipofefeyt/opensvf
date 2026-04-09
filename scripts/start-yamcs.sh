#!/usr/bin/env bash
# Start YAMCS ground station for OpenSVF
set -e

YAMCS_BIN=$(find /tmp/yamcs -name "yamcsd" 2>/dev/null | head -1)
if [ -z "$YAMCS_BIN" ]; then
    echo "ERROR: yamcsd not found in /tmp/yamcs. Re-extract the distribution."
    exit 1
fi

pkill -f yamcsd 2>/dev/null || true
sleep 1

echo "Starting YAMCS 5.12.6..."
$YAMCS_BIN --etc-dir "$(pwd)/yamcs/etc" &
YAMCS_PID=$!
echo "YAMCS PID: $YAMCS_PID"

# Wait for HTTP API
for i in $(seq 1 20); do
    if curl -sf http://localhost:8090/api/ > /dev/null 2>&1; then
        echo "YAMCS ready at http://localhost:8090"
        echo "Instance: http://localhost:8090/yamcs/opensvf"
        exit 0
    fi
    sleep 1
done

echo "ERROR: YAMCS did not start within 20s"
exit 1