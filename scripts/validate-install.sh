#!/bin/bash
# LobKit Backend Validation Script
# Run this on a FRESH Mac to validate the install sequence before building the UI around it.
# Usage: bash validate-install.sh --telegram-token "your-bot-token" --anthropic-key "sk-ant-..."
#
# What this tests:
#   1. Prerequisites (Homebrew, Node, Git)
#   2. OpenClaw install via curl | bash
#   3. Config patch (model provider + channel)
#   4. Gateway daemon install
#   5. Health check

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

TELEGRAM_TOKEN=""
ANTHROPIC_KEY=""
DRY_RUN=0

for arg in "$@"; do
  case $arg in
    --telegram-token=*) TELEGRAM_TOKEN="${arg#*=}" ;;
    --telegram-token) shift; TELEGRAM_TOKEN="$1" ;;
    --anthropic-key=*) ANTHROPIC_KEY="${arg#*=}" ;;
    --anthropic-key) shift; ANTHROPIC_KEY="$1" ;;
    --dry-run) DRY_RUN=1 ;;
  esac
done

ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${YELLOW}·${NC} $*"; }
fail() { echo -e "${RED}✗${NC} $*"; exit 1; }
section() { echo -e "\n${BOLD}$*${NC}"; }

section "[1/5] Prerequisites"

# Homebrew
if command -v brew &>/dev/null; then
  ok "Homebrew found: $(brew --version | head -1)"
else
  info "Homebrew not found — installing..."
  if [[ $DRY_RUN -eq 0 ]]; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ok "Homebrew installed"
  else
    info "[DRY RUN] Would install Homebrew"
  fi
fi

# Node
if command -v node &>/dev/null; then
  NODE_VER=$(node --version)
  ok "Node found: $NODE_VER"
  # Check minimum version (22.16+)
  NODE_MAJOR=$(echo "$NODE_VER" | sed 's/v//' | cut -d. -f1)
  if [[ $NODE_MAJOR -lt 22 ]]; then
    info "Node $NODE_VER is below minimum (22.16+) — will upgrade"
  fi
else
  info "Node not found — will be installed by OpenClaw installer"
fi

# Git
if command -v git &>/dev/null; then
  ok "Git found: $(git --version)"
else
  info "Git not found — will be installed by OpenClaw installer"
fi

section "[2/5] Install OpenClaw"

if command -v openclaw &>/dev/null; then
  ok "OpenClaw already installed: $(openclaw --version 2>/dev/null || echo 'version unknown')"
else
  info "Installing OpenClaw..."
  if [[ $DRY_RUN -eq 0 ]]; then
    curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard
    ok "OpenClaw installed"
  else
    info "[DRY RUN] Would run: curl -fsSL https://openclaw.ai/install.sh | bash -s -- --no-onboard"
  fi
fi

section "[3/5] Configure OpenClaw"

# Anthropic model config
if [[ -n "$ANTHROPIC_KEY" ]]; then
  info "Configuring Anthropic as model provider..."
  PATCH=$(cat <<JSON
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-5"
    }
  },
  "auth": {
    "profiles": [
      {
        "id": "anthropic-default",
        "provider": "anthropic",
        "apiKey": "$ANTHROPIC_KEY"
      }
    ]
  }
}
JSON
)
  if [[ $DRY_RUN -eq 0 ]]; then
    echo "$PATCH" > /tmp/lobkit-model-patch.json
    openclaw config patch --file /tmp/lobkit-model-patch.json
    rm /tmp/lobkit-model-patch.json
    ok "Model provider configured"
  else
    info "[DRY RUN] Would patch model config (Anthropic)"
  fi
else
  info "No API key provided — skipping model config (required for a real install)"
fi

# Telegram channel config
if [[ -n "$TELEGRAM_TOKEN" ]]; then
  info "Configuring Telegram channel..."
  PATCH=$(cat <<JSON
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "$TELEGRAM_TOKEN"
    }
  }
}
JSON
)
  if [[ $DRY_RUN -eq 0 ]]; then
    echo "$PATCH" > /tmp/lobkit-telegram-patch.json
    openclaw config patch --file /tmp/lobkit-telegram-patch.json
    rm /tmp/lobkit-telegram-patch.json
    ok "Telegram channel configured"
  else
    info "[DRY RUN] Would patch Telegram config"
  fi
else
  info "No Telegram token provided — skipping channel config"
fi

section "[4/5] Install Gateway Daemon"

info "Installing LaunchAgent (gateway daemon)..."
if [[ $DRY_RUN -eq 0 ]]; then
  openclaw gateway install --force
  sleep 2
  openclaw gateway restart
  ok "Gateway daemon installed and started"
else
  info "[DRY RUN] Would run: openclaw gateway install --force && openclaw gateway restart"
fi

section "[5/5] Health Check"

if [[ $DRY_RUN -eq 0 ]]; then
  info "Waiting for gateway..."
  sleep 3
  STATUS=$(openclaw gateway status 2>&1)
  if echo "$STATUS" | grep -q "running\|listening\|18789"; then
    ok "Gateway is running ✓"
  else
    echo "$STATUS"
    fail "Gateway health check failed — see output above"
  fi

  info "Running openclaw doctor..."
  openclaw doctor --non-interactive 2>&1 | tail -5
  ok "Doctor check complete"
else
  info "[DRY RUN] Would check: openclaw gateway status"
  info "[DRY RUN] Would check: openclaw doctor --non-interactive"
fi

echo ""
echo -e "${GREEN}${BOLD}🦞 Validation complete!${NC}"
echo ""
echo "If all steps showed ✓, the LobKit install backend is working correctly."
echo "You should now be able to message your OpenClaw bot on Telegram."
echo ""
echo "To open the dashboard: openclaw dashboard"
echo "To check status:       openclaw gateway status"
