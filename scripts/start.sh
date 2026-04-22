#!/bin/bash
# Cadge Start - launches API + UI with clean shutdown on Ctrl+C
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

API_PORT=33401
UI_PORT=33400
API_PID=""
UI_PID=""

cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null && echo -e "  ${CYAN}Stopped API (PID $API_PID)${NC}"
    [ -n "$UI_PID" ] && kill "$UI_PID" 2>/dev/null && echo -e "  ${CYAN}Stopped UI (PID $UI_PID)${NC}"
    # Kill any remaining children
    wait 2>/dev/null
    echo -e "${GREEN}Cadge stopped.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# ── Preflight checks ────────────────────────────────────────────────

# Check setup was run
if [ ! -d "$ROOT_DIR/backend/venv" ]; then
    echo -e "${RED}Backend venv not found.${NC} Run ./scripts/setup.sh first."
    exit 1
fi

if [ ! -d "$ROOT_DIR/frontend/node_modules" ]; then
    echo -e "${RED}Frontend node_modules not found.${NC} Run ./scripts/setup.sh first."
    exit 1
fi

# Check ports are free (nc -z uses a safe kernel path; lsof has triggered macOS kernel panics)
if nc -z 127.0.0.1 "$API_PORT" >/dev/null 2>&1; then
    echo -e "${RED}Port $API_PORT is already in use.${NC} Run ./scripts/stop.sh first."
    exit 1
fi

if nc -z 127.0.0.1 "$UI_PORT" >/dev/null 2>&1; then
    echo -e "${RED}Port $UI_PORT is already in use.${NC} Run ./scripts/stop.sh first."
    exit 1
fi

# ── Start services ──────────────────────────────────────────────────

echo ""
echo -e "${CYAN}Starting Cadge${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Start backend API
cd "$ROOT_DIR/backend"
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port "$API_PORT" 2>&1 | sed "s/^/[${CYAN}api${NC}] /" &
API_PID=$!
echo -e "  ${GREEN}API${NC} started on port $API_PORT (PID $API_PID)"

# Start frontend UI
cd "$ROOT_DIR/frontend"
npm run dev 2>&1 | sed "s/^/[${CYAN} ui${NC}] /" &
UI_PID=$!
echo -e "  ${GREEN}UI${NC}  started on port $UI_PORT (PID $UI_PID)"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  UI:  ${GREEN}http://localhost:$UI_PORT${NC}"
echo -e "  API: ${GREEN}http://localhost:$API_PORT${NC}"
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop"
echo ""

# Wait for either process to exit
wait -n 2>/dev/null || true

# If one exited, check which and report
if [ -n "$API_PID" ] && ! kill -0 "$API_PID" 2>/dev/null; then
    echo -e "${RED}API process exited unexpectedly.${NC}"
fi
if [ -n "$UI_PID" ] && ! kill -0 "$UI_PID" 2>/dev/null; then
    echo -e "${RED}UI process exited unexpectedly.${NC}"
fi

# Clean up the other
cleanup
