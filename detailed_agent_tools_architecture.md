# AI Agent Financial Tool Architecture

## 🛠️ Phase 1: Tool Schema Design (The LLM's View)

These are the schemas you will provide to the agent. Notice that `user_id` is intentionally absent from all input schemas. The LLM will only control the filters.

### 1. get_trade_history

- **Description:** Retrieves a log of the user's raw transactions (buys, sells, top-ups, cashouts). Use this when the user asks "what did I buy last week?" or "show me my recent deposits."
- **Parameters:**
  - `start_date` (string, optional): Format YYYY-MM-DD.
  - `end_date` (string, optional): Format YYYY-MM-DD.
  - `asset_type` (string, optional): e.g., 'crypto', 'stock_index', 'gold'.
  - `limit` (integer, optional): Default 50, max 100.

### 2. get_realised_pnl_transactions

- **Description:** Retrieves the realized profit or loss for individual trades (e.g., when a user sells an asset). Use this when the user asks "how much did I make when I sold my AAPL stock?" or "show my dividend payouts."
- **Parameters:**
  - `start_date` (string, optional): Format YYYY-MM-DD.
  - `end_date` (string, optional): Format YYYY-MM-DD.
  - `asset_type` (string, optional): Filter by asset class.

### 3. get_aggregate_pnl_summary

- **Description:** Retrieves a daily time-series summary of the user's overall portfolio performance, showing total realized and unrealized gains for specific days. Use this to answer "how did my portfolio perform over the last month?"
- **Parameters:**
  - `days_back` (integer, optional): How many days of history to retrieve (e.g., 7 for the last week, 30 for the last month). Defaults to 7.

### 4. get_current_positions

- **Description:** Retrieves the user's current holdings, their total value (AUM), and their latest unrealized returns based on yesterday's prices. Use this for "what is in my portfolio right now?" or "what are my open positions?"
- **Parameters:**
  - `asset_type` (string, optional): Filter to only show positions in a specific asset class.

---

## 🌐 Phase 1b: External Market Tools (The LLM's View)

These tools provide external context to explain *why* the user's portfolio changed.

### 5. get_market_news

- **Description:** Retrieves recent news headlines and market sentiment for a specific asset or sector. Use this to explain WHY an asset's price might have changed.
- **Parameters:**
  - `asset_symbol` (string, optional): The ticker symbol (e.g., 'BTC', 'AAPL').
  - `sector` (string, optional): The broader market sector (e.g., 'crypto', 'technology').
  - `days_back` (integer): How many days of news to retrieve. Default is 3.

### 6. get_asset_price_metrics

- **Description:** Fetches historical price trends, percentage changes, and current market prices for a specific asset.
- **Parameters:**
  - `asset_symbol` (string, required): The ticker symbol.
  - `timeframe` (string, required): e.g., '1D', '1W', '1M', 'YTD', '1Y'.

---

## 🗺️ Phase 2: Implementation Plan (The Backend View)

To build these tools into your Python loop safely, follow this step-by-step implementation plan.

### Step 1: Create the Session Context Helper

Before writing any handlers, ensure you have a mechanism to fetch the authenticated user's ID.

```python
def get_secure_user_id() -> str:
    # TODO: Hook this into your app's actual authentication state (e.g., JWT decoding)
    return "CURRENT_LOGGED_IN_USER_ID"
```

### Step 2: Build the BigQuery Handlers (`agents/tools/finance_tools.py`)

Write four separate Python handler functions. Each function must:

1. Call `get_secure_user_id()`.
2. Construct the BigQuery parameterized query based on the LLM's inputs (`start_date`, `asset_type`, etc.).
3. Execute the query.
4. Format the BigQuery `RowIterator` into a clean JSON string or a concise markdown table to return to the LLM.

*Example logic for the Current Positions handler:*

```python
from google.cloud import bigquery
import json

def handle_get_current_positions(asset_type: str = None) -> str:
    user_id = get_secure_user_id()
    client = bigquery.Client()
    
    query = """
        SELECT asset_type, product, total_aum, unrealized_return
        FROM `DA_aggregate_published.detail_user_latest_unrealised_return_daily`
        WHERE user_id = @user_id
    """
    
    query_params = [bigquery.ScalarQueryParameter("user_id", "STRING", user_id)]
    
    # Dynamically append filters if the LLM provided them
    if asset_type:
        query += " AND asset_type = @asset_type"
        query_params.append(bigquery.ScalarQueryParameter("asset_type", "STRING", asset_type))
        
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    results = client.query(query, job_config=job_config).result()
    
    # Format results as a list of dicts, then json.dumps() to return to the agent
    data = [dict(row) for row in results]
    return json.dumps({"status": "success", "data": data})
```

