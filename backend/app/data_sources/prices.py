import os
import time
import math
from pathlib import Path
import pandas as pd
import yfinance as yf
from app.config import PRICES_DIR
from app.data_sources.companies import resolve_ticker, company_info

def _path(symbol: str) -> str:
    return str(Path(PRICES_DIR) / f"{symbol.upper()}.parquet")

def refresh_prices(symbol: str, period: str = "2y") -> pd.DataFrame:
    """
    Download real historical price data from NSE/BSE and cache to parquet.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    info = company_info(sym)
    
    # Try NSE first (SYMBOL.NS)
    ticker_str = f"{sym}.NS"
    df = yf.download(ticker_str, period=period, auto_adjust=False, progress=False)
    
    # Fallback to BSE if NSE fails and BSE scrip code is known
    if df.empty and info and info.get("bse_code"):
        ticker_str = f"{info['bse_code']}.BO"
        df = yf.download(ticker_str, period=period, auto_adjust=False, progress=False)

    if df.empty:
        raise RuntimeError(f"No price data found for {symbol} ({ticker_str})")

    # Reset index first to get Date column
    df = df.reset_index()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0].lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]

    date_cols = [c for c in df.columns if "date" in c]
    if date_cols:
        df.rename(columns={date_cols[0]: "date"}, inplace=True)

    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values("date").reset_index(drop=True)
    
    # Ensure numeric types
    for col in ["open", "high", "low", "close", "adj close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
    df.to_parquet(_path(sym))
    return df

def load_prices(symbol: str, max_age_hours: int = 1) -> pd.DataFrame:
    """
    Load cached prices from Parquet. Automatically refreshes if file is missing or stale.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    file_path = _path(sym)
    
    needs_refresh = False
    if not os.path.exists(file_path):
        needs_refresh = True
    else:
        file_age = time.time() - os.path.getmtime(file_path)
        if file_age > (max_age_hours * 3600):
            needs_refresh = True

    if needs_refresh:
        try:
            return refresh_prices(sym)
        except Exception as e:
            if os.path.exists(file_path):
                # Fallback to existing cache if network fetch fails
                return pd.read_parquet(file_path)
            raise e

    return pd.read_parquet(file_path)

_LIVE_QUOTE_CACHE: dict = {}

def get_live_quote(symbol: str, max_age_seconds: int = 45) -> dict:
    """
    Fetch live real-time price, previous close, and moving averages from NSE/BSE via fast_info with in-memory caching.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    now = time.time()
    if sym in _LIVE_QUOTE_CACHE:
        cached_time, data = _LIVE_QUOTE_CACHE[sym]
        if now - cached_time < max_age_seconds:
            return data

    result = {
        "symbol": sym,
        "last_price": None,
        "previous_close": None,
        "sma_50": None,
        "sma_200": None,
    }

    ticker_candidates = [f"{sym}.NS"]
    info = company_info(sym)
    if info and info.get("bse_code"):
        ticker_candidates.append(f"{info['bse_code']}.BO")

    for ticker_str in ticker_candidates:
        try:
            t = yf.Ticker(ticker_str)
            fi = t.fast_info
            lp = getattr(fi, "last_price", None)
            pc = getattr(fi, "previous_close", None)
            sma50 = getattr(fi, "fifty_day_average", None)
            sma200 = getattr(fi, "two_hundred_day_average", None)

            if lp is not None and not math.isnan(float(lp)):
                result["last_price"] = float(lp)
            if pc is not None and not math.isnan(float(pc)):
                result["previous_close"] = float(pc)
            if sma50 is not None and not math.isnan(float(sma50)):
                result["sma_50"] = float(sma50)
            if sma200 is not None and not math.isnan(float(sma200)):
                result["sma_200"] = float(sma200)

            if result["last_price"] is not None:
                break
        except Exception:
            continue

    _LIVE_QUOTE_CACHE[sym] = (now, result)
    return result

