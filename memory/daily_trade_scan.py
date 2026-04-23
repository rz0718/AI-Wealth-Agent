"""
Daily trade behavioral scan — infers trading thesis, behaviors, and risk profile from actual trades.
Writes to Trading Thesis, Behavioral Patterns, and Risk Profile in user_memory.md.

Run manually or via cron:
    0 8 * * * cd /path/to/trading_agent && python memory/daily_trade_scan.py

Requires: CURRENT_USER_ID, BQ_PROJECT, ANTHROPIC_API_KEY in .env
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
from google.cloud import bigquery

from auth import get_secure_user_id
from config import ANTHROPIC_API_KEY, BQ_PROJECT
from memory.memory_manager import append_observation, set_last_updated, update_section

DATASET = "DA_aggregate_published"
LOOKBACK_DAYS = 30


def _bq(project: str) -> bigquery.Client:
    return bigquery.Client(project=project)


def _run(client: bigquery.Client, sql: str, params: list) -> list[dict]:
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in client.query(sql, job_config=cfg).result()]


def _uid(user_id: str) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter("user_id", "INT64", int(user_id))


def _dp(name: str, val: date) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, "DATE", val.isoformat())


def _fetch_activity(client, user_id, start) -> dict:
    sql = f"""
        SELECT
            COUNT(*) AS total_trades,
            COUNTIF(activity = 'topup') AS topup_count,
            COUNTIF(activity = 'cashout') AS cashout_count,
            COUNTIF(asset_type IN ('options', 'leverage')) AS high_risk_count,
            COUNT(DISTINCT product) AS distinct_products,
            COUNT(DISTINCT asset_type) AS distinct_asset_types,
            ROUND(COUNT(*) / GREATEST(DATE_DIFF(CURRENT_DATE(), @start_date, WEEK), 1), 1) AS trades_per_week,
            APPROX_TOP_COUNT(asset_type, 1)[OFFSET(0)].value AS top_asset_type
        FROM `{BQ_PROJECT}.{DATASET}.detail_all_transactions_daily`
        WHERE user_id = @user_id AND DATE(created) >= @start_date
    """
    rows = _run(client, sql, [_uid(user_id), _dp("start_date", start)])
    return rows[0] if rows else {}


def _fetch_pnl(client, user_id, start) -> list[dict]:
    sql = f"""
        SELECT
            asset_type,
            COUNT(*) AS sell_count,
            COUNTIF(realised_gain_idr > 0) AS wins,
            AVG(CASE WHEN realised_gain_idr > 0 THEN realised_gain_idr END) AS avg_winner,
            AVG(CASE WHEN realised_gain_idr < 0 THEN realised_gain_idr END) AS avg_loser,
            MIN(realised_gain_idr) AS max_loss,
            SUM(realised_gain_idr) AS total_pnl
        FROM `{BQ_PROJECT}.{DATASET}.detail_all_user_realised_return_by_trx_daily`
        WHERE user_id = @user_id
          AND DATE(created) >= @start_date
          AND transaction_type = 'SELL'
        GROUP BY asset_type
    """
    return _run(client, sql, [_uid(user_id), _dp("start_date", start)])


def _fetch_positions(client, user_id) -> list[dict]:
    sql = f"""
        SELECT
            asset_type,
            SUM(percent) AS total_weight,
            SUM(unrealized_return) AS total_unrealized,
            COUNTIF(unrealized_return < 0) AS losing_positions,
            COUNT(*) AS total_positions
        FROM `{BQ_PROJECT}.{DATASET}.detail_user_latest_unrealised_return_daily`
        WHERE user_id = @user_id
        GROUP BY asset_type
    """
    return _run(client, sql, [_uid(user_id)])


def _build_metrics(activity: dict, pnl_rows: list, positions: list) -> dict:
    winners = [float(r["avg_winner"]) for r in pnl_rows if r.get("avg_winner")]
    losers = [float(r["avg_loser"]) for r in pnl_rows if r.get("avg_loser")]
    avg_winner = sum(winners) / len(winners) if winners else None
    avg_loser = sum(losers) / len(losers) if losers else None

    top_pos = max(positions, key=lambda r: r["total_weight"], default={}) if positions else {}

    return {
        "activity": {
            "total_trades_30d": activity.get("total_trades"),
            "trades_per_week": float(activity.get("trades_per_week") or 0),
            "net_flow": "accumulating" if (activity.get("topup_count") or 0) >= (activity.get("cashout_count") or 0) else "distributing",
            "distinct_products_traded": activity.get("distinct_products"),
            "distinct_asset_types_traded": activity.get("distinct_asset_types"),
            "high_risk_instrument_trades": activity.get("high_risk_count"),
            "most_traded_asset_class": activity.get("top_asset_type"),
        },
        "pnl_by_asset": [
            {
                "asset_type": r["asset_type"],
                "sell_count": r["sell_count"],
                "win_rate": round(r["wins"] / r["sell_count"], 2) if r["sell_count"] else None,
                "avg_winner_idr": round(float(r["avg_winner"] or 0)),
                "avg_loser_idr": round(float(r["avg_loser"] or 0)),
                "max_single_loss_idr": round(float(r["max_loss"] or 0)),
                "total_pnl_idr": round(float(r["total_pnl"] or 0)),
            }
            for r in pnl_rows
        ],
        "disposition_effect": {
            "avg_winner_idr": round(avg_winner) if avg_winner else None,
            "avg_loser_idr": round(avg_loser) if avg_loser else None,
            # True = cuts winners early and holds losers (classic bias)
            "cuts_winners_early": (
                abs(avg_winner) < abs(avg_loser) if avg_winner and avg_loser else None
            ),
        },
        "portfolio": {
            "top_asset_class": top_pos.get("asset_type"),
            "top_asset_weight_pct": round(float(top_pos.get("total_weight") or 0), 1),
            "total_losing_positions": sum(r.get("losing_positions", 0) for r in positions),
            "total_unrealized_idr": round(sum(float(r.get("total_unrealized") or 0) for r in positions)),
            "holds_high_risk_instruments": any(
                r["asset_type"] in ("options", "leverage") for r in positions
            ),
        },
    }


def _synthesize(metrics: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=(
            "You are a behavioral finance analyst. Given quantitative trade metrics, produce a trading profile. "
            "Output ONLY valid JSON with exactly these keys:\n"
            '"thesis": 2-3 sentences on the user\'s inferred market beliefs and approach,\n'
            '"behaviors": list of 4-6 specific observed behavior strings (e.g. "holds losers too long", "concentrates in crypto"),\n'
            '"risk_profile": one sentence starting with conservative/moderate/aggressive and explaining why.\n'
            "Ground every claim in the numbers. No hedging. No text outside the JSON."
        ),
        messages=[{
            "role": "user",
            "content": f"Trade metrics (last 30 days):\n{json.dumps(metrics, indent=2, default=str)}"
        }],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def run():
    user_id = get_secure_user_id()
    client = _bq(BQ_PROJECT)
    start = date.today() - timedelta(days=LOOKBACK_DAYS)

    print(f"Scanning {LOOKBACK_DAYS} days of trades (from {start})...")

    activity = _fetch_activity(client, user_id, start)
    pnl_rows = _fetch_pnl(client, user_id, start)
    positions = _fetch_positions(client, user_id)

    if not activity.get("total_trades") and not pnl_rows and not positions:
        print("No trade data found. Memory not updated.")
        return

    metrics = _build_metrics(activity, pnl_rows, positions)
    print(f"  {metrics['activity']['total_trades_30d']} trades, "
          f"{metrics['activity']['trades_per_week']}/week, "
          f"top asset: {metrics['activity']['most_traded_asset_class']}, "
          f"flow: {metrics['activity']['net_flow']}")

    print("Synthesizing behavioral profile via LLM...")
    try:
        profile = _synthesize(metrics)
    except Exception as e:
        print(f"Synthesis failed: {e}")
        return

    thesis = (profile.get("thesis") or "").strip()
    behaviors = [b.strip() for b in (profile.get("behaviors") or []) if b.strip()]
    risk_profile = (profile.get("risk_profile") or "").strip()

    if thesis:
        update_section("Trading Thesis", thesis)
    if behaviors:
        update_section("Behavioral Patterns", "\n".join(f"- {b}" for b in behaviors))
    if risk_profile:
        update_section("Risk Profile", risk_profile)

    append_observation(
        f"daily scan: {activity.get('total_trades')} trades, "
        f"top asset {activity.get('top_asset_type')}, "
        f"flow {metrics['activity']['net_flow']}"
    )
    set_last_updated("daily_scan")

    print(f"\nThesis:   {thesis[:120]}...")
    print(f"Behaviors: {behaviors}")
    print(f"Risk:      {risk_profile[:100]}")
    print("\nDone.")


if __name__ == "__main__":
    run()
