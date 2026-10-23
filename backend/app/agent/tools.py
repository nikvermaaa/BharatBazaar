from typing import Dict, Any, Optional
import math
import numpy as np
import pandas as pd
from app.data_sources.companies import resolve_ticker, company_info
from app.data_sources.prices import load_prices, get_live_quote

def get_price_history(ticker: str, days: int = 30) -> Dict[str, Any]:
    """
    Fetch price history summary and real-time live market metrics aligned with Google Finance.
    """
    sym = resolve_ticker(ticker)
    if not sym:
        return {"error": f"Unknown or unsupported company: '{ticker}'. Please verify the company name or NSE ticker."}

    try:
        df = load_prices(sym)
    except Exception as e:
        return {"error": f"Could not load prices for {sym}: {str(e)}"}

    if df.empty:
        return {"error": f"Price data empty for {sym}"}

    # 1. Identify valid close column and clean/sort data
    close_col = "close" if "close" in df.columns else ("adj close" if "adj close" in df.columns else df.columns[1])
    df_clean = df.dropna(subset=["date", close_col]).copy()
    df_clean["dt"] = pd.to_datetime(df_clean["date"])
    df_clean = df_clean.sort_values("dt").reset_index(drop=True)

    if df_clean.empty:
        return {"error": f"No valid price rows for {sym}"}

    days = max(2, min(days, 365))
    
    # Query live real-time quote (fast_info with in-memory caching)
    live_quote = get_live_quote(sym)
    live_price = live_quote.get("last_price")
    prev_close = live_quote.get("previous_close")

    # Current price: live market quote at the exact moment matching Google Finance
    if live_price is not None:
        last_close = live_price
    else:
        last_close = float(df_clean[close_col].iloc[-1])

    # 1-Day Change % relative to official previous close (e.g. 1184.50 vs 1209.00 -> -2.03%)
    if prev_close is not None and prev_close > 0:
        change_1d_pct = ((last_close - prev_close) / prev_close) * 100.0
    elif len(df_clean) >= 2:
        hist_prev = float(df_clean.iloc[-2][close_col])
        change_1d_pct = ((last_close - hist_prev) / hist_prev) * 100.0
    else:
        change_1d_pct = 0.0

    # Multi-horizon return calculations (Google Finance / Yahoo Finance standard formula)
    # Compares current live price against the closest closing candle at or immediately after the target date
    def _calc_return(target_dt: pd.Timestamp) -> Optional[float]:
        slice_df = df_clean[df_clean["dt"] >= target_dt]
        if not slice_df.empty:
            base_val = float(slice_df.iloc[0][close_col])
            if base_val > 0:
                return round(((last_close - base_val) / base_val) * 100.0, 2)
        elif not df_clean.empty:
            base_val = float(df_clean.iloc[0][close_col])
            if base_val > 0:
                return round(((last_close - base_val) / base_val) * 100.0, 2)
        return None

    max_dt = df_clean["dt"].max()
    ret_1m = _calc_return(max_dt - pd.Timedelta(days=30))
    ret_3m = _calc_return(max_dt - pd.Timedelta(days=90))
    ret_6m = _calc_return(max_dt - pd.Timedelta(days=180))
    ytd_start_dt = pd.Timestamp(year=max_dt.year, month=1, day=1)
    ret_ytd = _calc_return(ytd_start_dt)
    ret_1y = _calc_return(max_dt - pd.Timedelta(days=365))

    # Requested days window (default 30 days)
    anchor_dt = max_dt - pd.Timedelta(days=days)
    window_slice = df_clean[df_clean["dt"] >= anchor_dt]
    if not window_slice.empty:
        base_candle = window_slice.iloc[0]
        subset = window_slice
    else:
        base_candle = df_clean.iloc[0]
        subset = df_clean

    first_close = float(base_candle[close_col])
    period_start_date = str(base_candle["date"])
    change_days_pct = ((last_close - first_close) / first_close) * 100.0

    info = company_info(sym)
    return {
        "symbol": sym,
        "company_name": info["name"] if info else sym,
        "currency": "INR",
        "as_of": str(df["date"].max()),
        "last_close": round(last_close, 2),
        "change_1d_pct": round(change_1d_pct, 2),
        "return_1m_pct": ret_1m,
        "return_3m_pct": ret_3m,
        "return_6m_pct": ret_6m,
        "return_ytd_pct": ret_ytd,
        "return_1y_pct": ret_1y,
        "return_30d_pct": ret_1m if ret_1m is not None else round(change_days_pct, 2),
        "returns_summary": f"1D: {round(change_1d_pct, 2)}% | 1M: {ret_1m}% | 3M: {ret_3m}% | 6M: {ret_6m}% | YTD: {ret_ytd}% | 1Y: {ret_1y}%",
        "period_calendar_days": int((pd.to_datetime(df["date"].max()) - base_candle["dt"]).days),
        "period_trading_days": len(subset),
        "period_days": len(subset),
        "period_start": period_start_date,
        "period_high": round(float(subset["high"].max()), 2) if "high" in subset else round(float(subset[close_col].max()), 2),
        "period_low": round(float(subset["low"].min()), 2) if "low" in subset else round(float(subset[close_col].min()), 2),
        "change_pct": round(change_days_pct, 2),
        "source": "NSE/BSE real-time market quote aligned with Google Finance",
    }

