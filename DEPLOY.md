# MCP Market Pulse Server — Deploy Guide

## Overview
MCP server that exposes 7 market data tools via the Model Context Protocol.
Run anywhere Node.js + Python are available (VPS, Railway, Fly.io, home server).

## Quick Start (Local Dev)

```bash
cd market-pulse-mcp
pip install -r requirements.txt
python server.py
```

## Test with mcporter

```bash
mcporter add-stdio "market-pulse" "python $PWD/server.py"
mcporter call market-pulse get_market_regime
```

## Integration with OpenClaw

Add to `~/.openclaw/config.yaml`:
```yaml
mcpServers:
  market-pulse:
    command: python
    args: ["/path/to/market-pulse-mcp/server.py"]
```

Or for claude_desktop_config.json:
```json
{
  "mcpServers": {
    "market-pulse": {
      "command": "python",
      "args": ["/path/to/market-pulse-mcp/server.py"]
    }
  }
}
```

## Deployment Options

### Option 1: VPS (DigitalOcean $6/mo droplet)
```bash
# SSH in, clone repo
git clone <repo-url>
cd market-pulse-mcp
pip install -r requirements.txt

# Run as a service
sudo tee /etc/systemd/system/market-pulse-mcp.service <<EOF
[Unit]
Description=Market Pulse MCP Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/market-pulse-mcp
ExecStart=/usr/bin/python server.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now market-pulse-mcp
```

### Option 2: Railway/Fly.io
- Expose as HTTP SSE endpoint (needs wrapper)
- Revenue model: $10/mo API key access

### Option 3: HomeLab (existing OpenClaw host)
- Run as a regular process under supervisor/cron
- No additional hosting cost

## Revenue Model

**Target**: $10/mo per user
- Wrap MCP in a simple FastAPI proxy with API keys
- Offer via OpenAI marketplace or direct subscription
- Alternatively: keep free (MCP protocol) and monetize via newsletter upsell

## Tools Exposed

| Tool | Description |
|------|-------------|
| `get_market_regime` | BULL/BEAR/CHAOS regime + confidence |
| `get_crypto_prices` | BTC/ETH prices + 24h change |
| `get_equities_prices` | SPY/QQQ prices + levels |
| `get_polymarket_top_markets` | Top prediction markets by volume |
| `get_key_levels` | Daily ranges for BTC, ETH, SPY, QQQ |
| `get_full_briefing` | Complete latest market briefing as JSON |
| `get_market_overview` | All data in one call (regime + prices + markets) |

## On OpenClaw Moltbook

After deployment, announce on Moltbook with:
- Link to README
- Example query: "What's the current market regime?"
- Note: works with any MCP-compatible agent
