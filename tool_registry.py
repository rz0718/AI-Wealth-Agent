from agents.tools.finance_tools import (
    handle_get_aggregate_pnl_summary,
    handle_get_current_positions,
    handle_get_realised_pnl_transactions,
    handle_get_trade_history,
)
from agents.tools.market_tools import (
    handle_get_asset_price_metrics,
    handle_get_market_news,
)
from agents.tools.skill_tools import handle_load_skill

TOOL_HANDLERS = {
    "get_trade_history": handle_get_trade_history,
    "get_realised_pnl_transactions": handle_get_realised_pnl_transactions,
    "get_aggregate_pnl_summary": handle_get_aggregate_pnl_summary,
    "get_current_positions": handle_get_current_positions,
    "get_market_news": handle_get_market_news,
    "get_asset_price_metrics": handle_get_asset_price_metrics,
    "load_skill": handle_load_skill,
}
