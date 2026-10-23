import csv
import urllib.request
import re
from pathlib import Path

csv_path = Path(__file__).resolve().parent.parent / "data" / "companies.csv"

# Pre-seed top companies with known sectors & BSE codes
seed_enrichments = {
    "RELIANCE": {"bse_code": "500325", "sector": "Energy / Conglomerate", "aliases": "RIL;Reliance;Reliance Ind;Jio;Reliance Retail"},
    "TCS": {"bse_code": "532540", "sector": "IT Services", "aliases": "TCS;Tata Consultancy;Tata Consultancy Services Ltd"},
    "INFY": {"bse_code": "500209", "sector": "IT Services", "aliases": "Infosys;Infy;Infosys Ltd"},
    "HDFCBANK": {"bse_code": "500180", "sector": "Banking", "aliases": "HDFC;HDFC Bank;HDFCBANK"},
    "ICICIBANK": {"bse_code": "532174", "sector": "Banking", "aliases": "ICICI;ICICI Bank"},
    "SBIN": {"bse_code": "500112", "sector": "Banking", "aliases": "SBI;State Bank of India"},
    "BHARTIARTL": {"bse_code": "532454", "sector": "Telecom", "aliases": "Airtel;Bharti Airtel"},
    "ITC": {"bse_code": "500875", "sector": "FMCG", "aliases": "ITC;ITC Limited;ITC Ltd"},
    "HINDUNILVR": {"bse_code": "500696", "sector": "FMCG", "aliases": "HUL;Hindustan Unilever"},
    "LT": {"bse_code": "500510", "sector": "Infrastructure", "aliases": "L&T;Larsen & Toubro"},
    "TATAMOTORS": {"bse_code": "500570", "sector": "Automobile", "aliases": "Tata Motors"},
    "TATASTEEL": {"bse_code": "500470", "sector": "Metals & Mining", "aliases": "Tata Steel"},
    "MARUTI": {"bse_code": "532500", "sector": "Automobile", "aliases": "Maruti;Maruti Suzuki"},
    "BAJFINANCE": {"bse_code": "500034", "sector": "Financial Services", "aliases": "Bajaj Finance"},
    "KOTAKBANK": {"bse_code": "500247", "sector": "Banking", "aliases": "Kotak;Kotak Mahindra Bank"},
    "AXISBANK": {"bse_code": "532215", "sector": "Banking", "aliases": "Axis Bank"},
    "TITAN": {"bse_code": "500114", "sector": "Consumer Durables", "aliases": "Titan;Titan Company"},
    "SUNPHARMA": {"bse_code": "524715", "sector": "Pharmaceuticals", "aliases": "Sun Pharma;Sun Pharmaceuticals"},
    "ASIANPAINT": {"bse_code": "500820", "sector": "Consumer Goods", "aliases": "Asian Paints"},
    "WIPRO": {"bse_code": "507685", "sector": "IT Services", "aliases": "Wipro"},
    "HCLTECH": {"bse_code": "532281", "sector": "IT Services", "aliases": "HCL;HCL Tech;HCL Technologies"},
    "NTPC": {"bse_code": "532555", "sector": "Power / Energy", "aliases": "NTPC"},
    "POWERGRID": {"bse_code": "532898", "sector": "Power / Energy", "aliases": "Power Grid;PowerGrid"},
    "ONGC": {"bse_code": "500312", "sector": "Oil & Gas", "aliases": "ONGC"},
    "M&M": {"bse_code": "500520", "sector": "Automobile", "aliases": "Mahindra;Mahindra & Mahindra"},
}

url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

with urllib.request.urlopen(req) as resp:
    lines = [line.decode("utf-8", errors="ignore") for line in resp.readlines()]

reader = csv.DictReader(lines)
companies = {}

for r in reader:
    clean_r = {k.strip(): v.strip() for k, v in r.items() if k}
    sym = clean_r.get("SYMBOL", "").strip().upper()
    name = clean_r.get("NAME OF COMPANY", "").strip()
    series = clean_r.get("SERIES", "").strip()
    
    if not sym or not name or series not in ["EQ", "BE", "SM", "BZ"]:
        continue
        
    short_name = re.sub(r"\b(Limited|Ltd|India|Corp|Corporation)\b", "", name, flags=re.IGNORECASE).strip()
    alias_list = []
    if short_name and short_name.lower() != name.lower():
        alias_list.append(short_name)

    bse_code = ""
    sector = "Equity"

    if sym in seed_enrichments:
        enrich = seed_enrichments[sym]
        bse_code = enrich["bse_code"]
        sector = enrich["sector"]
        alias_list.extend(enrich["aliases"].split(";"))

    companies[sym] = {
        "name": name,
        "nse_symbol": sym,
        "bse_code": bse_code,
        "sector": sector,
        "aliases": ";".join(list(dict.fromkeys(alias_list)))
    }

# Write out to companies.csv
with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["name", "nse_symbol", "bse_code", "sector", "aliases"])
    writer.writeheader()
    # Write top seed companies first for easy discovery, then alphabetical
    for sym in seed_enrichments:
        if sym in companies:
            writer.writerow(companies.pop(sym))
    for sym in sorted(companies.keys()):
        writer.writerow(companies[sym])

print(f"Successfully wrote companies to {csv_path}")
