import json
from datetime import datetime, timedelta
import yfinance as yf


def handle_get_market_news(
    asset_symbol: str = None,
    sector: str = None,
    days_back: int = 3,
) -> str:
    # Map sector names to representative tickers if no symbol given
    sector_tickers = {
        "crypto": "BTC-USD",
        "technology": "QQQ",
        "gold": "GLD",
        "stock_index": "^GSPC",
    }

    ticker_str = asset_symbol
    if not ticker_str and sector:
        ticker_str = sector_tickers.get(sector.lower(), sector)
    if not ticker_str:
        return json.dumps({"status": "error", "message": "Provide asset_symbol or sector."})

    try:
        ticker = yf.Ticker(ticker_str)
        news = ticker.news or []
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

    cutoff = datetime.utcnow() - timedelta(days=days_back)
    filtered = []
    for item in news:
        pub_time = item.get("content", {}).get("pubDate") or item.get("providerPublishTime")
        if isinstance(pub_time, int):
            pub_dt = datetime.utcfromtimestamp(pub_time)
            if pub_dt < cutoff:
                continue
        content = item.get("content", {})
        filtered.append({
            "title": content.get("title") or item.get("title", ""),
            "summary": content.get("summary") or item.get("summary", ""),
            "published": str(pub_time),
            "url": (content.get("canonicalUrl", {}) or {}).get("url") or item.get("link", ""),
        })

    return json.dumps({"status": "success", "symbol": ticker_str, "count": len(filtered), "news": filtered})


def handle_get_asset_price_metrics(asset_symbol: str, timeframe: str) -> str:
    period_map = {
        "1D": ("1d", "5m"),
        "1W": ("5d", "1h"),
        "1M": ("1mo", "1d"),
        "YTD": ("ytd", "1d"),
        "1Y": ("1y", "1wk"),
    }
    period, interval = period_map.get(timeframe.upper(), ("1mo", "1d"))

    try:
        ticker = yf.Ticker(asset_symbol)
        hist = ticker.history(period=period, interval=interval)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

    if hist.empty:
        return json.dumps({"status": "error", "message": f"No data for {asset_symbol}."})

    first_close = float(hist["Close"].iloc[0])
    last_close = float(hist["Close"].iloc[-1])
    pct_change = ((last_close - first_close) / first_close) * 100

    return json.dumps({
        "status": "success",
        "symbol": asset_symbol,
        "timeframe": timeframe,
        "current_price": round(last_close, 4),
        "start_price": round(first_close, 4),
        "pct_change": round(pct_change, 2),
        "high": round(float(hist["High"].max()), 4),
        "low": round(float(hist["Low"].min()), 4),
        "data_points": len(hist),
    })
