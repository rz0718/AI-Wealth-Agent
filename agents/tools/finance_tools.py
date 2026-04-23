import json
from datetime import datetime, timedelta

from google.cloud import bigquery

from auth import get_secure_user_id
from config import BQ_PROJECT, BQ_DATASET


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=BQ_PROJECT)


def _table(name: str) -> str:
    return f"`{BQ_PROJECT}.{BQ_DATASET}.{name}`"


def _user_id_param(user_id: str) -> bigquery.ScalarQueryParameter:
    return bigquery.ScalarQueryParameter("user_id", "INT64", int(user_id))


def _thirty_days_ago() -> str:
    return (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")


ASSET_TYPE_ALIASES = {
    # US/global stocks — explicit geographic intent only
    "us_stock": "gss",
    "us_stocks": "gss",
    "global_stock": "gss",
    "global_stocks": "gss",
    # Indonesian stocks — explicit geographic intent only
    "id_stock": "idss",
    "id_stocks": "idss",
    "indonesian_stock": "idss",
    # Unambiguous aliases
    "mutual_fund": "mfund",
    "mutual_funds": "mfund",
    "fund": "mfund",
    "futures": "crypto_futures",
    "crypto_future": "crypto_futures",
}


def _normalize_asset_type(asset_type: str | None) -> str | None:
    if not asset_type:
        return None
    key = asset_type.lower().replace(" ", "_").replace("-", "_")
    return ASSET_TYPE_ALIASES.get(key, asset_type)


def handle_get_trade_history(
    start_date: str = None,
    end_date: str = None,
    asset_type: str = None,
    limit: int = 50,
) -> str:
    asset_type = _normalize_asset_type(asset_type)
    user_id = get_secure_user_id()
    client = _bq_client()

    if not start_date:
        start_date = _thirty_days_ago()

    query = f"""
        SELECT created, asset_type, asset_subtype, product, activity, ref_id, is_aum
        FROM {_table("detail_all_transactions_daily")}
        WHERE user_id = @user_id
          AND DATE(created) >= @start_date
    """
    params = [
        _user_id_param(user_id),
        bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
    ]

    if end_date:
        query += " AND DATE(created) <= @end_date"
        params.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))

    if asset_type:
        query += " AND asset_type = @asset_type"
        params.append(bigquery.ScalarQueryParameter("asset_type", "STRING", asset_type))

    query += f" ORDER BY created DESC LIMIT {min(limit, 100)}"

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(row) for row in client.query(query, job_config=job_config).result()]
    return json.dumps({"status": "success", "count": len(rows), "data": rows}, default=str)


def handle_get_realised_pnl_transactions(
    start_date: str = None,
    end_date: str = None,
    asset_type: str = None,
) -> str:
    asset_type = _normalize_asset_type(asset_type)
    user_id = get_secure_user_id()
    client = _bq_client()

    if not start_date:
        start_date = _thirty_days_ago()

    query = f"""
        SELECT day, created, asset_type, asset_subtype, product,
               transaction_type, activity, realised_gain_idr
        FROM {_table("detail_all_user_realised_return_by_trx_daily")}
        WHERE user_id = @user_id
          AND DATE(created) >= @start_date
    """
    params = [
        _user_id_param(user_id),
        bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
    ]

    if end_date:
        query += " AND DATE(created) <= @end_date"
        params.append(bigquery.ScalarQueryParameter("end_date", "DATE", end_date))

    if asset_type:
        query += " AND asset_type = @asset_type"
        params.append(bigquery.ScalarQueryParameter("asset_type", "STRING", asset_type))

    query += " ORDER BY created DESC"

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(row) for row in client.query(query, job_config=job_config).result()]
    return json.dumps({"status": "success", "count": len(rows), "data": rows}, default=str)


def handle_get_aggregate_pnl_summary(days_back: int = 7) -> str:
    user_id = get_secure_user_id()
    client = _bq_client()

    query = f"""
        SELECT day, realisedGainValue, unrealisedGainValue, overallGainValue,
               realised_gain_daily, unrealised_gain_daily, overall_gain_daily
        FROM {_table("agg_user_realised_unrealised_gain_daily")}
        WHERE user_id = @user_id
          AND day >= DATE_SUB(CURRENT_DATE(), INTERVAL @days_back DAY)
        ORDER BY day DESC
    """
    params = [
        _user_id_param(user_id),
        bigquery.ScalarQueryParameter("days_back", "INT64", days_back),
    ]

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(row) for row in client.query(query, job_config=job_config).result()]
    return json.dumps({"status": "success", "count": len(rows), "data": rows}, default=str)


def handle_get_current_positions(asset_type: str = None) -> str:
    asset_type = _normalize_asset_type(asset_type)
    user_id = get_secure_user_id()
    client = _bq_client()

    query = f"""
        SELECT asset_type, product, product_aum, total_aum, percent, unrealized_return
        FROM {_table("detail_user_latest_unrealised_return_daily")}
        WHERE user_id = @user_id
    """
    params = [_user_id_param(user_id)]

    if asset_type:
        query += " AND asset_type = @asset_type"
        params.append(bigquery.ScalarQueryParameter("asset_type", "STRING", asset_type))

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = [dict(row) for row in client.query(query, job_config=job_config).result()]
    return json.dumps({"status": "success", "count": len(rows), "data": rows}, default=str)
