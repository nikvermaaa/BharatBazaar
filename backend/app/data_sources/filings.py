import os
import re
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import requests
from bs4 import BeautifulSoup

from app.config import FILINGS_DIR
from app.data_sources.companies import resolve_ticker, company_info
from app.data_sources.fiscal import fiscal_period
from app.rag.ingest import ingest_pdf, ingest_text_document

_DISCLOSURE_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_SYNC_LOCKS: Dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()

def _get_lock(symbol: str) -> threading.Lock:
    with _GLOBAL_LOCK:
        if symbol not in _SYNC_LOCKS:
            _SYNC_LOCKS[symbol] = threading.Lock()
        return _SYNC_LOCKS[symbol]

def _index_path(symbol: str) -> Path:
    target_dir = Path(FILINGS_DIR) / symbol.upper()
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "filings_index.json"

def get_filings_status(symbol: str) -> Dict[str, Any]:
    """
    Get the current indexing status and latest concall/filing info for a company.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    idx_file = _index_path(sym)
    if idx_file.exists():
        try:
            with open(idx_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "symbol": sym,
                    "indexed": True,
                    "latest_doc_type": data.get("latest_doc_type", "concall"),
                    "latest_title": data.get("latest_title", "Latest Disclosures"),
                    "fiscal_year": data.get("fiscal_year", "N/A"),
                    "quarter": data.get("quarter", "N/A"),
                    "chunks_indexed": data.get("chunks_indexed", 0),
                    "last_synced": data.get("last_synced", ""),
                    "filename": data.get("filename", "")
                }
        except Exception:
            pass
    return {
        "symbol": sym,
        "indexed": False,
        "latest_doc_type": None,
        "latest_title": None,
        "fiscal_year": None,
        "quarter": None,
        "chunks_indexed": 0,
        "last_synced": None,
        "filename": None
    }

def parse_period_from_context(context: str) -> Tuple[str, str]:
    """
    Parse (fiscal_year, quarter) from announcement description text.
    Handles Indian corporate reporting conventions and calendar years.
    """
    ctx = context.lower()

    # 1. Explicit Quarter mention (e.g. Q1, Q2, Q3, Q4)
    q_match = re.search(r'\bq([1-4])\b', ctx)
    q = f"Q{q_match.group(1)}" if q_match else None

    # 2. Explicit FY mention (e.g. FY24, FY 2024, FY2023-2024, FY23-24)
    fy_span_match = re.search(r'fy\s*(?:20)?([0-9]{2})\s*[-–/]\s*(?:20)?([0-9]{2})', ctx)
    if fy_span_match:
        fy = f"FY{fy_span_match.group(2)}"
    else:
        fy_match = re.search(r'fy\s*([0-9]{2,4})', ctx)
        fy = f"FY{fy_match.group(1)[-2:]}" if fy_match else None

    # 3. Calendar Year mention (e.g. 2023, 2024, 2025, 2026)
    year_match = re.search(r'\b(20[12][0-9])\b', ctx)
    cal_year = int(year_match.group(1)) if year_match else None

    # Check for multi-year span like 2023-24 or 2023-2024
    if not fy:
        span_match = re.search(r'(?:20)?([0-9]{2})\s*[-–/]\s*(?:20)?([0-9]{2})', ctx)
        if span_match:
            fy = f"FY{span_match.group(2)}"

    # 4. Month Mentions aligned with Indian reporting cycles:
    # April - June: companies report Q4 results of the financial year ending in March of cal_year (e.g. May 2024 -> Q4 FY24)
    if any(m in ctx for m in ["april", "apr", "may", "june", "jun"]):
        if not q: q = "Q4"
        if not fy and cal_year: fy = f"FY{str(cal_year)[-2:]}"
    # July - September: companies report Q1 results of next FY (e.g. August 2024 -> Q1 FY25)
    elif any(m in ctx for m in ["july", "jul", "august", "aug", "september", "sep"]):
        if not q: q = "Q1"
        if not fy and cal_year: fy = f"FY{str(cal_year + 1)[-2:]}"
    # October - December: companies report Q2 results of next FY (e.g. November 2024 -> Q2 FY25)
    elif any(m in ctx for m in ["october", "oct", "november", "nov", "december", "dec"]):
        if not q: q = "Q2"
        if not fy and cal_year: fy = f"FY{str(cal_year + 1)[-2:]}"
    # January - March: companies report Q3 results of current FY (e.g. February 2024 -> Q3 FY24)
    elif any(m in ctx for m in ["january", "jan", "february", "feb", "march", "mar"]):
        if not q: q = "Q3"
        if not fy and cal_year: fy = f"FY{str(cal_year)[-2:]}"

    if not fy and cal_year:
        fy = f"FY{str(cal_year)[-2:]}"

    # Fallback to current fiscal period
    if not q or not fy:
        calc_fy, calc_q = fiscal_period(datetime.now())
        q = q or calc_q
        fy = fy or calc_fy

    return fy, q

def fetch_latest_disclosures(symbol: str) -> Dict[str, Any]:
    """
    Fetch list of latest official company disclosures (concall transcripts, results, annual reports) from exchange feeds.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    now = time.time()
    if sym in _DISCLOSURE_CACHE:
        cached_time, cached_data = _DISCLOSURE_CACHE[sym]
        if now - cached_time < 300: # 5 min cache
            return cached_data

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    results = {
        "symbol": sym,
        "concalls": [],
        "results": [],
        "annual_reports": []
    }

    urls_to_try = [
        f"https://www.screener.in/company/{sym}/consolidated/",
        f"https://www.screener.in/company/{sym}/"
    ]

    resp = None
    for url in urls_to_try:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                resp = r
                break
        except Exception:
            continue

    if not resp:
        return results

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        doc_section = soup.find("section", id="documents")
        if not doc_section:
            return results

        for a in doc_section.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if not href or not href.startswith("http"):
                continue

            parent = a.find_parent("li") or a.find_parent("div")
            context = parent.get_text(" ", strip=True) if parent else text

            # 1. Earnings Concall Transcripts
            if ("transcript" in text.lower() or "concall" in text.lower() or "transcript" in context.lower()) and href.endswith(".pdf"):
                fy, q = parse_period_from_context(context)
                results["concalls"].append({
                    "title": text,
                    "context": context,
                    "url": href,
                    "fiscal_year": fy,
                    "quarter": q,
                    "doc_type": "concall"
                })

            # 2. Quarterly Results
            elif ("results" in text.lower() or "financial results" in context.lower()) and href.endswith(".pdf"):
                fy, q = parse_period_from_context(context)
                results["results"].append({
                    "title": text,
                    "context": context,
                    "url": href,
                    "fiscal_year": fy,
                    "quarter": q,
                    "doc_type": "results"
                })

            # 3. Annual Reports
            elif "annual report" in text.lower() and href.endswith(".pdf"):
                fy, _ = parse_period_from_context(text)
                results["annual_reports"].append({
                    "title": text,
                    "context": context,
                    "url": href,
                    "fiscal_year": fy,
                    "quarter": "Annual",
                    "doc_type": "annual_report"
                })
    except Exception as e:
        print(f"[Filings] Error parsing disclosures for {sym}: {e}")

    _DISCLOSURE_CACHE[sym] = (now, results)
    return results

