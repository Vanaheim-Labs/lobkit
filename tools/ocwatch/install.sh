#!/usr/bin/env bash
# ocwatch installer — copies ocwatch to ~/.openclaw/bin/
set -euo pipefail

INSTALL_DIR="${HOME}/.openclaw/bin"
SCRIPT_URL="https://raw.githubusercontent.com/Vanaheim-Labs/lobkit/main/tools/ocwatch/ocwatch.py"

mkdir -p "$INSTALL_DIR"

echo "Installing ocwatch to ${INSTALL_DIR}/ocwatch..."

if command -v curl &>/dev/null; then
    curl -sL "$SCRIPT_URL" -o "${INSTALL_DIR}/ocwatch"
elif command -v wget &>/dev/null; then
    wget -qO "${INSTALL_DIR}/ocwatch" "$SCRIPT_URL"
else
    echo "Error: curl or wget required" >&2
    exit 1
fi

chmod +x "${INSTALL_DIR}/ocwatch"

# Check if ~/.openclaw/bin is in PATH
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "Add to your shell profile:"
    echo "  export PATH=\"\$HOME/.openclaw/bin:\$PATH\""
    echo ""
fi

echo "Done. Run 'ocwatch -v --tail 20' to start watching."
