#!/usr/bin/env bash
set -euo pipefail

# granola-to-markdown installer
# Exports Granola meetings as markdown. Optionally installs GranolaMCP for Claude Code.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MCP_INSTALL_DIR="$HOME/.local/share/granola-mcp"
MCP_CONFIG="$HOME/.mcp.json"
GRANOLA_CACHE="$HOME/Library/Application Support/Granola/cache-v4.json"
LAUNCHD_LABEL="com.granola-to-markdown.sync"
LAUNCHD_PLIST="$HOME/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"

# Defaults
OUTPUT_DIR="$HOME/granola-notes"
WITH_MCP=false
WITH_LAUNCHD=false
FORCE=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info()  { printf "\\033[1;34m==>\\033[0m %s\\n" "$1"; }
ok()    { printf "\\033[1;32m OK\\033[0m %s\\n" "$1"; }
warn()  { printf "\\033[1;33mWARN\\033[0m %s\\n" "$1"; }
error() { printf "\\033[1;31mERROR\\033[0m %s\\n" "$1" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: ./install.sh [OPTIONS]

Options:
  --with-mcp           Also install GranolaMCP server for Claude Code
  --with-launchd       Install launchd agent for automatic sync every 30 min
  --output-dir <path>  Output directory for markdown files (default: ~/granola-notes)
  --force              Force reinstall even if components already exist
  --help               Show this help message

Examples:
  ./install.sh
  ./install.sh --with-mcp --with-launchd
  ./install.sh --output-dir ~/Documents/meetings --with-launchd
EOF
    exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
    case "$1" in
        --with-mcp)     WITH_MCP=true; shift ;;
        --with-launchd) WITH_LAUNCHD=true; shift ;;
        --output-dir)
            if [[ $# -lt 2 ]] || [[ "$2" == --* ]]; then
                error "--output-dir requires a path argument"
            fi
            OUTPUT_DIR="$2"; shift 2 ;;
        --force)        FORCE=true; shift ;;
        --help)         usage ;;
        *)              error "Unknown option: $1. Run with --help for usage." ;;
    esac
done

# ---------------------------------------------------------------------------
# Step 1: Check macOS
# ---------------------------------------------------------------------------

info "Checking platform..."
if [[ "$(uname)" != "Darwin" ]]; then
    error "This tool requires macOS. Detected: $(uname)"
fi
ok "macOS detected"

# ---------------------------------------------------------------------------
# Step 2: Check Python 3.12+
# ---------------------------------------------------------------------------

info "Checking Python..."
if ! command -v python3 &>/dev/null; then
    error "Python 3 not found. Install it from https://python.org or via 'brew install python'"
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 12 ]]; then
    error "Python 3.12+ required (found $PYTHON_VERSION). Upgrade via 'brew install python'"
fi
ok "Python $PYTHON_VERSION"

# ---------------------------------------------------------------------------
# Step 2b: Check git
# ---------------------------------------------------------------------------

info "Checking git..."
if ! command -v git &>/dev/null; then
    error "git not found. Install it via 'xcode-select --install' or 'brew install git'"
fi
ok "git available"

# ---------------------------------------------------------------------------
# Step 3: Check Granola installed
# ---------------------------------------------------------------------------

info "Checking Granola..."
if [[ ! -f "$GRANOLA_CACHE" ]]; then
    error "Granola cache not found at: $GRANOLA_CACHE

Install the Granola app from https://granola.ai and attend at least one meeting."
fi
ok "Granola cache found"

# ---------------------------------------------------------------------------
# Step 4: Optional MCP server setup (uv, GranolaMCP, ~/.mcp.json)
# ---------------------------------------------------------------------------

if [[ "$WITH_MCP" == "true" ]]; then

    info "Checking uv..."
    if command -v uv &>/dev/null; then
        ok "uv already installed ($(uv --version))"
    else
        info "Installing uv..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        # Source the env so uv is available in this session
        export PATH="$HOME/.local/bin:$PATH"
        if command -v uv &>/dev/null; then
            ok "uv installed ($(uv --version))"
        else
            error "Failed to install uv. Install manually: https://docs.astral.sh/uv/"
        fi
    fi

    info "Setting up GranolaMCP..."
    if [[ -d "$MCP_INSTALL_DIR" ]] && [[ "$FORCE" == "false" ]]; then
        info "Updating existing GranolaMCP installation..."
        git -C "$MCP_INSTALL_DIR" pull --quiet 2>/dev/null || warn "Could not update GranolaMCP (offline?)"
        ok "GranolaMCP up to date at $MCP_INSTALL_DIR"
    else
        if [[ -d "$MCP_INSTALL_DIR" ]]; then
            rm -rf "$MCP_INSTALL_DIR"
        fi
        mkdir -p "$(dirname "$MCP_INSTALL_DIR")"
        git clone --quiet https://github.com/pedramamini/GranolaMCP.git "$MCP_INSTALL_DIR"
        ok "GranolaMCP cloned to $MCP_INSTALL_DIR"
    fi

    info "Configuring MCP server..."

    python3 << 'PYEOF'
