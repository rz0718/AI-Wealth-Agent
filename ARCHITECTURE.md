# Personalized AI Wealth Copilot — What's Built

## Overview

A CLI-based agentic financial analyst that has secure access to a user's real portfolio data (BigQuery) and live market data (yfinance). It learns the user's trading behavior over time through two complementary memory systems — conversation observations and daily trade analysis — and can apply expert investment frameworks on demand.

---

## Architecture

```
trading_agent/
├── agent.py                        # Main agentic loop (entry point)
├── auth.py                         # Security boundary — user_id isolation
├── config.py                       # Env var loader (API keys, BQ project)
├── tool_schemas.py                 # 7 tool definitions exposed to Claude
├── tool_registry.py                # Maps tool names → handler functions
│
├── agents/tools/
│   ├── finance_tools.py            # 4 BigQuery handlers
│   ├── market_tools.py             # 2 yfinance handlers
│   └── skill_tools.py             # Expert framework loader
│
├── memory/
│   ├── user_memory.md              # Persistent behavioral profile
│   ├── memory_manager.py           # Section-based read/write utilities
│   └── daily_trade_scan.py        # Daily BigQuery behavioral analysis
│
└── skills/
    ├── index.md                    # Skill directory (injected into system prompt)
    ├── ray_dalio/SKILL.md
    ├── warren_buffett/SKILL.md
    ├── charlie_munger/SKILL.md
    ├── benjamin_graham/SKILL.md
    ├── peter_lynch/SKILL.md
    ├── michael_burry/SKILL.md
    ├── cathie_wood/SKILL.md
    └── bill_ackman/SKILL.md
```

---

## Agent Loop (`agent.py`)

- Model: `claude-sonnet-4-6` with adaptive thinking
- System prompt rebuilt before each turn, injecting the current `user_memory.md` + skill index
- System prompt cached with `cache_control: ephemeral` to reduce token cost within a session
- Tool calls dispatched through `TOOL_HANDLERS` registry
- At session exit (quit / Ctrl+C): calls `claude-haiku-4-5-20251001` to extract `asset_interests` and behavioral signals from the transcript and appends them to **Conversation Observations** only

---

## Data Tools (7 tools)

| Tool | Source | What it returns |
|---|---|---|
| `get_trade_history` | BigQuery | Raw transactions (buy/sell/topup/cashout), last 30d default |
| `get_realised_pnl_transactions` | BigQuery | Per-trade realized P&L in IDR |
| `get_aggregate_pnl_summary` | BigQuery | Daily realized + unrealized portfolio P&L time-series |
| `get_current_positions` | BigQuery | Current holdings, AUM, portfolio weight %, unrealized return |
| `get_market_news` | yfinance | Recent headlines for a ticker or sector |
| `get_asset_price_metrics` | yfinance | Price, % change, high/low for 1D/1W/1M/YTD/1Y |
| `load_skill` | Local file | Full expert framework markdown loaded into context |

**Security:** `user_id` never appears in tool schemas. All BigQuery queries use parameterized bindings. `get_secure_user_id()` in `auth.py` is the single injection point.

---

## Memory System

### `memory/user_memory.md` — Persistent Profile

Four sections, each with a distinct owner:

| Section | Written by | Source of truth |
|---|---|---|
| **Trading Thesis** | `daily_trade_scan.py` | Actual trade patterns |
| **Behavioral Patterns** | `daily_trade_scan.py` | Trade frequency, disposition effect, flow direction |
| **Risk Profile** | `daily_trade_scan.py` | Portfolio concentration, instrument types, loss tolerance |
| **Conversation Observations** | `agent.py` session-end | What the user asked about; secondary corroborating signals |

Trades are authoritative — conversations only append observations, never overwrite the core profile.

### `memory/memory_manager.py` — Utilities

- `load_memory()` — reads full file, wraps in system prompt block
- `update_section(name, content)` — replaces a `## Section` block without touching others
- `append_observation(text)` — appends timestamped line to Conversation Observations
- `set_last_updated(source)` — updates the header timestamp

### `memory/daily_trade_scan.py` — Behavioral Analysis

Queries 3 BigQuery tables, computes behavioral signals, then calls `claude-haiku-4-5-20251001` to synthesize plain-English thesis + behaviors + risk profile.

**Metrics computed:**

| Signal | Reveals |
|---|---|
| Trades/week | Active vs. buy-and-hold |
| topup vs. cashout count | Accumulation vs. distribution phase |
| Distinct products traded | Concentrated bets vs. scatter-shot |
| High-risk instrument count (options/leverage) | True risk appetite |
| Avg winner vs. avg loser size | Disposition effect (cuts winners early / holds losers) |
| Max single loss accepted | Actual loss tolerance |
| Top asset class portfolio weight % | Concentration vs. diversification |
| Losing positions held unrealized | Loss aversion signal |

Run manually or via cron:
```
0 8 * * * cd /path/to/trading_agent && python memory/daily_trade_scan.py
```

---

## Expert Skills (8 frameworks)

Loaded on-demand via `load_skill` tool. Available: Ray Dalio (All-Weather), Warren Buffett (value), Charlie Munger (mental models), Benjamin Graham (margin of safety), Peter Lynch (consumer insight), Michael Burry (contrarian deep value), Cathie Wood (disruptive innovation), Bill Ackman (activist value).

Skill index is always in the system prompt so the agent knows what's available without loading the full content upfront.

---

## What's Not Built Yet

- **Auto-trigger for daily scan** — currently manual or cron; no startup stale-check in `agent.py`
- **Observation cap** — `append_observation` grows unboundedly; should cap at ~20 recent lines
- **Multi-user support** — `user_memory.md` is single-file; tied to whichever `CURRENT_USER_ID` is in `.env`
