#!/usr/bin/env bash
# Stop YAMCS  -  kill by saved PID first, fall back to process pattern.
_stopped=0

if [ -f /tmp/yamcs.pid ]; then
    _pid=$(cat /tmp/yamcs.pid)
    if kill -0 "$_pid" 2>/dev/null; then
        kill "$_pid" && echo "YAMCS stopped (PID $_pid)"
        _stopped=1
    fi
    rm -f /tmp/yamcs.pid
fi

# Fallback: any remaining YamcsServer processes (covers manual starts)
if pkill -f 'org.yamcs.YamcsServer' 2>/dev/null; then
    echo "YAMCS stopped (pattern match)"
    _stopped=1
fi

if [ "$_stopped" -eq 0 ]; then
    echo "YAMCS not running"
    exit 1
fi
