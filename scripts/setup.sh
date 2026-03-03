#!/bin/bash
# Stargate Setup - run once on a new machine (idempotent, safe to re-run)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
skip() { echo -e "  ${YELLOW}→${NC} $1 (already done)"; }
fail() { echo -e "  ${RED}✗${NC} $1"; exit 1; }
info() { echo -e "  ${CYAN}…${NC} $1"; }

echo ""
echo -e "${CYAN}Stargate Setup${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Check prerequisites ──────────────────────────────────────────

echo ""
echo "Checking prerequisites..."

command -v python3 >/dev/null 2>&1 || fail "python3 not found. Install Python 3.12+: https://www.python.org/downloads/"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
ok "python3 ($PYTHON_VERSION)"

command -v node >/dev/null 2>&1 || fail "node not found. Install Node 20+: https://nodejs.org/"
NODE_VERSION=$(node --version 2>&1)
ok "node ($NODE_VERSION)"

command -v npm >/dev/null 2>&1 || fail "npm not found. Should come with Node."
NPM_VERSION=$(npm --version 2>&1)
ok "npm ($NPM_VERSION)"

if command -v claude >/dev/null 2>&1; then
    ok "claude CLI installed"
else
    echo -e "  ${YELLOW}⚠${NC} claude CLI not found. Install: https://docs.anthropic.com/en/docs/claude-code"
    echo -e "  ${YELLOW}⚠${NC} Stargate can still start, but sessions won't work without it."
fi

# ── 2. Backend: Python venv + dependencies ───────────────────────────

echo ""
echo "Setting up backend..."

cd "$ROOT_DIR/backend"

if [ -d "venv" ] && [ -f "venv/bin/python" ]; then
    skip "Python venv exists"
else
    info "Creating Python virtual environment..."
    python3 -m venv venv
    ok "Created venv"
fi

info "Installing Python dependencies..."
./venv/bin/pip install -q -r requirements.txt
ok "Python dependencies installed"

# ── 3. Frontend: npm install ─────────────────────────────────────────

echo ""
echo "Setting up frontend..."

cd "$ROOT_DIR/frontend"

if [ -d "node_modules" ] && [ -f "node_modules/.package-lock.json" ]; then
    skip "node_modules exists"
else
    info "Installing npm dependencies..."
    npm install
    ok "npm dependencies installed"
fi

# ── 4. Install Claude Code hooks ─────────────────────────────────────

echo ""
echo "Setting up hooks..."

HOOKS_SCRIPT="$ROOT_DIR/hooks/install-hooks.sh"
if [ -f "$HOOKS_SCRIPT" ]; then
    chmod +x "$HOOKS_SCRIPT"
    bash "$HOOKS_SCRIPT"
    ok "Claude Code hooks installed"
else
    echo -e "  ${YELLOW}⚠${NC} hooks/install-hooks.sh not found, skipping"
fi

# ── Done ─────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "  Run ./scripts/start.sh to start Stargate"
echo "  UI:  http://localhost:33400"
echo "  API: http://localhost:33401"
echo ""