def download_and_ingest_latest_filing(symbol: str, doc_type: str = "concall") -> Dict[str, Any]:
    """
    Autonomously download, extract text, chunk, embed, and index the latest filing into ChromaDB.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    lock = _get_lock(sym)
    with lock:
        disclosures = fetch_latest_disclosures(sym)
        if doc_type == "annual_report":
            target_list = disclosures.get("annual_reports", []) or disclosures.get("concalls", [])
        elif doc_type == "concall":
            target_list = disclosures.get("concalls", []) or disclosures.get("results", [])
        else:
            target_list = disclosures.get("results", []) or disclosures.get("concalls", [])

        if not target_list:
            return {
                "status": "error",
                "message": f"No online disclosures found for {sym} ({doc_type}).",
                "chunks": 0
            }

        latest_item = target_list[0]
        pdf_url = latest_item["url"]
        context_title = latest_item.get("context") or latest_item.get("title")
        fy = latest_item.get("fiscal_year", "FY27")
        q = latest_item.get("quarter", "Q2")
        actual_doc_type = latest_item.get("doc_type", doc_type)

        # Check existing index
        idx_path = _index_path(sym)
        if idx_path.exists():
            try:
                with open(idx_path, "r", encoding="utf-8") as f:
                    curr_idx = json.load(f)
                    if curr_idx.get("latest_url") == pdf_url and curr_idx.get("chunks_indexed", 0) > 0:
                        return {
                            "status": "cached",
                            "message": f"Latest disclosure already indexed for {sym}.",
                            "chunks": curr_idx.get("chunks_indexed", 0),
                            "fiscal_year": fy,
                            "quarter": q,
                            "title": context_title
                        }
            except Exception:
                pass

        # Download PDF
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bseindia.com/"
        }

        try:
            r = requests.get(pdf_url, headers=headers, timeout=20)
            if r.status_code != 200 or len(r.content) < 1000:
                return {
                    "status": "error",
                    "message": f"Failed downloading PDF from {pdf_url} (HTTP {r.status_code}).",
                    "chunks": 0
                }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Network exception downloading PDF: {str(e)}",
                "chunks": 0
            }

        # Save to disk
        target_dir = Path(FILINGS_DIR) / sym
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{actual_doc_type}_{q}_{fy}.pdf"
        target_path = target_dir / filename
        with open(target_path, "wb") as f:
            f.write(r.content)

        # Ingest into ChromaDB
        chunks_count = ingest_pdf(
            path=str(target_path),
            symbol=sym,
            doc_type=actual_doc_type,
            fiscal_year=fy,
            quarter=q,
            basis="consolidated",
            url=pdf_url
        )

        # Update index
        index_data = {
            "symbol": sym,
            "latest_url": pdf_url,
            "latest_doc_type": actual_doc_type,
            "latest_title": context_title,
            "fiscal_year": fy,
            "quarter": q,
            "filename": filename,
            "chunks_indexed": chunks_count,
            "last_synced": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, indent=2)

        return {
            "status": "success",
            "message": f"Successfully downloaded and embedded latest {actual_doc_type} ({fy} {q}) for {sym}.",
            "chunks": chunks_count,
            "fiscal_year": fy,
            "quarter": q,
            "title": context_title
        }

def parse_screener_quarter(header_str: str) -> Tuple[str, str]:
    """Parse header like 'Jun 2023' or 'Mar 2024' into Indian fiscal (fiscal_year, quarter)."""
    parts = header_str.strip().split()
    if len(parts) != 2:
        return "N/A", "N/A"
    mon = parts[0].lower()
    try:
        yr = int(parts[1])
    except Exception:
        return "N/A", "N/A"
    fy_num = yr % 100
    if "jun" in mon:
        q = "Q1"
        fy = f"FY{fy_num + 1:02d}"
    elif "sep" in mon:
        q = "Q2"
        fy = f"FY{fy_num + 1:02d}"
    elif "dec" in mon:
        q = "Q3"
        fy = f"FY{fy_num + 1:02d}"
    elif "mar" in mon:
        q = "Q4"
        fy = f"FY{fy_num:02d}"
    else:
        q = "N/A"
        fy = f"FY{fy_num:02d}"
    return fy, q

def scrape_and_ingest_quarterly_table(symbol: str, force: bool = False) -> Dict[str, Any]:
    """
    Scrape official multi-quarter financial results (last 10-14 quarters) from Screener
    and ingest structured data into ChromaDB so the RAG agent has multi-quarter profit history.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    lock = _get_lock(f"{sym}_quarters")
    with lock:
        target_dir = Path(FILINGS_DIR) / sym
        target_dir.mkdir(parents=True, exist_ok=True)
        flag_file = target_dir / "quarters_synced.json"

        if not force and flag_file.exists():
            try:
                with open(flag_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if time.time() - data.get("synced_at", 0) < 86400: # 24 hr cache
                        return {
                            "status": "cached",
                            "message": f"Multi-quarter results already indexed for {sym}.",
                            "quarters_count": data.get("quarters_count", 0)
                        }
            except Exception:
                pass

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }

        urls_to_try = [
            f"https://www.screener.in/company/{sym}/consolidated/",
            f"https://www.screener.in/company/{sym}/"
        ]

        resp = None
        for u in urls_to_try:
            try:
                r = requests.get(u, headers=headers, timeout=10)
                if r.status_code == 200 and "quarters" in r.text:
                    resp = r
                    break
            except Exception:
                continue

        if not resp:
            return {"status": "error", "message": f"Could not fetch financial results page for {sym}."}

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
            section = soup.find("section", id="quarters")
            if not section:
                return {"status": "error", "message": f"No quarterly results section found for {sym}."}

            table = section.find("table")
            if not table:
                return {"status": "error", "message": f"No quarterly data table found for {sym}."}

            raw_headers = [th.get_text(strip=True) for th in table.find_all("th")]
            date_cols = [h for h in raw_headers if h and h != "Raw PDF"]

            if not date_cols:
                return {"status": "error", "message": f"No quarter date columns found for {sym}."}

            metric_rows = {}
            for tr in table.find_all("tr")[1:]:
                tds = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if tds and tds[0]:
                    name = tds[0].rstrip("+").strip()
                    vals = tds[1:len(date_cols) + 1]
                    metric_rows[name] = vals

            total_chunks = 0
            indexed_quarters = []

            # 1. Ingest each quarter's results as a dedicated document
            for idx, col_date in enumerate(date_cols):
                fy, q = parse_screener_quarter(col_date)
                if fy == "N/A" or q == "N/A":
                    continue

                def _get_val(m_name: str) -> str:
                    for k, v in metric_rows.items():
                        if m_name.lower() in k.lower() and idx < len(v):
                            return v[idx]
                    return "N/A"

                sales = _get_val("Sales")
                expenses = _get_val("Expenses")
                op_profit = _get_val("Operating Profit")
                opm = _get_val("OPM")
                other_inc = _get_val("Other Income")
                interest = _get_val("Interest")
                deprec = _get_val("Depreciation")
                pbt = _get_val("Profit before tax")
                tax = _get_val("Tax")
                net_profit = _get_val("Net Profit")
                eps = _get_val("EPS")

                q_text = (
                    f"{sym} Verified Consolidated Financial Results for {q} {fy} (Quarter ended {col_date}):\n"
                    f"- Sales / Revenue from Operations: Rs. {sales} Cr\n"
                    f"- Total Expenses: Rs. {expenses} Cr\n"
                    f"- Operating Profit: Rs. {op_profit} Cr (Operating Profit Margin: {opm})\n"
                    f"- Other Income: Rs. {other_inc} Cr\n"
                    f"- Finance Costs / Interest: Rs. {interest} Cr\n"
                    f"- Depreciation & Amortization: Rs. {deprec} Cr\n"
                    f"- Profit Before Tax (PBT): Rs. {pbt} Cr (Tax Rate: {tax})\n"
                    f"- Net Profit / PAT (Profit After Tax): Rs. {net_profit} Cr\n"
                    f"- Basic EPS: Rs. {eps}\n"
                    f"Accounting Basis: Consolidated | Source: Screener Verified Exchange Filings Data. All values in INR Crores."
                )

                chunk_count = ingest_text_document(
                    title=f"{sym} {q} {fy} Results",
                    content=q_text,
                    symbol=sym,
                    doc_type="results",
                    fiscal_year=fy,
                    quarter=q,
                    basis="consolidated",
                    source=f"{sym}_quarterly_results_{fy}_{q}.txt"
                )
                total_chunks += chunk_count
                indexed_quarters.append(f"{q} {fy} ({col_date})")

            # 2. Build and ingest comprehensive multi-quarter comparison markdown table
            header_line = "| Metric | " + " | ".join([f"{col} ({parse_screener_quarter(col)[1]} {parse_screener_quarter(col)[0]})" for col in date_cols]) + " |"
            sep_line = "| --- | " + " | ".join(["---"] * len(date_cols)) + " |"
            table_rows = [header_line, sep_line]

            for m_name, vals in metric_rows.items():
                row_str = f"| {m_name} | " + " | ".join(vals) + " |"
                table_rows.append(row_str)

            summary_table_md = (
                f"### {sym} Consolidated Quarterly Financial Results Multi-Quarter History ({date_cols[0]} to {date_cols[-1]})\n"
                f"Accounting Basis: Consolidated | All figures in Rs. Crores (except EPS in Rs).\n"
                f"Source: Screener Verified Exchange Filings Data.\n\n"
                + "\n".join(table_rows)
            )

            summary_chunks = ingest_text_document(
                title=f"{sym} Consolidated Quarterly History Table",
                content=summary_table_md,
                symbol=sym,
                doc_type="results",
                fiscal_year="Multi",
                quarter="Multi",
                basis="consolidated",
                source=f"{sym}_consolidated_quarterly_history.txt"
            )
            total_chunks += summary_chunks

            # Record sync flag
            with open(flag_file, "w", encoding="utf-8") as f:
                json.dump({
                    "symbol": sym,
                    "synced_at": time.time(),
                    "quarters_count": len(indexed_quarters),
                    "quarters": indexed_quarters,
                    "total_chunks": total_chunks
                }, f, indent=2)

            return {
                "status": "success",
                "message": f"Successfully indexed {len(indexed_quarters)} quarters of financial results for {sym}.",
                "quarters_count": len(indexed_quarters),
                "chunks": total_chunks
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed scraping quarterly results for {sym}: {str(e)}"}

def ensure_latest_filings(symbol: str, doc_type: str = "concall", force_check: bool = False) -> Dict[str, Any]:
    """
    Idempotent check: ensures the latest filing/concall/annual report is embedded in ChromaDB for `symbol`.
    Also automatically indexes multi-quarter financial results tables.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    target_doc = doc_type.strip().lower() if doc_type else "concall"

    # Always ensure multi-quarter results history is indexed into ChromaDB
    try:
        scrape_and_ingest_quarterly_table(sym, force=force_check)
    except Exception as e:
        print(f"[Filings] Quarterly table sync notice for {sym}: {e}")

    if target_doc == "results":
        return get_filings_status(sym)

    if not force_check:
        try:
            from app.rag.ingest import collection
            existing = collection.get(
                where={"$and": [{"symbol": sym}, {"kind": "filing"}, {"doc_type": target_doc}]},
                limit=1
            )
            if existing and existing.get("ids") and len(existing["ids"]) > 0:
                return get_filings_status(sym)
        except Exception:
            pass

    status = get_filings_status(sym)
    if status["indexed"] and target_doc == "concall" and not force_check:
        return status

    return download_and_ingest_latest_filing(sym, doc_type=target_doc)
