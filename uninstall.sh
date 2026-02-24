#!/usr/bin/env bash
set -euo pipefail

# granola-to-markdown uninstaller
# Removes MCP config (if present), GranolaMCP, and launchd agent.
# Does NOT remove your exported meeting notes.

MCP_INSTALL_DIR="$HOME/.local/share/granola-mcp"
MCP_CONFIG="$HOME/.mcp.json"
LAUNCHD_LABEL="com.granola-to-markdown.sync"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"

info()  { printf "\\033[1;34m==>\\033[0m %s\\n" "$1"; }
ok()    { printf "\\033[1;32m OK\\033[0m %s\\n" "$1"; }
warn()  { printf "\\033[1;33mWARN\\033[0m %s\\n" "$1"; }

# ---------------------------------------------------------------------------
# Step 1: Unload and remove launchd agent
# ---------------------------------------------------------------------------

info "Checking launchd agent..."
if [[ -f "$LAUNCHD_PLIST" ]]; then
    launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    rm -f "$LAUNCHD_PLIST"
    ok "Launchd agent removed"
else
    ok "No launchd agent found (skipping)"
fi

# ---------------------------------------------------------------------------
# Step 2: Remove granola-mcp from ~/.mcp.json
# ---------------------------------------------------------------------------

info "Removing MCP server config..."
if [[ -f "$MCP_CONFIG" ]]; then
    python3 << 'PYEOF'
import json
import os

mcp_path = os.path.expanduser("~/.mcp.json")

try:
    with open(mcp_path, "r") as f:
        config = json.load(f)
except (json.JSONDecodeError, IOError):
    print("  Could not parse ~/.mcp.json — skipping")
    exit(0)

servers = config.get("mcpServers", {})
if "granola-mcp" in servers:
    del servers["granola-mcp"]
    with open(mcp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print("  Removed granola-mcp from ~/.mcp.json")
else:
    print("  granola-mcp not found in ~/.mcp.json (skipping)")
PYEOF
    ok "MCP config cleaned"
else
    ok "No ~/.mcp.json found (skipping)"
fi

# ---------------------------------------------------------------------------
# Step 3: Remove GranolaMCP installation
# ---------------------------------------------------------------------------

info "Removing GranolaMCP..."
if [[ -d "$MCP_INSTALL_DIR" ]]; then
    rm -rf "$MCP_INSTALL_DIR"
    ok "Removed $MCP_INSTALL_DIR"
else
    ok "GranolaMCP not found at $MCP_INSTALL_DIR (skipping)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "-------------------------------------------------------"
echo "  granola-to-markdown uninstalled"
echo "-------------------------------------------------------"
echo ""
echo "  Your exported meeting notes were NOT removed."
echo "  They are still in the output directory you configured"
echo "  (default: ~/granola-notes)."
echo ""
echo "  To delete them manually:"
echo "    rm -rf <your-output-dir>"
echo ""
