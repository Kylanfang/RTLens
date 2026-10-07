#!/bin/bash
# ============================================================
#  RTLens v5.0.0 Quickstart Launcher for Linux/macOS
#  Run: ./start.sh
#  Browser will open automatically at http://127.0.0.1:8765
# ============================================================

cd "$(dirname "$0")"

echo "============================================"
echo "  RTLens v5.0.0 - Verilog LSP Quickstart"
echo "============================================"
echo ""

# --- 1. check rtlens package exists ---
if [ ! -f "rtlens/__main__.py" ]; then
    echo "[ERROR] rtlens package not found next to start.sh"
    echo "        Please EXTRACT the whole zip first, then run start.sh"
    exit 1
fi

# --- 2. find Python ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &> /dev/null; then
        if "$cmd" --version &> /dev/null; then
            PYTHON="$cmd"
            echo "[OK] Found $($PYTHON --version)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python 3.8+ not found."
    echo "        Please install from https://www.python.org/downloads/"
    exit 1
fi

echo ""
echo "[..] Starting Web UI, browser will open automatically..."
echo "[..] Press Ctrl+C to stop."
echo ""

# --- 3. run quickstart (browser opens automatically) ---
$PYTHON -m rtlens quickstart
RC=$?
echo ""
if [ $RC -ne 0 ]; then
    echo "[ERROR] quickstart exited with code $RC"
    echo "        If port 8765 is in use, try: $PYTHON -m rtlens quickstart --port 8766"
fi
