# JSON schemas passed to the Claude API as the `tools` parameter.
# user_id is intentionally absent from ALL schemas — it is injected
# server-side via get_secure_user_id() inside each handler.

TOOL_SCHEMAS = [
    {
        "name": "get_trade_history",
        "description": (
            "Retrieves a log of the user's raw transactions (buys, sells, top-ups, cashouts). "
            "Use this when the user asks 'what did I buy last week?' or 'show me my recent deposits.' "
            "Defaults to the last 30 days if no date is provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date filter. Format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter. Format YYYY-MM-DD.",
                },
                "asset_type": {
                    "type": "string",
                    "description": (
                        "Filter by asset class. Valid values: 'crypto', 'crypto_futures', "
                        "'crypto_wallet', 'fx', 'gold', 'gss' (US/global stocks), "
                        "'idss' (Indonesian stocks), 'mfund' (mutual funds), "
                        "'options', 'stock_index'."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum rows to return. Default 50, max 100.",
                },
            },
        },
    },
    {
        "name": "get_realised_pnl_transactions",
        "description": (
            "Retrieves the realized profit or loss for individual trades. "
            "Use this when the user asks 'how much did I make when I sold my BTC?' or "
            "'show my dividend payouts.' Defaults to the last 30 days. "
            "All gain values are in IDR (Indonesian Rupiah). Always display as 'Rp X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date filter. Format YYYY-MM-DD.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date filter. Format YYYY-MM-DD.",
                },
                "asset_type": {
                    "type": "string",
                    "description": (
                        "Filter by asset class. Valid values: 'crypto', 'fx', 'gold', "
                        "'gss' (US/global stocks), 'idss' (Indonesian stocks), "
                        "'mfund' (mutual funds), 'options', 'stock_index'."
                    ),
                },
            },
        },
    },
    {
        "name": "get_aggregate_pnl_summary",
        "description": (
            "Retrieves a daily time-series summary of the user's overall portfolio performance, "
            "showing total realized and unrealized gains. "
            "Use this to answer 'how did my portfolio perform over the last month?' "
            "All gain values are in IDR (Indonesian Rupiah). Always display as 'Rp X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days_back": {
                    "type": "integer",
                    "description": "How many days of history to retrieve. Default 7.",
                },
            },
        },
    },
    {
        "name": "get_current_positions",
        "description": (
            "Retrieves the user's current holdings, total value (AUM), and latest unrealized returns. "
            "Use this for 'what is in my portfolio right now?' or 'what are my open positions?' "
            "product_aum and total_aum are in IDR (Indonesian Rupiah). Display as 'Rp X'. "
            "percent is a portfolio weight (0-100), not a currency. "
            "unrealized_return is in IDR."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_type": {
                    "type": "string",
                    "description": (
                        "Filter to only show positions in a specific asset class. "
                        "Valid values: 'crypto', 'crypto_futures', 'fx', 'gold', "
                        "'gss' (US/global stocks), 'gss_leverage', 'idss' (Indonesian stocks), "
                        "'mfund' (mutual funds), 'options', 'cash'."
                    ),
                },
            },
        },
    },
    {
        "name": "get_market_news",
        "description": (
            "Retrieves recent news headlines and market sentiment for a specific asset or sector. "
            "Use this to explain WHY an asset's price might have changed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_symbol": {
                    "type": "string",
                    "description": "Ticker symbol, e.g. 'BTC-USD', 'AAPL'.",
                },
                "sector": {
                    "type": "string",
                    "description": "Broader market sector, e.g. 'crypto', 'technology'.",
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days of news to retrieve. Default 3.",
                },
            },
        },
    },
    {
        "name": "get_asset_price_metrics",
        "description": (
            "Fetches historical price trends, percentage changes, and current market price "
            "for a specific asset."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asset_symbol": {
                    "type": "string",
                    "description": "Ticker symbol, e.g. 'BTC-USD', 'AAPL', 'GLD'.",
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["1D", "1W", "1M", "YTD", "1Y"],
                    "description": "Time window for price data.",
                },
            },
            "required": ["asset_symbol", "timeframe"],
        },
    },
    {
        "name": "load_skill",
        "description": (
            "Loads the full methodology of a named expert investment framework. "
            "Use this before applying an expert's lens to the user's portfolio. "
            "Available skills are listed in your system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill name, e.g. 'ray_dalio' or 'warren_buffett'.",
                },
            },
            "required": ["name"],
        },
    },
]
