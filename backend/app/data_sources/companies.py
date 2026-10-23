import os
import csv
from pathlib import Path
from difflib import get_close_matches
from typing import Optional, Dict, List
from app.config import DATA_DIR

_companies_file = Path(DATA_DIR) / "companies.csv"

def _norm(s: str) -> str:
    if not s:
        return ""
    return s.strip().lower().replace(".ns", "").replace(".bo", "").replace("-", " ")

_companies_list: List[Dict] = []
_index: Dict[str, str] = {}
_symbols_map: Dict[str, Dict] = {}

def _load_data():
    global _companies_list, _index, _symbols_map
    if not _companies_file.exists():
        return
    _companies_list = []
    _index = {}
    _symbols_map = {}
    
    with open(_companies_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("nse_symbol", "").strip().upper()
            if not sym:
                continue
            item = {
                "name": row.get("name", "").strip(),
                "nse_symbol": sym,
                "bse_code": row.get("bse_code", "").strip(),
                "sector": row.get("sector", "Equity").strip(),
                "aliases": [a.strip() for a in row.get("aliases", "").split(";") if a.strip()]
            }
            _companies_list.append(item)
            _symbols_map[sym] = item
            
            # Index all matchable terms
            keys = [item["name"], sym, item["bse_code"]] + item["aliases"]
            for k in keys:
                norm_k = _norm(k)
                if norm_k:
                    _index[norm_k] = sym

_load_data()

def reload_companies():
    """Reload company index from disk."""
    _load_data()

def resolve_ticker(text: str) -> Optional[str]:
    """
    Resolve user-entered text or ticker to canonical NSE symbol.
    Uses exact lookup first, then fuzzy matching on known aliases.
    """
    if not text:
        return None
    k = _norm(text)
    if k in _index:
        return _index[k]
    
    matches = get_close_matches(k, _index.keys(), n=1, cutoff=0.82)
    if matches:
        return _index[matches[0]]
    
    raw_upper = text.strip().upper().replace(".NS", "").replace(".BO", "")
    if raw_upper in _symbols_map:
        return raw_upper
        
    return None

def company_info(symbol: str) -> Optional[Dict]:
    """Return company metadata row for canonical NSE symbol."""
    sym = symbol.strip().upper()
    return _symbols_map.get(sym)

def list_companies() -> List[Dict]:
    """Return all tracked companies."""
    return _companies_list

def search_companies(query: str, limit: int = 25) -> List[Dict]:
    """
    Fast prefix and substring search for typeahead autocomplete.
    Matches against symbol, company name, and aliases.
    """
    if not query or not query.strip():
        return _companies_list[:limit]
        
    q = query.strip().lower()
    prefix_matches = []
    substring_matches = []
    
    for c in _companies_list:
        sym_lower = c["nse_symbol"].lower()
        name_lower = c["name"].lower()
        
        # Priority 1: Symbol starts with query (e.g. "RE" -> RELIANCE, REDINGTON)
        if sym_lower.startswith(q):
            prefix_matches.append(c)
        # Priority 2: Company name starts with query (e.g. "Rel" -> Reliance Industries)
        elif name_lower.startswith(q) or any(a.lower().startswith(q) for a in c.get("aliases", [])):
            prefix_matches.append(c)
        # Priority 3: Contains query anywhere
        elif q in sym_lower or q in name_lower or any(q in a.lower() for a in c.get("aliases", [])):
            substring_matches.append(c)
            
        if len(prefix_matches) >= limit * 2:
            break

    seen = set()
    result = []
    for item in (prefix_matches + substring_matches):
        if item["nse_symbol"] not in seen:
            seen.add(item["nse_symbol"])
            result.append(item)
            if len(result) >= limit:
                break
    return result

def find_companies_in_text(text: str) -> List[Dict]:
    """
    Scans a free-form text message for mentions of tracked Indian companies and tickers.
    Supports multi-company detection for peer comparisons.
    """
    if not text:
        return []
    import re
    norm_text = _norm(text)
    found = []
    seen_syms = set()

    all_candidates = []
    for c in _companies_list:
        sym = c["nse_symbol"]
        aliases = [c["name"], sym] + c.get("aliases", [])
        for a in aliases:
            norm_a = _norm(a)
            if len(norm_a) >= 3 and norm_a not in {"ltd", "limited", "bank", "corp", "industries", "company", "india", "financial", "services"}:
                all_candidates.append((norm_a, c))

    # Sort longer names first so "Reliance Jio" or "Bharti Airtel" claims spans before shorter words
    all_candidates.sort(key=lambda x: len(x[0]), reverse=True)
    claimed_spans = []

    for cand_norm, c in all_candidates:
        sym = c["nse_symbol"]
        if sym in seen_syms:
            continue
        pattern = re.compile(r"\b" + re.escape(cand_norm) + r"\b")
        for match in pattern.finditer(norm_text):
            start, end = match.span()
            if any(not (end <= cs or start >= ce) for cs, ce in claimed_spans):
                continue
            claimed_spans.append((start, end))
            seen_syms.add(sym)
            found.append(c)
            break

    return found
