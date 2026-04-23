"""
Daily trade behavioral scan — infers trading thesis, behaviors, and risk profile from actual trades.
Writes to Trading Thesis, Behavioral Patterns, and Risk Profile in user_memory.md.

Usage:
    # Daily job (last 30 days) — run via cron:
    0 8 * * * cd /path/to/trading_agent && python memory/daily_trade_scan.py

    # One-time full history scan:
    python memory/daily_trade_scan.py --full

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
BEM_PROJECT = "bem---beli-emas-murni"
LOOKBACK_DAYS = 30

TRADE_ACTIVITIES = (
    "transaction",
    "limit_transaction_filled",
    "market_transaction_filled",
    "stop_limit_transaction_filled",
)
# USD flows — tracked in detail_all_transactions_daily
USD_CASHOUT_ACTIVITIES = ("fx_withdrawal",)
# Crypto wallet flows — tracked in detail_all_transactions_daily
CRYPTO_DEPOSIT_ACTIVITIES = ("crypto_deposit",)
CRYPTO_WITHDRAWAL_ACTIVITIES = ("crypto_withdrawal_request",)

_ALL_ACTIVITIES = (
    TRADE_ACTIVITIES
    + USD_CASHOUT_ACTIVITIES
    + CRYPTO_DEPOSIT_ACTIVITIES
    + CRYPTO_WITHDRAWAL_ACTIVITIES
)


def _bq(project: str) -> bigquery.Client:
    return bigquery.Client(project=project)


def _run(client: bigquery.Client, sql: str, params: list) -> list[dict]:
    cfg = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in client.query(sql, job_config=cfg).result()]


def _uid(user_id: str) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter("user_id", "INT64", int(user_id))


def _dp(name: str, val: date) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter(name, "DATE", val.isoformat())


def _fetch_activity(client, user_id, start: date | None) -> dict:
    activity_list = ", ".join(f"'{a}'" for a in _ALL_ACTIVITIES)
    trade_list = ", ".join(f"'{a}'" for a in TRADE_ACTIVITIES)
    usd_cashout_list = ", ".join(f"'{a}'" for a in USD_CASHOUT_ACTIVITIES)
    crypto_deposit_list = ", ".join(f"'{a}'" for a in CRYPTO_DEPOSIT_ACTIVITIES)
    crypto_withdrawal_list = ", ".join(f"'{a}'" for a in CRYPTO_WITHDRAWAL_ACTIVITIES)

    date_filter = "AND DATE(created) >= @start_date" if start else ""
    params = [_uid(user_id)]
    if start:
        params.append(_dp("start_date", start))

    week_expr = (
        "GREATEST(DATE_DIFF(CURRENT_DATE(), @start_date, WEEK), 1)"
        if start
        else "GREATEST(DATE_DIFF(CURRENT_DATE(), MIN(DATE(created)), WEEK), 1)"
    )

    sql = f"""
        SELECT
            COUNTIF(activity IN ({trade_list})) AS buy_sell_count,
            COUNTIF(activity IN ({usd_cashout_list})) AS usd_cashout_count,
            COUNTIF(activity IN ({crypto_deposit_list})) AS crypto_deposit_count,
            COUNTIF(activity IN ({crypto_withdrawal_list})) AS crypto_withdrawal_count,
            COUNTIF(asset_type IN ('options', 'leverage')) AS high_risk_count,
            COUNT(DISTINCT product) AS distinct_products,
            COUNT(DISTINCT asset_type) AS distinct_asset_types,
            ROUND(COUNTIF(activity IN ({trade_list})) / {week_expr}, 1) AS trades_per_week,
            APPROX_TOP_COUNT(asset_type, 1)[OFFSET(0)].value AS top_asset_type
        FROM `{BQ_PROJECT}.{DATASET}.detail_all_transactions_daily`
        WHERE user_id = @user_id
          {date_filter}
          AND activity IN ({activity_list})
    """
    rows = _run(client, sql, params)
    return rows[0] if rows else {}


def _fetch_idr_flows(client, user_id: str, start: date | None) -> dict:
    topup_table = f"`{BEM_PROJECT}.pluang_cash_transactions.topups`"
    cashout_table = f"`{BEM_PROJECT}.pluang_cash_transactions.cashouts`"

    topup_date = (
        "AND DATE(DATETIME(transaction_time, 'Asia/Jakarta')) >= @start_date" if start else ""
    )
    cashout_date = (
        "AND DATE(DATETIME(COALESCE(transaction_time, updated), 'Asia/Jakarta')) >= @start_date"
        if start else ""
    )

    params = [_uid(user_id)]
    if start:
        params.append(_dp("start_date", start))

    sql = f"""
        SELECT
            (SELECT COUNT(*) FROM {topup_table}
             WHERE user_id = @user_id AND status = 'SUCCESS' {topup_date}) AS idr_topup_count,
            (SELECT COALESCE(SUM(amount), 0) FROM {topup_table}
             WHERE user_id = @user_id AND status = 'SUCCESS' {topup_date}) AS idr_topup_idr,
            (SELECT COUNT(*) FROM {cashout_table}
             WHERE user_id = @user_id AND status IN ('COMPLETED', 'APPROVED') {cashout_date}) AS idr_cashout_count,
            (SELECT COALESCE(SUM(nominal), 0) FROM {cashout_table}
             WHERE user_id = @user_id AND status IN ('COMPLETED', 'APPROVED') {cashout_date}) AS idr_cashout_idr
    """
    rows = _run(client, sql, params)
    return rows[0] if rows else {}


def _fetch_pnl(client, user_id, start: date | None) -> list[dict]:
    date_filter = "AND DATE(created) >= @start_date" if start else ""
    params = [_uid(user_id)]
    if start:
        params.append(_dp("start_date", start))

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
          {date_filter}
          AND transaction_type = 'SELL'
        GROUP BY asset_type
    """
    return _run(client, sql, params)


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


