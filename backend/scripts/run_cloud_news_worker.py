import os
import sys
from pathlib import Path
from datetime import datetime

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.data_sources.companies import list_companies, company_info
from app.data_sources.news import refresh_news_for_company, load_news_clusters
from app.data_sources.prices import refresh_prices

def main():
    print(f"[{datetime.now().isoformat()}] STARTING CLOUD NEWS & MARKET SYNC WORKER")
    tracked_env = os.environ.get("TRACKED_SYMBOLS", "")
    if tracked_env:
        tracked_symbols = [s.strip().upper() for s in tracked_env.split(",") if s.strip()]
        companies = [company_info(s) for s in tracked_symbols if company_info(s)]
    else:
        companies = list_companies()[:15]
    print(f"Target Companies ({len(companies)}): {[c['nse_symbol'] for c in companies]}")

    for c in companies:
        sym = c["nse_symbol"]
        print(f"\n--- Processing {sym} ({c['name']}) ---")
        
        # 1. Refresh & cluster live news
        try:
            print(f"  [News] Fetching live RSS & running mathematical clustering...")
            clusters = refresh_news_for_company(sym)
            print(f"  [News] ✅ Successfully generated {len(clusters)} event cluster(s) for {sym}")
        except Exception as e:
            print(f"  [News] ⚠️ News sync error for {sym}: {e}")

        # 2. Refresh prices & cache parquet
        try:
            print(f"  [Prices] Fetching market candles from NSE...")
            df = refresh_prices(sym, period="1y")
            last_date = df['date'].iloc[-1]
            last_close = df['close'].iloc[-1]
            print(f"  [Prices] ✅ Updated prices for {sym}. Last close: ₹{last_close:,.2f} ({last_date})")
        except Exception as e:
            print(f"  [Prices] ⚠️ Price sync error for {sym}: {e}")

    print(f"\n[{datetime.now().isoformat()}] WORKER SYNC COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
