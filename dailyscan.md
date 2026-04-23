# Behavioral Profiler (Memory Engine) — Implementation Plan

## Context


---

## Architecture Overview

Layer 2 — Trade pattern scan (daily batch)
scripts/daily_scan.py  ← run via cron or at agent startup if last_scan > 24h
    └── TradePatternAnalyzer.run_full_scan()
            ├── _fetch_all_trades()            # BigQuery: full history, no date limit
            ├── _fetch_price_at_date()         # yfinance: price on sell date + 7d prior
            ├── _detect_panic_sells()          # sell after >5% drop in prior 7 days
            ├── _compute_win_loss_by_asset()   # realized gain/loss per asset_type
            ├── _compute_hold_durations()      # avg days between buy and sell per asset
            ├── _detect_dip_buying()           # buys within 3 days of >5% drop
            └── _merge_and_write()             # same memory_writer, separate fields
```

New files: `agents/memory/` package, `scripts/daily_scan.py`. New dependency: `pyyaml`. Surgical changes: 3 lines in `agent.py`.

---


## Layer 2: TradePatternAnalyzer (`agents/memory/trade_pattern_analyzer.py`)

```python
class TradePatternAnalyzer:
    PANIC_DROP_THRESHOLD = 0.05   # 5% price drop in prior 7 days triggers panic check
    DIP_BUY_WINDOW_DAYS = 3       # buy within 3 days of a drop = dip-buying signal

    def __init__(self, user_id: str, client: anthropic.Anthropic): ...

    def run_full_scan(self) -> None:
        """Entry point. Fetches trades, runs all detectors, writes memory."""

    def _fetch_all_trades(self) -> list[dict]:
        """
        Calls handle_get_trade_history(start_date="2020-01-01", limit=1000).
        Uses the existing finance_tools handler directly — no new BQ code.
        """

    def _fetch_realised_pnl(self) -> list[dict]:
        """Calls handle_get_realised_pnl_transactions for full history."""

    def _fetch_price_at_date(self, product: str, date: str) -> float | None:
        """
        Maps product name → yfinance ticker (reuse existing sector_map from market_tools.py).
        Calls yf.Ticker(ticker).history(start=date-1d, end=date+1d).
        Returns closing price or None if unavailable.
        """

    def _detect_panic_sells(self, trades: list[dict]) -> dict:
        """
        For each 'sell' or 'cashout' transaction:
          1. Fetch price on sell_date and sell_date - 7 days
          2. If (price_7d_ago - price_sell) / price_7d_ago > PANIC_DROP_THRESHOLD → panic event
        Returns: { panic_sell_count, total_sells, panic_rate, examples: [...] }
        """

    def _compute_win_loss_by_asset(self, pnl_rows: list[dict]) -> dict:
        """
        Groups realised_gain_idr by asset_type.
        For each asset: wins (gain > 0), losses (gain <= 0), avg_gain_idr, total_gain_idr.
        Returns: { "crypto": {wins, losses, avg_gain_idr}, "gold": {...}, ... }
        """

    def _compute_hold_durations(self, trades: list[dict]) -> dict:
        """
        Pairs buy→sell by product. Computes days between buy date and sell date.
        Returns: { "crypto": avg_hold_days, "stock": avg_hold_days, ... }
        """

    def _detect_dip_buying(self, trades: list[dict]) -> dict:
        """
        For each 'buy' transaction:
          1. Fetch price on buy_date and buy_date - 7 days
          2. If price dropped > PANIC_DROP_THRESHOLD before buy → dip-buy signal
        Returns: { dip_buy_count, total_buys, dip_buy_rate }
        """

    def _build_scan_summary(self, results: dict) -> str:
        """Produces a one-line human-readable scan summary for evidence_log."""

    def _merge_scan_results(self, results: dict) -> None:
        """Merges scan results into YAML frontmatter + human sections via memory_writer."""