import json
import os
import sys

mcp_path = os.path.expanduser("~/.mcp.json")
install_dir = os.path.expanduser("~/.local/share/granola-mcp")
cache_path = os.path.expanduser("~/Library/Application Support/Granola/cache-v4.json")

# Load existing config or start fresh
config = {"mcpServers": {}}
if os.path.exists(mcp_path):
    try:
        with open(mcp_path, "r") as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError):
        print(f"  Warning: Could not parse {mcp_path}, backing up and recreating")
        os.rename(mcp_path, mcp_path + ".bak")
        config = {"mcpServers": {}}

if "mcpServers" not in config:
    config["mcpServers"] = {}

# Add or update granola-mcp entry
config["mcpServers"]["granola-mcp"] = {
    "command": "uv",
    "args": [
        "--directory", install_dir,
        "run", "python", "-m", "granola_mcp.mcp"
    ],
    "env": {
        "GRANOLA_CACHE_PATH": cache_path
    }
}

with open(mcp_path, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")

print(f"  Updated {mcp_path}")
PYEOF

    ok "MCP server configured in ~/.mcp.json"

fi

# ---------------------------------------------------------------------------
# Step 5: Create output directory
# ---------------------------------------------------------------------------

info "Setting up output directory..."
mkdir -p "$OUTPUT_DIR"
ok "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Step 6: Run initial sync
# ---------------------------------------------------------------------------

info "Running initial sync..."
python3 "$SCRIPT_DIR/sync.py" --output-dir "$OUTPUT_DIR" --verbose

# ---------------------------------------------------------------------------
# Step 7: Optional launchd setup
# ---------------------------------------------------------------------------

if [[ "$WITH_LAUNCHD" == "true" ]]; then
    info "Installing launchd agent for automatic sync..."

    PYTHON3_PATH="$(command -v python3)"
    SYNC_SCRIPT="$SCRIPT_DIR/sync.py"
    LOG_PATH="$OUTPUT_DIR/.sync.log"
    TEMPLATE="$SCRIPT_DIR/launchd/com.granola-to-markdown.sync.plist.template"

    if [[ ! -f "$TEMPLATE" ]]; then
        error "Launchd template not found at $TEMPLATE"
    fi

    # Unload existing if present
    if launchctl list "$LAUNCHD_LABEL" &>/dev/null; then
        launchctl unload "$LAUNCHD_PLIST" 2>/dev/null || true
    fi

    sed \
        -e "s|__PYTHON3__|$PYTHON3_PATH|g" \
        -e "s|__SYNC_SCRIPT__|$SYNC_SCRIPT|g" \
        -e "s|__OUTPUT_DIR__|$OUTPUT_DIR|g" \
        -e "s|__LOG_PATH__|$LOG_PATH|g" \
        "$TEMPLATE" > "$LAUNCHD_PLIST"

    launchctl load "$LAUNCHD_PLIST"
    ok "Launchd agent installed — syncs every 30 minutes"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "-------------------------------------------------------"
echo "  granola-to-markdown installed successfully!"
echo "-------------------------------------------------------"
echo ""
echo "  Meeting notes:   $OUTPUT_DIR"
if [[ "$WITH_MCP" == "true" ]]; then
echo "  MCP config:      $MCP_CONFIG"
echo "  GranolaMCP:      $MCP_INSTALL_DIR"
fi
if [[ "$WITH_LAUNCHD" == "true" ]]; then
echo "  Auto-sync:       Every 30 minutes (launchd)"
fi
echo ""
echo "  Next steps:"
if [[ "$WITH_MCP" == "true" ]]; then
echo "    - Open Claude Code and ask: \"show my recent meetings\""
fi
echo "    - Run sync manually: python3 $SCRIPT_DIR/sync.py --verbose"
if [[ "$WITH_LAUNCHD" == "false" ]]; then
echo "    - Enable auto-sync: ./install.sh --with-launchd"
fi
if [[ "$WITH_MCP" == "false" ]]; then
echo "    - Add live meeting search: ./install.sh --with-mcp"
fi
echo ""