### Step 3: Implement Date/Partition Guardrails

For queries 1, 2, and 3, which are partitioned by `created` or `day`, your handlers must enforce date filters.
If the LLM calls `get_trade_history` but doesn't provide a `start_date`, your Python handler should automatically inject a default (e.g., `WHERE created >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)`) to prevent full table scans and keep your BigQuery costs down.

### Step 4: Register the Handlers

Map your schemas and handler functions into the agent loop:

```python
TOOL_HANDLERS = {
    # Internal User Tools
    "get_trade_history": handle_get_trade_history,
    "get_realised_pnl_transactions": handle_get_realised_pnl_transactions,
    "get_aggregate_pnl_summary": handle_get_aggregate_pnl_summary,
    "get_current_positions": handle_get_current_positions,
    
    # External Market Tools
    "get_market_news": handle_get_market_news,  # Assuming these are defined similarly
    "get_asset_price_metrics": handle_get_asset_price_metrics
}
```



  Sample **Queries for User Trade History, Positions & PNL by user_id**



  ---

  **1. Trade History — every transaction a user made**

  SELECT

    created,

    user_id,

    account_id,

    asset_type,

    asset_subtype,

    product,

    activity,          -- buy / sell / topup / cashout / etc.

    ref_id,

    is_gtv,

    is_aum

  FROM `DA_aggregate_published.detail_all_transactions_daily`

  WHERE user_id = ''

  ORDER BY created DESC

  **Source model:** dbt/models/core/DA_aggregate_published__detail_all_transactions_daily.sql

  Partitioned by created (datetime/day), clustered by asset_type, activity, is_gtv, is_AUM.

  ---

  **2. Realised PNL — per-transaction gain/loss**

  SELECT

    day,

    created,

    user_id,

    account_id,

    asset_type,

    asset_subtype,

    product,

    transaction_type,   -- BUY / SELL / DIVIDEND / etc.

    activity,

    realised_gain_idr,

    realised_gain_usd

  FROM `DA_aggregate_published.detail_all_user_realised_return_by_trx_daily`

  WHERE user_id = ''

  ORDER BY created DESC

  **Source model:** dbt/models/core/DA_aggregate_published__detail_all_user_realised_return_by_trx_daily.sql

  Clustered by asset_type, transaction_type, user_id, account_id — filtering on user_id is fast.

  Covers all asset types: crypto, gold, GSS, FX, stock index, mfund, IDSS, options, leverage.

  ---

  **3. Aggregate PNL summary (realised + unrealised, daily)**

  SELECT

    day,

    user_id,

    account_id,

    realisedGainValue,

    unrealisedGainValue,

    overallGainValue,

    realised_gain_daily,

    unrealised_gain_daily,

    overall_gain_daily

  FROM `DA_aggregate_published.agg_user_realised_unrealised_gain_daily`

  WHERE user_id = ''

  ORDER BY day DESC

  **Source model:** dbt/models/core/DA_aggregate_published__agg_user_realised_unrealised_gain_daily.sql

  Partitioned by day. Good for a portfolio-level PNL time series.

  ---

  **4. Current Positions (unrealised return by asset)**

  SELECT

    user_id,

    asset_type,

    product,

    product_aum,

    total_aum,

    percent,

    unrealized_return

  FROM `DA_aggregate_published.detail_user_latest_unrealised_return_daily`

  WHERE user_id = ''

  **Source model:** dbt/models/core/DA_aggregate_published__detail_user_latest_unrealised_return_daily.sql

  This is a snapshot (no date partition) — reflects the latest unrealised return based on yesterday's prices. Covers gold, crypto, mfund, stock_index, GSS, FX.

  ---

  **Putting it all together (one user, full picture)**

  -- Trade history

  SELECT 'transaction' AS record_type, CAST(created AS DATE) AS day, asset_type, product, activity AS event, realised_gain_idr AS gain_idr

  FROM `DA_aggregate_published.detail_all_user_realised_return_by_trx_daily`

  WHERE user_id = ''

  UNION ALL

  -- Current unrealised positions

  SELECT 'position', CURRENT_DATE(), asset_type, product, 'unrealised', unrealized_return

  FROM `DA_aggregate_published.detail_user_latest_unrealised_return_daily`

  WHERE user_id = ''

  ORDER BY day DESC