```

### Panic-sell detection algorithm

```
For each sell transaction S:
  ticker = product_to_ticker(S.product)          # e.g. "BTC" → "BTC-USD"
  price_sell   = yfinance.price(ticker, S.date)
  price_7d_ago = yfinance.price(ticker, S.date - 7d)
  if price_7d_ago is not None:
    drop_pct = (price_7d_ago - price_sell) / price_7d_ago
    if drop_pct >= 0.05:
      panic_sell_events += 1
      log: f"[{S.date}] Sold {S.product} after {drop_pct:.0%} drop"
```

### Extended memory frontmatter fields (Layer 2 additions)

```yaml
trade_patterns:
  last_scan: "2026-04-17"
  panic_sell_rate: 0.40          # 40% of sells followed a >5% drop
  panic_sell_count: 4
  total_sells: 10
  dip_buy_rate: 0.25
  panic_sell_examples:
    - "[2026-04-10] Sold BTC after -8.2% drop"
    - "[2026-03-22] Sold ETH after -6.1% drop"
win_loss_by_asset:
  crypto: {wins: 8, losses: 2, avg_gain_idr: 2100000, total_gain_idr: 16800000}
  gold:   {wins: 1, losses: 0, avg_gain_idr: 450000,  total_gain_idr: 450000}
hold_duration_by_asset:
  crypto: {avg_hold_days: 45}
  gold:   {avg_hold_days: 120}
```

### `scripts/daily_scan.py`

```python
#!/usr/bin/env python3
"""
Run standalone: python scripts/daily_scan.py
Or triggered from agent.py startup if last_scan > 24h ago.
"""
from auth import get_secure_user_id
from agents.memory.trade_pattern_analyzer import TradePatternAnalyzer
import anthropic
from config import ANTHROPIC_API_KEY

def main():
    user_id = get_secure_user_id()
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    analyzer = TradePatternAnalyzer(user_id=user_id, client=client)
    analyzer.run_full_scan()
    print("Scan complete. memory/user_memory.md updated.")

if __name__ == "__main__":
    main()
```

### Agent startup hook (agent.py — 2 additional lines)

```python
# After profiler = BehaviorProfiler(client), check if daily scan is due:
from agents.memory.trade_pattern_analyzer import TradePatternAnalyzer
_maybe_run_daily_scan(client)   # no-ops if last_scan < 24h ago
```

`_maybe_run_daily_scan` reads `trade_patterns.last_scan` from frontmatter; if today's date differs, runs `TradePatternAnalyzer.run_full_scan()` silently in background (wrapped in try/except).

---

## Layer 2 Fixtures — Simulated Trade History

Each fixture JSON gains a `price_history` section alongside `tool_responses`:

```json
{
  "archetype": "panic_seller",
  "expected_signals": ["panic_sell", "low_risk_tolerance", "reactive"],
  "tool_responses": {
    "get_trade_history": {
      "data": [
        {"created": "2026-04-10", "asset_type": "crypto", "product": "BTC",
         "activity": "sell"},
        {"created": "2026-03-22", "asset_type": "crypto", "product": "ETH",
         "activity": "sell"},
        {"created": "2026-04-08", "asset_type": "crypto", "product": "BTC",
         "activity": "buy"},
        {"created": "2026-03-18", "asset_type": "crypto", "product": "ETH",
         "activity": "buy"}
      ]
    },
    "get_realised_pnl_transactions": {
      "data": [
        {"day": "2026-04-10", "asset_type": "crypto", "product": "BTC",
         "realised_gain_idr": -500000},
        {"day": "2026-03-22", "asset_type": "crypto", "product": "ETH",
         "realised_gain_idr": -300000}
      ]
    }
  },
  "price_history": {
    "BTC-USD": {
      "2026-04-03": 85000,
      "2026-04-10": 78200
    },
    "ETH-USD": {
      "2026-03-15": 3200,
      "2026-03-22": 2990
    }
  }
}
```

The mock yfinance in `mock_tool_registry.py` intercepts `_fetch_price_at_date()` calls and returns values from `price_history`. The panic_seller fixture encodes a -8.2% BTC drop and -6.6% ETH drop before each sell — the test asserts `panic_sell_rate >= 0.5`.

---

## Layer 2 Test Cases (`tests/test_trade_pattern_analyzer.py`)

| Test | Assertion |
|------|-----------|
| `test_panic_seller_detected` | `panic_sell_rate >= 0.5`; `panic_sell_count == 2` |
| `test_income_investor_no_panic` | `panic_sell_count == 0`; `win_loss.bond.wins >= 3` |
| `test_crypto_bull_hold_duration` | `hold_duration.crypto.avg_hold_days >= 30` |
| `test_win_loss_computed_correctly` | Bond fixture: wins=3, losses=0 |
| `test_dip_buyer_detected` | crypto_bull fixture: `dip_buy_rate >= 0.3` |
| `test_scan_updates_last_scan_date` | After scan, `trade_patterns.last_scan == today` |
| `test_no_rerun_within_24h` | If `last_scan == today`, `run_full_scan` exits early without BQ call |
| `test_yfinance_unavailable_graceful` | If price unavailable, skip that sell — don't crash |

---

## BehaviorProfiler Class (`agents/memory/behavior_profiler.py`)

```python
class BehaviorProfiler:
    HAIKU_MODEL = "claude-haiku-4-5"

    def __init__(self, client: anthropic.Anthropic): ...

    def extract_and_update(
        self,
        user_turn: str,
        assistant_turn: str,
        tool_exchanges: list[dict],  # full message list from agent.py
    ) -> None:
        # Wraps everything in try/except — never crashes the main agent

    def _summarize_tool_results(self, tool_exchanges: list[dict]) -> str:
        # Parses tool_result messages; aggregates per asset_type without
        # sending raw BQ rows to Haiku. Output capped at ~500 chars.
        # e.g. "Trades: 12 crypto, 3 gold. Realized: crypto +Rp 2.1M (8W/2L). Largest: crypto 62%."

    def _build_extraction_prompt(
        self, user_turn, assistant_turn, tool_summary, existing_profile
    ) -> str:
        # Constructs system + user message. Total Haiku input: ~600–900 tokens.

    def _call_haiku(self, prompt: str) -> dict | None:
        # Returns parsed ExtractionResult JSON or None on failure

    def _merge_and_write(self, extraction: dict) -> None:
        # Reads frontmatter via yaml.safe_load, merges signals,
        # regenerates human-readable sections, calls atomic_write()
