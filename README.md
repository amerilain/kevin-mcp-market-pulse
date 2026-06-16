# Market Pulse MCP Server

Real-time market intelligence delivered through the **Model Context Protocol (MCP)**.
Provides AI agents with structured market data — crypto prices, equity indices, regime
classification, sentiment signals, and Polymarket prediction markets.

## Features

| Tool | Description |
|------|-------------|
| `get_market_regime` | Market regime (BULL/BEAR/CHAOS) with confidence, VIX, SPY SMAs |
| `get_crypto_prices` | BTC, ETH prices with 24h change |
| `get_equities_prices` | SPY, QQQ prices with change percentages |
| `get_polymarket_top_markets` | Top prediction markets by 24h volume |
| `get_key_levels` | Daily ranges for BTC, ETH, SPY, QQQ |
| `get_full_briefing` | Complete market briefing as structured JSON |
| `health_check` | Server and tool health check |

## Quick Start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Make run.sh executable
chmod +x run.sh

# 3. Start server (stdio transport)
./run.sh

# 4. One-shot health check
./run.sh --health
```

## Usage with AI Hosts

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "market-pulse": {
      "command": "/path/to/market-pulse-mcp/run.sh",
      "args": []
    }
  }
}
```

### mcporter (CLI Access)

```bash
# Run tools directly via mcporter
mcporter call --stdio "./run.sh" get_market_regime
mcporter call --stdio "./run.sh" get_crypto_prices
mcporter call --stdio "./run.sh" get_polymarket_top_markets limit=5
```

### Cline / VS Code

Add to MCP server configuration:
```json
{
  "command": "/path/to/market-pulse-mcp/run.sh"
}
```

## Deploy as SaaS

### Option 1: HTTP SSE Transport (Basic)

The server uses stdio by default. For remote HTTP access, run it with an SSE adapter:

```bash
# Use Python's uvicorn to wrap the MCP server as an SSE endpoint
pip install uvicorn
python3 -c "
from mcp.server.fastmcp import FastMCP
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server.sse import SseServerTransport

# Import your market-pulse app
import sys
sys.path.insert(0, '.')
from server import mcp

app = Starlette(
    routes=[
        Mount('/', app=mcp.sse_app()),
    ],
)
uvicorn.run(app, host='0.0.0.0', port=8000)
"
```

### Option 2: Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Expose tools from host (kevin-tools)
VOLUME /opt/kevin-tools
VOLUME /workspace/logs

CMD ["./run.sh"]
```

Build and run:
```bash
docker build -t market-pulse-mcp .
docker run -d \
  -v /opt/kevin-tools:/opt/kevin-tools:ro \
  -v /workspace/logs:/workspace/logs:ro \
  market-pulse-mcp
```

### Option 3: systemd Service

```ini
[Unit]
Description=Market Pulse MCP Server
After=network.target

[Service]
Type=simple
ExecStart=/opt/market-pulse-mcp/run.sh
Restart=always
RestartSec=10
User=kevin
WorkingDirectory=/opt/market-pulse-mcp
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## Architecture

```
┌──────────────────┐     stdio/SSE     ┌─────────────────────────────┐
│                  │ ◄──────────────► │                             │
│   AI Host        │                   │   Market Pulse MCP Server  │
│   (Claude, etc.) │                   │                             │
│                  │                   │   ┌─────────────────────┐  │
└──────────────────┘                   │   │  FastMCP (mcp SDK)  │  │
                                       │   └────────┬────────────┘  │
                                       │            │                │
                                       │   ┌────────▼────────────┐  │
                                       │   │  Tool Adapters      │  │
                                       │   │  ┌──────┬──────┬──┐ │  │
                                       │   │  │ yf   │regime│pm│ │  │
                                       │   │  └──────┴──────┴──┘ │  │
                                       │   └────────┬────────────┘  │
                                       │            │                │
                                       │   ┌────────▼────────────┐  │
                                       │   │  /opt/kevin-tools/  │  │
                                       │   └─────────────────────┘  │
                                       └─────────────────────────────┘
```

## Data Sources

- **Yahoo Finance** (`yf`) — BTC, ETH, SPY, QQQ prices and history
- **Market Regime** (`regime`) — VIX + SPY SMA-based regime classification
- **Polymarket API** (`polymarket`, `polymarket-signals`) — Prediction market data
- **Sentiment** (`sentiment`) — Multi-source sentiment aggregation
- **Briefing Files** (`/workspace/logs/briefing-*.txt`) — Pre-generated market summaries

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKSPACE` | `/workspace` | Base directory for briefing files and logs |

## Error Handling

All tools return one of two JSON shapes:

**Success:**
```json
{
  "ok": true,
  "data": { ... }
}
```

**Error:**
```json
{
  "ok": false,
  "error": "Descriptive error message"
}
```

## Monitoring

```bash
# Health check (one-shot)
./run.sh --health

# Check logs
tail -f /workspace/market-pulse-mcp/logs/*.log  # or journalctl if run as systemd service
```

## License

Proprietary — Market Pulse SaaS