def _build_metrics(
    activity: dict,
    idr_flows: dict,
    pnl_rows: list,
    positions: list,
    period_days: int | None,
) -> dict:
    winners = [float(r["avg_winner"]) for r in pnl_rows if r.get("avg_winner")]
    losers = [float(r["avg_loser"]) for r in pnl_rows if r.get("avg_loser")]
    avg_winner = sum(winners) / len(winners) if winners else None
    avg_loser = sum(losers) / len(losers) if losers else None

    top_pos = max(positions, key=lambda r: r["total_weight"], default={}) if positions else {}

    idr_in = idr_flows.get("idr_topup_count") or 0
    idr_out = idr_flows.get("idr_cashout_count") or 0
    net_flow = "accumulating" if idr_in >= idr_out else "distributing"

    return {
        "period_days": period_days or "all-time",
        "activity": {
            "buy_sell_trades": activity.get("buy_sell_count"),
            "trades_per_week": float(activity.get("trades_per_week") or 0),
            "net_flow": net_flow,
            "distinct_products_traded": activity.get("distinct_products"),
            "distinct_asset_types_traded": activity.get("distinct_asset_types"),
            "high_risk_instrument_trades": activity.get("high_risk_count"),
            "most_traded_asset_class": activity.get("top_asset_type"),
        },
        "flows": {
            "idr": {
                "topup_count": idr_in,
                "topup_idr": idr_flows.get("idr_topup_idr") or 0,
                "cashout_count": idr_out,
                "cashout_idr": idr_flows.get("idr_cashout_idr") or 0,
            },
            "usd": {
                "cashout_count": activity.get("usd_cashout_count") or 0,
            },
            "crypto": {
                "deposit_count": activity.get("crypto_deposit_count") or 0,
                "withdrawal_count": activity.get("crypto_withdrawal_count") or 0,
            },
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
    """Full synthesis — returns thesis, behaviors, risk_profile. Used by full scan."""
    period = metrics.get("period_days")
    period_label = f"last {period} days" if isinstance(period, int) else "all-time"
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
            "content": f"Trade metrics ({period_label}):\n{json.dumps(metrics, indent=2, default=str)}"
        }],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _synthesize_behaviors(metrics: dict) -> list[str]:
    """Behaviors only — cheaper call used by daily scan."""
    period = metrics.get("period_days")
    period_label = f"last {period} days" if isinstance(period, int) else "all-time"
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=(
            "You are a behavioral finance analyst. Given quantitative trade metrics, identify observed trading behaviors. "
            "Output ONLY a valid JSON array of 4-6 specific behavior strings "
            '(e.g. "holds losers too long", "concentrates in crypto"). '
            "Ground every item in the numbers. No hedging. No text outside the JSON array."
        ),
        messages=[{
            "role": "user",
            "content": f"Trade metrics ({period_label}):\n{json.dumps(metrics, indent=2, default=str)}"
        }],
    )
    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _execute(start: date | None, period_days: int | None, scan_label: str) -> None:
    user_id = get_secure_user_id()
    client = _bq(BQ_PROJECT)

    period_str = f"{period_days} days (from {start})" if start else "all-time"
    print(f"Scanning {period_str}...")

    activity = _fetch_activity(client, user_id, start)
    idr_flows = _fetch_idr_flows(client, user_id, start)
    pnl_rows = _fetch_pnl(client, user_id, start)
    positions = _fetch_positions(client, user_id)

    if not activity.get("buy_sell_count") and not pnl_rows and not positions:
        print("No trade data found. Memory not updated.")
        return

    metrics = _build_metrics(activity, idr_flows, pnl_rows, positions, period_days)
    f = metrics["flows"]
    print(f"  trades: {activity.get('buy_sell_count')} ({activity.get('trades_per_week')}/week) | "
          f"IDR: +{f['idr']['topup_count']} / -{f['idr']['cashout_count']} | "
          f"USD cashout: {f['usd']['cashout_count']} | "
          f"crypto: +{f['crypto']['deposit_count']} / -{f['crypto']['withdrawal_count']} | "
          f"flow: {metrics['activity']['net_flow']}")

    print("Synthesizing behavioral profile via LLM...")
    try:
        profile = _synthesize(metrics)
        thesis = (profile.get("thesis") or "").strip()
        behaviors = [b.strip() for b in (profile.get("behaviors") or []) if b.strip()]
        risk_profile = (profile.get("risk_profile") or "").strip()
        if thesis:
            update_section("Trading Thesis (Long-Term)", thesis)
        if behaviors:
            update_section("Behavioral Patterns (Long-Term)", "\n".join(f"- {b}" for b in behaviors))
        if risk_profile:
            update_section("Risk Profile (Long-Term)", risk_profile)
        print(f"  Behaviors: {behaviors}")
    except Exception as e:
        print(f"  Synthesis failed: {e}")
        return

    append_observation(
        f"{scan_label}: {activity.get('buy_sell_count')} trades | "
        f"IDR +{f['idr']['topup_count']}/-{f['idr']['cashout_count']} | "
        f"crypto +{f['crypto']['deposit_count']}/-{f['crypto']['withdrawal_count']} | "
        f"flow {metrics['activity']['net_flow']}"
    )
    set_last_updated(scan_label)
    print("\nDone.")