```

### ExtractionResult schema (what Haiku returns)

```json
{
  "signals_found": true,
  "asset_class_bias":    { "primary": "crypto",  "evidence": "..." },
  "risk_indicators":     { "tolerance": "high",  "panic_language_detected": false, "evidence": "..." },
  "analytical_framework":{ "preferred": ["news_driven", "technical"], "evidence": "..." },
  "trading_style":       { "style": "hold_through_volatility", "evidence": "..." },
  "new_observation":     "[2026-04-17] Crypto-focused, holds through dips, news-aware"
}
```

If `signals_found == false`, skip disk write entirely.

---

## Memory Format (`memory/user_memory.md`)

```markdown
---
profiler_version: 1
last_updated: "2026-04-17"
trading_thesis: "Crypto-concentrated speculator, high risk tolerance, holds through drawdowns"
asset_class_bias:
  primary: crypto
  secondary: gold
  evidence_log:
    - "[2026-04-17] 3 questions about BTC/ETH, largest position crypto at 62%"
risk_profile:
  tolerance: high
  panic_events: 0
  systematic_score: 7
  evidence_log:
    - "[2026-04-17] Held -17% unrealized loss on BTC without selling"
win_loss_by_asset:
  crypto: {wins: 8, losses: 2, avg_gain_idr: 2100000}
analytical_framework:
  preferred: [news_driven, technical]
  evidence_log:
    - "[2026-04-17] Asked market news + price metrics, no P/E questions"
trade_style:
  frequency: medium
  avg_hold_days: 45
  style: hold_through_volatility
---

# User Trading Profile
## Trading Thesis
...human-readable narrative regenerated from frontmatter on each write...
## Observed Behaviors
...
## Asset Class Performance
...
## Inferred Preferences
...
```

`evidence_log` lists are capped at last 10 entries. `_load_memory()` in `agent.py` is untouched — it reads the whole file as text; the frontmatter is harmless to Claude as structured context.

---

## Changes to `agent.py` (3 lines)

```python
# ~line 18 — add import
from agents.memory.behavior_profiler import BehaviorProfiler

