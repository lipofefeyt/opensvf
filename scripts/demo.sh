#!/usr/bin/env bash
# OpenSVF + YAMCS Demo — one command to run everything
# Usage: bash scripts/demo.sh

set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
cd "$REPO"

# Activate venv
source "$REPO/.venv/bin/activate"

# Kill any existing session
tmux kill-session -t svf 2>/dev/null || true

# Create tmux session
tmux new-session -d -s svf -n yamcs
tmux new-window -t svf -n demo

# Start YAMCS in window 0
tmux send-keys -t svf:yamcs "cd $REPO && bash scripts/start-yamcs.sh" Enter

echo "Starting YAMCS... (waiting 20s)"
sleep 20

# Start demo in window 1
tmux send-keys -t svf:demo "cd $REPO && .venv/bin/python3 scripts/demo_yamcs.py" Enter

echo ""
echo "=== OpenSVF + YAMCS Demo Running ==="
echo ""
echo "YAMCS UI:   http://localhost:8090"
echo "Instance:   opensvf | Processor: realtime"
echo ""
echo "tmux shortcuts:"
echo "  Ctrl+B 0  — YAMCS window"
echo "  Ctrl+B 1  — SVF demo window"  
echo "  Ctrl+B d  — detach (keeps running)"
echo ""
echo "Attaching to demo window in 3s... (Ctrl+B d to detach)"
sleep 3
tmux attach -t svf:demo
