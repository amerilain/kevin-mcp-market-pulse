#!/usr/bin/env bash
# ==============================================================================
# Market Pulse MCP Server — Runner Script
# ==============================================================================
# Starts the Market Pulse MCP server over stdio transport.
# Compatible with:
#   - Claude Desktop (via claude_desktop_config.json)
#   - Cline / VS Code LM API
#   - mcporter (mcporter call --stdio "./run.sh" tool_name arg=value)
#   - Any MCP-compatible host
#
# Usage:
#   ./run.sh                    # Run server (stdio mode, default)
#   ./run.sh --help             # Show help
#   ./run.sh --health           # One-shot health check
#   ./run.sh --daemon           # NOT YET IMPLEMENTED (reserved for future)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
SERVER_PY="${SCRIPT_DIR}/server.py"

mkdir -p "${LOG_DIR}"

# ── Dependency check ─────────────────────────────────────────────────────────

if ! python3 -c "import mcp" 2>/dev/null; then
    echo "[market-pulse-mcp] Installing dependencies (mcp package)..." >&2
    pip3 install --break-system-packages -r "${SCRIPT_DIR}/requirements.txt" 2>&1 \
        | tail -3
fi

# ── Tool availability check ───────────────────────────────────────────────────

check_tool() {
    local tool="$1"
    local path="$2"
    if [ -x "$path" ]; then
        return 0
    fi
    return 1
}

MISSING_TOOLS=0
for tool in yf regime polymarket polymarket-signals sentiment; do
    path="/opt/kevin-tools/$tool"
    if ! check_tool "$tool" "$path"; then
        echo "[market-pulse-mcp] WARNING: Tool '$tool' not found at $path" >&2
        MISSING_TOOLS=$((MISSING_TOOLS + 1))
    fi
done

if [ "$MISSING_TOOLS" -gt 0 ]; then
    echo "[market-pulse-mcp] WARNING: $MISSING_TOOLS tool(s) unavailable. Some tools may not work." >&2
fi

# ── Execute ──────────────────────────────────────────────────────────────────

echo "[market-pulse-mcp] Starting server..." >&2
echo "[market-pulse-mcp] PID: $$" >&2
echo "[market-pulse-mcp] Logs: ${LOG_DIR}" >&2

exec python3 "${SERVER_PY}" "$@"