# ~line 113 — after client = anthropic.Anthropic(...)
profiler = BehaviorProfiler(client)

# inside end_turn branch, after messages.append(assistant_text) and before break:
profiler.extract_and_update(
    user_turn=user_input,
    assistant_turn=assistant_text,
    tool_exchanges=messages,
)
```

---

## Testing Architecture

### Fixture JSON structure
Each `tests/fixtures/<archetype>.json` contains:
- `archetype` string
- `expected_thesis_keywords` list
- `tool_responses` dict keyed by tool name — mirrors real handler return format

### `mock_tool_registry.py`
```python
def make_mock_handlers(archetype: str) -> dict:
    """Returns TOOL_HANDLERS-compatible dict backed by fixture data."""
```

### `ConversationSimulator` (in `test_behavior_profiler.py`)
- Iterates through a conversation script
- For each turn: builds synthetic tool_exchanges from fixture responses
- Calls `profiler.extract_and_update()`
- After all turns: returns parsed frontmatter for assertions

### Pytest test cases
| Test | Assertion |
|------|-----------|
| `test_income_investor_thesis` | `trading_thesis` contains "income" or "dividend"; `primary == "bond"` |
| `test_panic_seller_detection` | `panic_events >= 1`; `tolerance == "low"` |
| `test_crypto_bull_bias` | `asset_class_bias.primary == "crypto"` |
| `test_value_investor_framework` | `"fundamental" in analytical_framework.preferred` |
| `test_no_signals_no_write` | `atomic_write` NOT called for a generic turn |
| `test_corrupt_yaml_no_crash` | Profiler handles malformed frontmatter without exception |
| `test_load_memory_unchanged` | `_load_memory()` returns non-empty string after profiler write |

---

## Implementation Order

1. `agents/memory/__init__.py` + `memory_writer.py`
2. Update `memory/user_memory.md` format (add YAML frontmatter with both Layer 1 + Layer 2 fields)
3. `agents/memory/behavior_profiler.py` (Layer 1)
4. `agents/memory/trade_pattern_analyzer.py` (Layer 2)
5. `scripts/daily_scan.py` (Layer 2 standalone runner)
6. `tests/fixtures/*.json` (all four archetypes — include `price_history` section)
7. `tests/mock_tool_registry.py` (mock both BQ handlers and yfinance price lookup)
8. `tests/conversation_scripts/*.py`
9. `tests/test_behavior_profiler.py` (Layer 1 tests)
10. `tests/test_trade_pattern_analyzer.py` (Layer 2 tests)
11. `agent.py` — 5-line integration (import + profiler + daily scan check)
12. `requirements.txt` — add `pyyaml`

Steps 1–10 testable without touching `agent.py`.

---

## Verification Steps

```bash
# 1. Layer 1 unit tests (fixture-backed, no API calls)
python -m pytest tests/test_behavior_profiler.py -v --tb=short

# 2. Layer 2 unit tests (fixture-backed, no API or BQ calls)
python -m pytest tests/test_trade_pattern_analyzer.py -v --tb=short

# 3. Haiku extraction smoke test (requires ANTHROPIC_API_KEY)
python -c "
from agents.memory.behavior_profiler import BehaviorProfiler
import anthropic, os
p = BehaviorProfiler(anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY']))
result = p._call_haiku(p._build_extraction_prompt(
    'How are my dividends performing?',
    'Your bond coupons returned Rp 150k this month.',
    'Trades: 3 bond. Realized: bond +Rp 150k (3W/0L).', ''
))
print(result)
"

# 4. Daily scan smoke test (requires real BQ + yfinance)
python scripts/daily_scan.py
cat memory/user_memory.md   # trade_patterns section should be populated

# 5. End-to-end agent integration
python agent.py
# Ask: "Am I a panic seller?"
# Agent should reference trade_patterns from memory in its answer
# Quit, then verify memory/user_memory.md updated with conversation signals
```
