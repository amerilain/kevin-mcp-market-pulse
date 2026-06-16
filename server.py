#!/usr/bin/env python3
"""
Market Pulse MCP Server
=======================
Model Context Protocol server for market data — exposes real-time market intelligence
as AI-accessible tools. Runs over stdio (compatible with claude_desktop_config.json
or mcporter).

Tools:
  get_market_regime       — Current market regime (BULL/BEAR/CHAOS) + confidence
  get_crypto_prices       — BTC, ETH prices with 24h change
  get_equities_prices     — SPY, QQQ prices with levels
  get_polymarket_top_markets — Top prediction markets by volume
  get_key_levels          — Daily ranges for BTC, ETH, SPY, QQQ
  get_full_briefing       — Latest full market briefing as JSON
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess
import sys
import time  # noqa: F401
import traceback
from datetime import datetime, timezone
from pathlib import Path  # noqa: F401
from typing import Any

# ── MCP SDK ──────────────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("market-pulse-mcp")

# ── Constants ────────────────────────────────────────────────────────────────

TOOL_PATHS = {
    "yf": "/opt/kevin-tools/yf",
    "regime": "/opt/kevin-tools/regime",
    "polymarket": "/opt/kevin-tools/polymarket",
    "polymarket_signals": "/opt/kevin-tools/polymarket-signals",
    "sentiment": "/opt/kevin-tools/sentiment",
}

LOG_DIR = "/workspace/logs"
TOOL_TIMEOUT = 25  # seconds per subprocess call

# ── MCP Server Initialization ────────────────────────────────────────────────

mcp = FastMCP(
    "market-pulse",
    instructions="Real-time market data server for crypto, equities, sentiment, and prediction markets",
)


# ── Utility Helpers ──────────────────────────────────────────────────────────


def _run_tool(tool: str, args: list[str] | None = None, timeout: int = TOOL_TIMEOUT) -> str:
    """Run a kevin-tool subprocess and return stdout.

    Args:
        tool: Tool key from TOOL_PATHS (e.g. 'yf', 'regime').
        args: Extra CLI arguments.
        timeout: Max seconds to wait for completion.

    Returns:
        Standard output as string.

    Raises:
        RuntimeError: If the tool is unknown or the subprocess fails.
    """
    tool_path = TOOL_PATHS.get(tool)
    if not tool_path:
        raise RuntimeError(f"Unknown tool: {tool}")
    if not os.path.exists(tool_path):
        # Fall back to bare command in PATH
        tool_path = tool

    cmd = [tool_path] + (args or [])
    logger.debug("Running: %s", " ".join(cmd))

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()[:500]
            logger.warning("Tool %s returned code %d: %s", tool, proc.returncode, stderr)
            # For tools that return data even with non-zero exit, still return stdout
        return proc.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Tool '{tool}' timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError(f"Tool '{tool}' not found at {tool_path}")
    except Exception as e:
        raise RuntimeError(f"Tool '{tool}' failed: {e}")


def _parse_yf_price_output(output: str) -> dict[str, Any] | None:
    """Parse yf price output into structured dict.

    yf uses Rich-formatted box-drawing output like:
    │ BTC-USD                       │
    │ Price: $64409.75              │
    │ Change: +937.41 (+1.48%)      │

    Strips box-drawing chars first, then extracts data.

    Returns: {symbol, price, change, change_pct}
    """
    try:
        # Strip all Unicode box-drawing characters before parsing
        clean = re.sub(
            r'[\u2500-\u257f\u2580-\u259f]',
            '', output
        ).strip()

        symbol_match = re.search(r'^([A-Z]+[-\.]?[A-Z0-9]*)$', clean, re.MULTILINE)
        price_match = re.search(r'Price:\s*\$?([0-9,]+\.?\d*)', clean)
        change_match = re.search(
            r'Change:\s*([+-]?[0-9,.]+)\s*\(([+-]?[0-9,.]+%)\)', clean
        )

        symbol = symbol_match.group(1) if symbol_match else None
        price = price_match.group(1).replace(',', '') if price_match else None
        change = None
        change_pct = None
        if change_match:
            change = change_match.group(1).replace(',', '')
            change_pct = change_match.group(2)

        result: dict[str, Any] = {}
        if symbol:
            result['symbol'] = symbol
        if price:
            result['price'] = round(float(price), 2)
        if change:
            result['change'] = round(float(change), 2)
        if change_pct:
            result['change_pct'] = change_pct  # e.g. '+1.48%'
        return result if result else None
    except Exception as e:
        logger.warning('Failed to parse yf output: %s', e)
        return None



def _parse_regime_json(output: str) -> dict[str, Any] | dict[str, Any]:
    """Parse regime --json output into dict."""
    try:
        parsed = json.loads(output)
        if isinstance(parsed, dict) and parsed.get("ok"):
            return parsed["data"]
        if isinstance(parsed, dict) and "regime" in parsed:
            return parsed
        return parsed
    except json.JSONDecodeError:
        return {"regime": "UNKNOWN", "confidence": 0, "raw": output[:500]}


def _find_latest_briefing() -> str | None:
    """Find the most recent briefing-*.txt file."""
    pattern = os.path.join(LOG_DIR, "briefing-*.txt")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def _parse_briefing_to_json(filepath: str) -> dict[str, Any]:
    """Parse a briefing text file into structured JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    def _int_safe(val: Any, default: int = 0) -> int:
        """Safely convert a value to int, returning default on failure."""
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def _float_safe(val: Any, default: float = 0.0) -> float:
        """Safely convert a value to float, returning default on failure."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    # Extract sections
    result: dict[str, Any] = {
        "source_file": os.path.basename(filepath),
        "timestamp": datetime.fromtimestamp(
            os.path.getmtime(filepath), tz=timezone.utc
        ).isoformat(),
    }

    # Regime
    regime_match = re.search(
        r"MARKET REGIME:\s*(\w+)\s*\(confidence:\s*(\d+)%\)", text
    )
    if regime_match:
        result["regime"] = {
            "name": regime_match.group(1),
            "confidence_pct": _int_safe(regime_match.group(2)),
        }

    # SPY indicators
    spy_match = re.search(r"SPY Price:\s*\$?\s*([0-9,.]+)", text)
    sma50_match = re.search(r"SMA\(50\):\s*\$?\s*([0-9,.]+)", text)
    sma200_match = re.search(r"SMA\(200\):\s*\$?\s*([0-9,.]+)", text)
    vix_match = re.search(r"VIX:\s*([0-9.]+)", text)
    spy_change_match = re.search(r"SPY:.*?([+-]?[0-9.]+%)", text)

    indicators: dict[str, Any] = {}
    if spy_match:
        indicators["spy_price"] = _float_safe(spy_match.group(1).replace(",", ""))
    if sma50_match:
        indicators["sma_50"] = _float_safe(sma50_match.group(1).replace(",", ""))
    if sma200_match:
        indicators["sma_200"] = _float_safe(sma200_match.group(1).replace(",", ""))
    if vix_match:
        indicators["vix"] = _float_safe(vix_match.group(1))
    if spy_change_match:
        indicators["spy_change_pct"] = spy_change_match.group(1)
    if indicators:
        result["indicators"] = indicators

    # Crypto
    btc_match = re.search(r"BTC:\s*\$?([0-9,]+\.?\d*)\s*\(([+-][0-9.]+%)\)", text)
    eth_match = re.search(r"ETH:\s*\$?([0-9,]+\.?\d*)\s*\(([+-][0-9.]+%)\)", text)

    crypto: dict[str, Any] = {}
    if btc_match:
        crypto["btc"] = {
            "price": _float_safe(btc_match.group(1).replace(",", "")),
            "change_pct": btc_match.group(2),
        }
    if eth_match:
        crypto["eth"] = {
            "price": _float_safe(eth_match.group(1).replace(",", "")),
            "change_pct": eth_match.group(2),
        }
    if crypto:
        result["crypto"] = crypto

    # Equities
    spy_eq_match = re.search(r"SPY:\s*\$?([0-9,]+\.?\d*)\s*\(([+-][0-9.]+%)\)", text)
    qqq_match = re.search(r"QQQ:\s*\$?([0-9,]+\.?\d*)\s*\(([+-][0-9.]+%)\)", text)

    equities: dict[str, Any] = {}
    if spy_eq_match:
        equities["spy"] = {
            "price": _float_safe(spy_eq_match.group(1).replace(",", "")),
            "change_pct": spy_eq_match.group(2),
        }
    if qqq_match:
        equities["qqq"] = {
            "price": _float_safe(qqq_match.group(1).replace(",", "")),
            "change_pct": qqq_match.group(2),
        }
    if equities:
        result["equities"] = equities

    # Sentiment — extract from the SENTIMENT section only
    sentiment_entries: list[dict[str, Any]] = []
    text_lines = text.split("\n")
    in_sentiment = False
    in_prediction_markets = False
    for line in text_lines:
        # Track sections
        if "SENTIMENT" in line.upper() and "Symbol" not in line:
            in_sentiment = True
            in_prediction_markets = False
            continue
        if "PREDICTION MARKETS" in line.upper():
            in_sentiment = False
            in_prediction_markets = True
            continue

        if in_sentiment:
            parts = line.strip().split()
            if (
                len(parts) >= 4
                and parts[0].isupper()
                and len(parts[0]) <= 6  # Ticker symbols are short
                and parts[0] != "Symbol"
            ):
                score_match = re.search(r"[-+]?\d+\.?\d*", parts[1])
                mentions_match = re.search(r"\d+", parts[3])
                sentiment_entries.append({
                    "symbol": parts[0],
                    "score": _float_safe(score_match.group()) if score_match else 0.0,
                    "signal": parts[2] if len(parts) > 2 else "neutral",
                    "mentions": _int_safe(mentions_match.group()) if mentions_match else 0,
                    "direction": parts[2].replace("ish", "") if len(parts) > 2 else "neutral",
                })
    if sentiment_entries:
        result["sentiment"] = sentiment_entries

    # Prediction markets
    pm_markets: list[dict[str, Any]] = []
    in_pm = False
    pm_section_found = False
    for line in text_lines:
        if "PREDICTION MARKETS" in line.upper():
            in_pm = True
            pm_section_found = True
            continue
        if pm_section_found and "MARKET REGIME" in line.upper():
            in_pm = False
        if not in_pm:
            continue

        # Match market question lines: "Will ...?" or "Is ...?" or "Does ...?" specific patterns
        q_match = re.match(r"^(Will |Is |Does |Are |Has |Can )", line.strip())
        if q_match and "?" in line:
            pm_markets.append({"question": line.strip()})
            continue

        # Match data lines: "   Yes: X% | No: Y% | 24h: $Z"
        if pm_markets and "Yes:" in line:
            yes_match = re.search(r"Yes:\s*([0-9.]+)%", line)
            no_match = re.search(r"No:\s*([0-9.]+)%", line)
            vol_match = re.search(r"24h:\s*\$?([0-9,.]+)", line)
            if pm_markets:
                m = pm_markets[-1]
                if yes_match:
                    m["yes_pct"] = _float_safe(yes_match.group(1))
                if no_match:
                    m["no_pct"] = _float_safe(no_match.group(1))
                if vol_match:
                    m["volume_24h"] = _float_safe(vol_match.group(1).replace(",", ""))

    if pm_markets:
        result["prediction_markets"] = pm_markets

    # Full text fallback (truncated)
    result["raw_text"] = text[:2000] + ("..." if len(text) > 2000 else "")

    return result


def _safe_json_output(data: Any) -> str:
    """Convert data to pretty-printed JSON string."""
    return json.dumps(data, indent=2, default=str)


def _format_error(message: str) -> str:
    """Return a structured error JSON string."""
    return _safe_json_output({"ok": False, "error": message})


# ── MCP Tool Implementations ────────────────────────────────────────────────


@mcp.tool(
    name="get_market_regime",
    description="Get the current market regime (BULL_TREND, BEAR_TREND, HIGH_VOLATILITY, etc.) with confidence score and indicators like VIX, SPY price, and SMAs.",
)
def get_market_regime() -> str:
    """Detect the current market regime using VIX + SPY trend indicators."""
    try:
        output = _run_tool("regime", ["detect", "--json"])
        data = _parse_regime_json(output)
        return _safe_json_output({"ok": True, "data": data})
    except Exception as e:
        logger.error("get_market_regime failed: %s", traceback.format_exc())
        return _format_error(str(e))


@mcp.tool(
    name="get_crypto_prices",
    description="Get current Bitcoin (BTC) and Ethereum (ETH) prices with 24h percentage change.",
)
def get_crypto_prices() -> str:
    """Fetch BTC and ETH prices via Yahoo Finance."""
    try:
        results: dict[str, Any] = {}
        for symbol in ["BTC-USD", "ETH-USD"]:
            try:
                output = _run_tool("yf", ["price", symbol])
                parsed = _parse_yf_price_output(output)
                if parsed:
                    key = symbol.replace("-USD", "").lower()
                    results[key] = parsed
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", symbol, e)
                results[symbol.replace("-USD", "").lower()] = {"error": str(e)}

        return _safe_json_output({"ok": True, "data": results})
    except Exception as e:
        logger.error("get_crypto_prices failed: %s", traceback.format_exc())
        return _format_error(str(e))


@mcp.tool(
    name="get_equities_prices",
    description="Get current SPY (S&P 500 ETF) and QQQ (Nasdaq ETF) prices with change percentages.",
)
def get_equities_prices() -> str:
    """Fetch SPY and QQQ prices via Yahoo Finance."""
    try:
        results: dict[str, Any] = {}
        for symbol in ["SPY", "QQQ"]:
            try:
                output = _run_tool("yf", ["price", symbol])
                parsed = _parse_yf_price_output(output)
                if parsed:
                    results[symbol.lower()] = parsed
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", symbol, e)
                results[symbol.lower()] = {"error": str(e)}

        return _safe_json_output({"ok": True, "data": results})
    except Exception as e:
        logger.error("get_equities_prices failed: %s", traceback.format_exc())
        return _format_error(str(e))


@mcp.tool(
    name="get_polymarket_top_markets",
    description="Get top Polymarket prediction markets by 24-hour volume, with prices and market details.",
)
def get_polymarket_top_markets(limit: int = 10) -> str:
    """Fetch top Polymarket markets by volume and return structured data.

    Args:
        limit: Number of markets to return (default 10, max 50).
    """
    try:
        limit = min(max(1, limit), 50)
        output = _run_tool("polymarket", ["--json", "--top", "--limit", str(limit)])
        data = json.loads(output)

        # Transform into cleaner format
        markets = []
        for m in data if isinstance(data, list) else data.get("markets", data):
            try:
                prices = json.loads(m.get("outcomePrices", '["0","0"]'))
                markets.append({
                    "question": m.get("question", "Unknown")[:120],
                    "slug": m.get("slug", ""),
                    "yes_pct": round(float(prices[0]) * 100, 1) if prices else 0,
                    "no_pct": round(float(prices[1]) * 100, 1) if len(prices) > 1 else 0,
                    "volume_24h": m.get("volume24hr", 0) or 0,
                    "volume_total": m.get("volumeNum", 0) or 0,
                    "liquidity": m.get("liquidityNum", 0) or 0,
                    "end_date": m.get("endDate", "")[:10] if m.get("endDate") else None,
                    "closed": m.get("closed", False),
                })
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning("Skipping malformed market: %s", e)
                continue

        return _safe_json_output({
            "ok": True,
            "data": {
                "count": len(markets),
                "markets": markets,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        })
    except Exception as e:
        logger.error("get_polymarket_top_markets failed: %s", traceback.format_exc())
        return _format_error(str(e))


@mcp.tool(
    name="get_key_levels",
    description="Get key price levels and daily ranges for BTC, ETH, SPY, and QQQ from Yahoo Finance.",
)
def get_key_levels() -> str:
    """Fetch daily price ranges for major assets."""
    symbols = {
        "btc": "BTC-USD",
        "eth": "ETH-USD",
        "spy": "SPY",
        "qqq": "QQQ",
    }
    try:
        results: dict[str, Any] = {}
        for key, symbol in symbols.items():
            try:
                output = _run_tool("yf", ["history", symbol, "5d"])
                # Strip box-drawing characters — remaining format is space-delimited
                clean = re.sub(
                    r'[\u2500-\u257f\u2580-\u259f]',
                    '', output
                ).strip()
                lines = clean.split('\n')

                prices = []
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('Date') or line.startswith(symbol):
                        continue
                    # After stripping box-drawing, format: Date $Open $High $Low $Close Volume
                    # e.g., "2026-06-13  $63543.13  $64525.84  $63458.68  $64492.29  16,308,692,992"
                    parts = line.split()
                    if len(parts) >= 5 and parts[0].startswith('20'):
                        try:
                            prices.append({
                                'date': parts[0],
                                'open': float(parts[1].replace('$','').replace(',','')),
                                'high': float(parts[2].replace('$','').replace(',','')),
                                'low': float(parts[3].replace('$','').replace(',','')),
                                'close': float(parts[4].replace('$','').replace(',','')),
                            })
                        except (ValueError, IndexError):
                            continue

                if prices:
                    closes = [p['close'] for p in prices]
                    highs = [p['high'] for p in prices]
                    lows = [p['low'] for p in prices]
                    latest = prices[-1]
                    results[key] = {
                        'symbol': symbol,
                        'current': round(latest['close'], 2),
                        'day_high': round(latest['high'], 2),
                        'day_low': round(latest['low'], 2),
                        'day_open': round(latest['open'], 2),
                        '5d_high': round(max(highs), 2),
                        '5d_low': round(min(lows), 2),
                        '5d_range': f"${min(lows):,.2f} - ${max(highs):,.2f}",
                    }
                else:
                    results[key] = {'symbol': symbol, 'error': 'No price data available'}
            except Exception as e:
                logger.warning('Failed to fetch key levels for %s: %s', key, e)
                results[key] = {'symbol': symbol, 'error': str(e)}

        return _safe_json_output({"ok": True, "data": results})
    except Exception as e:
        logger.error('get_key_levels failed: %s', traceback.format_exc())
        return _format_error(str(e))


@mcp.tool(
    name="get_full_briefing",
    description="Get the latest full market briefing as structured JSON, including regime, crypto prices, equities, sentiment, and prediction markets.",
)
def get_full_briefing() -> str:
    """Parse the latest briefing file into structured JSON data."""
    try:
        briefing_path = _find_latest_briefing()
        if not briefing_path:
            return _format_error("No briefing file found in /workspace/logs/")

        data = _parse_briefing_to_json(briefing_path)
        return _safe_json_output({"ok": True, "data": data})
    except Exception as e:
        logger.error("get_full_briefing failed: %s", traceback.format_exc())
        return _format_error(str(e))


# ── Status / Health Check ────────────────────────────────────────────────────


@mcp.tool(
    name="health_check",
    description="Check server health, tool availability, and last briefing file status.",
)
def health_check() -> str:
    """Perform a health check on the MCP server and its toolchain."""
    results: dict[str, Any] = {
        "server": "market-pulse-mcp",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools": {},
    }

    for tool_name, tool_path in TOOL_PATHS.items():
        results["tools"][tool_name] = {
            "path": tool_path,
            "available": os.path.exists(tool_path),
        }

    briefing_path = _find_latest_briefing()
    results["briefing_file"] = {
        "found": briefing_path is not None,
        "latest": os.path.basename(briefing_path) if briefing_path else None,
    }

    return _safe_json_output({"ok": True, "data": results})


# ── Main Entry Point ─────────────────────────────────────────────────────────


def main():
    """Run the MCP server over stdio."""
    # Quick check for --help or --version
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Market Pulse MCP Server")
        print()
        print("Usage:")
        print("  python3 server.py              # Run MCP server (stdio mode)")
        print("  python3 server.py --help       # This help")
        print("  python3 server.py --health     # Quick health check (one-shot)")
        print()
        print("Tools:")
        print("  get_market_regime       — Market regime + confidence + indicators")
        print("  get_crypto_prices       — BTC, ETH prices + 24h change")
        print("  get_equities_prices     — SPY, QQQ prices + change")
        print("  get_polymarket_top_markets — Top prediction markets by volume")
        print("  get_key_levels          — Daily ranges for BTC, ETH, SPY, QQQ")
        print("  get_full_briefing       — Complete market briefing as JSON")
        print("  health_check            — Server and tool health")
        return

    if "--health" in sys.argv:
        print(health_check())
        return

    # Log startup
    logger.info(
        "Market Pulse MCP Server starting (PID=%d, tools in %s)",
        os.getpid(),
        ", ".join(TOOL_PATHS.keys()),
    )

    # Run server over stdio — this is the standard MCP transport
    # AI hosts (Claude Desktop, Cline, etc.) connect via stdio.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