def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    
    # Separate gains and losses
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    # Wilder's smoothing via EMA with alpha = 1 / period
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    # Only overwrite 0/0 (flat price where both avg_gain and avg_loss are 0) with 50.0.
    # Leave the initial warm-up NaNs intact!
    flat_mask = (avg_gain == 0) & (avg_loss == 0)
    rsi = rsi.mask(flat_mask, 50.0)
    
    return rsi

def compute_indicators(ticker: str) -> Dict[str, Any]:
    """
    Deterministic calculation of RSI, MACD, Moving Averages, and Volatility aligned with Google Finance.
    """
    sym = resolve_ticker(ticker)
    if not sym:
        return {"error": f"Unknown or unsupported company: '{ticker}'."}

    try:
        df = load_prices(sym)
    except Exception as e:
        return {"error": f"Could not compute indicators for {sym}: {str(e)}"}

    if len(df) < 30:
        return {"error": f"Insufficient price history ({len(df)} days) to compute indicators for {sym}."}

    close_col = "close" if "close" in df.columns else ("adj close" if "adj close" in df.columns else df.columns[1])
    # Drop rows where date or close is NaN to ensure only verified trading candles are evaluated
    df_clean = df.dropna(subset=["date", close_col]).copy()
    df_clean["dt"] = pd.to_datetime(df_clean["date"])
    df_clean = df_clean.sort_values("dt").reset_index(drop=True)

    if len(df_clean) < 30:
        return {"error": f"Insufficient price history ({len(df_clean)} days) to compute indicators for {sym}."}

    c = df_clean[close_col].copy()

    # Query live market quote
    live_quote = get_live_quote(sym)
    live_price = live_quote.get("last_price")

    # If live price is present, append as the current live session candle for real-time indicator evaluation
    if live_price is not None:
        last_close = live_price
        c_eval = pd.concat([c, pd.Series([live_price])], ignore_index=True)
    else:
        last_close = float(c.iloc[-1])
        c_eval = c

    # RSI (14) - Wilder's smoothed RSI evaluated with the live candle (matches live market at exact moment)
    rsi_live_series = _calc_rsi(c_eval, 14)
    rsi_live = round(float(rsi_live_series.iloc[-1]), 1) if pd.notna(rsi_live_series.iloc[-1]) else 50.0

    # RSI on settled T-1 close for comparison / historical inspection
    rsi_settled_series = _calc_rsi(c, 14)
    rsi_settled = round(float(rsi_settled_series.iloc[-1]), 1) if pd.notna(rsi_settled_series.iloc[-1]) else 50.0

    # MACD (12, 26, 9)
    ema12 = c_eval.ewm(span=12, adjust=False).mean()
    ema26 = c_eval.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line

    # Simple Moving Averages: Prefer fast_info (official 50-SMA / 200-SMA from market data), fallback to rolling mean
    if live_quote.get("sma_50") is not None:
        sma_50_val = round(live_quote["sma_50"], 2)
    elif len(c_eval) >= 50:
        sma_50_val = round(float(c_eval.rolling(50).mean().iloc[-1]), 2)
    else:
        sma_50_val = None

    if live_quote.get("sma_200") is not None:
        sma_200_val = round(live_quote["sma_200"], 2)
    elif len(c_eval) >= 200:
        sma_200_val = round(float(c_eval.rolling(200).mean().iloc[-1]), 2)
    else:
        sma_200_val = None

    sma_50_settled = round(float(c.rolling(50).mean().iloc[-1]), 2) if len(c) >= 50 else None
    sma_200_settled = round(float(c.rolling(200).mean().iloc[-1]), 2) if len(c) >= 200 else None

    # 30-day annualized volatility
    returns_30d = c_eval.pct_change().tail(30)
    vol_30d = float(returns_30d.std() * (252 ** 0.5) * 100.0) if len(returns_30d) > 5 else 0.0

    as_of = str(df["date"].max())

    price_vs_sma50_pct = round(((last_close / sma_50_val) - 1) * 100, 2) if sma_50_val else None
    price_vs_sma200_pct = round(((last_close / sma_200_val) - 1) * 100, 2) if sma_200_val else None

    def _clean_num(val, default=None):
        if val is None:
            return default
        try:
            import math
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return default
            return f
        except Exception:
            return default

    return {
        "symbol": sym,
        "as_of": as_of,
        "last_close": round(last_close, 2),
        "rsi_14": rsi_live,
        "rsi_14_live": rsi_live,
        "rsi_14_prev_close": rsi_settled,
        "macd": round(float(macd_line.iloc[-1]), 3) if pd.notna(macd_line.iloc[-1]) else 0.0,
        "macd_signal": round(float(signal_line.iloc[-1]), 3) if pd.notna(signal_line.iloc[-1]) else 0.0,
        "macd_hist": round(float(histogram.iloc[-1]), 3) if pd.notna(histogram.iloc[-1]) else 0.0,
        "sma_50": sma_50_val if sma_50_val is not None else "N/A (< 50 trading days)",
        "sma_50_live": sma_50_val if sma_50_val is not None else "N/A",
        "sma_50_prev_close": sma_50_settled if sma_50_settled is not None else "N/A",
        "sma_200": sma_200_val if sma_200_val is not None else "N/A (< 200 trading days)",
        "sma_200_live": sma_200_val if sma_200_val is not None else "N/A",
        "sma_200_prev_close": sma_200_settled if sma_200_settled is not None else "N/A",
        "price_vs_sma50_pct": _clean_num(price_vs_sma50_pct, None),
        "price_vs_sma200_pct": _clean_num(price_vs_sma200_pct, None),
        "annualized_volatility_30d_pct": round(vol_30d, 2) if not math.isnan(vol_30d) else 0.0,
        "source": "Real-time market quote aligned with Google Finance and verified candles",
        "settlement_note": f"Live RSI: {rsi_live} (Settled T-1 Close: {rsi_settled}) | 50-SMA: {sma_50_val}.",
        "note": "Descriptive statistical measurements only, not investment advice or trading signals."
    }

def search_filings(ticker: str, query: str, fiscal_year: Optional[str] = None, doc_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Search official company filings via vector RAG. Autonomously ensures latest concall/results are indexed.
    """
    sym = resolve_ticker(ticker)
    if not sym:
        return {"error": f"Unknown company: '{ticker}'."}
        
    try:
        from app.data_sources.filings import ensure_latest_filings
        target_doc = doc_type if doc_type in ["concall", "results", "annual_report"] else "concall"
        ensure_latest_filings(sym, doc_type=target_doc)
    except Exception as e:
        print(f"[Tools] ensure_latest_filings notice for {sym}: {e}")

    from app.rag.retriever import search_filings_rag
    return search_filings_rag(symbol=sym, query=query, fiscal_year=fiscal_year, doc_type=doc_type)

def search_news(ticker: str, query: str) -> Dict[str, Any]:
    """
    Search deduplicated corporate news event clusters.
    """
    sym = resolve_ticker(ticker)
    if not sym:
        return {"error": f"Unknown company: '{ticker}'."}
        
    from app.data_sources.news import search_news_events
    return search_news_events(symbol=sym, query=query)