def run():
    """Daily job: scan the last 30 days and write a metrics summary to Recent Activity (30d)."""
    user_id = get_secure_user_id()
    client = _bq(BQ_PROJECT)
    start = date.today() - timedelta(days=LOOKBACK_DAYS)

    print(f"Scanning last {LOOKBACK_DAYS} days (from {start})...")

    activity = _fetch_activity(client, user_id, start)
    idr_flows = _fetch_idr_flows(client, user_id, start)
    pnl_rows = _fetch_pnl(client, user_id, start)
    positions = _fetch_positions(client, user_id)

    if not activity.get("buy_sell_count") and not pnl_rows and not positions:
        print("No trade data found. Memory not updated.")
        return

    buy_sell = activity.get("buy_sell_count") or 0
    tpw = float(activity.get("trades_per_week") or 0)
    top_asset = activity.get("top_asset_type") or "—"

    idr_in = idr_flows.get("idr_topup_count") or 0
    idr_in_idr = idr_flows.get("idr_topup_idr") or 0
    idr_out = idr_flows.get("idr_cashout_count") or 0
    idr_out_idr = idr_flows.get("idr_cashout_idr") or 0
    usd_cashout = activity.get("usd_cashout_count") or 0
    crypto_dep = activity.get("crypto_deposit_count") or 0
    crypto_wd = activity.get("crypto_withdrawal_count") or 0
    flow = "accumulating" if idr_in >= idr_out else "distributing"

    total_unrealized = round(sum(float(r.get("total_unrealized") or 0) for r in positions))
    losing = sum(r.get("losing_positions", 0) for r in positions)
    total_pos = sum(r.get("total_positions", 0) for r in positions)

    pnl_lines = []
    for r in pnl_rows:
        win_rate = round(r["wins"] / r["sell_count"] * 100) if r["sell_count"] else 0
        pnl_lines.append(
            f"  - {r['asset_type']}: {r['sell_count']} sells, "
            f"{win_rate}% win rate, "
            f"total PnL Rp {round(float(r['total_pnl'] or 0)):,}"
        )
    pnl_block = "\n".join(pnl_lines) if pnl_lines else "  - no realized trades"

    summary = (
        f"**Period:** {start} → {date.today()}\n\n"
        f"**Trades:** {buy_sell} buy/sell ({tpw}/week) | **Top asset:** {top_asset}\n\n"
        f"**IDR flows:** {idr_in} topups (Rp {idr_in_idr:,}) / {idr_out} cashouts (Rp {idr_out_idr:,}) → {flow}\n\n"
        f"**USD flows:** {usd_cashout} cashouts\n\n"
        f"**Crypto flows:** {crypto_dep} deposits / {crypto_wd} withdrawals\n\n"
        f"**Realized P&L by asset:**\n{pnl_block}\n\n"
        f"**Unrealized:** Rp {total_unrealized:,} across {total_pos} positions ({losing} losing)"
    )

    update_section("Recent Activity (30d)", summary)

    print("Synthesizing behavioral patterns via LLM...")
    try:
        metrics = _build_metrics(activity, idr_flows, pnl_rows, positions, LOOKBACK_DAYS)
        behaviors = [b.strip() for b in _synthesize_behaviors(metrics) if b.strip()]
        if behaviors:
            update_section("Behavioral Patterns (30d)", "\n".join(f"- {b}" for b in behaviors))
        print(f"  Behaviors: {behaviors}")
    except Exception as e:
        print(f"  Synthesis failed: {e} — activity summary still saved.")

    append_observation(
        f"daily_scan: {buy_sell} trades | "
        f"IDR +{idr_in}/-{idr_out} | "
        f"crypto +{crypto_dep}/-{crypto_wd} | "
        f"flow {flow}"
    )
    set_last_updated("daily_scan")

    print(f"  trades: {buy_sell} ({tpw}/week) | IDR +{idr_in}/-{idr_out} | "
          f"crypto +{crypto_dep}/-{crypto_wd} | flow: {flow}")
    print("Done.")


def run_full_scan():
    """One-time scan: all available trade history."""
    _execute(start=None, period_days=None, scan_label="full_scan")


if __name__ == "__main__":
    if "--full" in sys.argv:
        run_full_scan()
    else:
        run()
