import os
import re
import json
import time
import math
import hashlib
import html
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import feedparser
from app.config import NEWS_DIR, GEMINI_API_KEY
from app.data_sources.companies import resolve_ticker, company_info, list_companies

RSS_FEEDS = [
    {
        "outlet": "Economic Times - Stocks",
        "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"
    },
    {
        "outlet": "Economic Times - Industry",
        "url": "https://economictimes.indiatimes.com/industry/rssfeeds/13352306.cms"
    },
    {
        "outlet": "LiveMint - Companies",
        "url": "https://www.livemint.com/rss/companies"
    },
    {
        "outlet": "LiveMint - Markets",
        "url": "https://www.livemint.com/rss/markets"
    },
    {
        "outlet": "Business Standard - Companies",
        "url": "https://www.business-standard.com/rss/companies-101.rss"
    }
]

def _news_file(symbol: str) -> str:
    return str(Path(NEWS_DIR) / f"{symbol.upper()}_news.json")

def _clean_html(text: str) -> str:
    if not text:
        return ""
    unescaped = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", cleaned).strip()

def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

def _simple_text_vector(text: str, vocab: Dict[str, int]) -> List[float]:
    """Lightweight bag-of-words vector with sublinear term-frequency."""
    import re
    words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", text.lower())
    vec = [0.0] * len(vocab)
    for w in words:
        if w in vocab:
            vec[vocab[w]] += 1.0
    # Normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec

def cluster_raw_articles(articles: List[Dict[str, Any]], similarity_threshold: float = 0.65) -> List[Dict[str, Any]]:
    """
    Mathematical cosine clustering algorithm adapted from news-aggregator-engine.
    Groups news stories covering the identical event into an ArticleCluster.
    """
    if not articles:
        return []

    # Build shared vocabulary for the batch
    import re
    vocab: Dict[str, int] = {}
    for art in articles:
        text = f"{art.get('title', '')} {art.get('summary', '')}".lower()
        for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", text):
            if w not in vocab:
                vocab[w] = len(vocab)

    vectors = [_simple_text_vector(f"{a['title']} {a.get('summary', '')}", vocab) for a in articles]
    
    assigned = [False] * len(articles)
    clusters: List[Dict[str, Any]] = []

    for i in range(len(articles)):
        if assigned[i]:
            continue
            
        cluster_articles = [articles[i]]
        assigned[i] = True

        for j in range(i + 1, len(articles)):
            if assigned[j]:
                continue
            sim = _cosine_similarity(vectors[i], vectors[j])
            if sim >= similarity_threshold:
                cluster_articles.append(articles[j])
                assigned[j] = True

        # Synthesize cluster record
        primary = cluster_articles[0]
        outlets = list(dict.fromkeys(a.get("outlet", "News") for a in cluster_articles if a.get("outlet")))
        
        # Determine latest timestamp and date among cluster articles
        pub_timestamps = [a.get("published_ts") for a in cluster_articles if a.get("published_ts")]
        latest_ts = max(pub_timestamps) if pub_timestamps else 0
        display_date = primary.get("published", "")[:16]
        for a in cluster_articles:
            if a.get("published_ts") == latest_ts and a.get("published"):
                display_date = a.get("published", "")[:16]
                break
        
        cluster_id = hashlib.md5(primary["title"].encode("utf-8")).hexdigest()[:10]
        clusters.append({
            "cluster_id": cluster_id,
            "theme_title": primary["title"],
            "date": display_date,
            "published_ts": latest_ts,
            "article_count": len(cluster_articles),
            "outlets": outlets,
            "summary": primary.get("summary", primary["title"]),
            "sources": [
                {
                    "outlet": a.get("outlet", "News"),
                    "title": a.get("title"),
                    "url": a.get("url", ""),
                    "published": a.get("published", ""),
                    "published_ts": a.get("published_ts"),
                    "priority_score": a.get("priority_score", 10)
                }
                for a in cluster_articles
            ]
        })

    return clusters

def get_company_search_terms(sym: str) -> List[str]:
    """Compile search terms and aliases for a company."""
    terms = []
    info = company_info(sym)
    terms.append(sym)
    if info:
        name = info["name"]
        clean_name = re.sub(r"(?i)\s+(limited|ltd\.?|corporation|inc\.?|\(india\))\b", "", name).strip()
        if clean_name and clean_name not in terms:
            terms.append(clean_name)
        if name not in terms:
            terms.append(name)
        for a in info.get("aliases", []):
            a_clean = a.strip()
            if a_clean and a_clean not in terms:
                terms.append(a_clean)
    return terms

MARKET_BEHAVIOR_TERMS = [
    "share price", "stock price", "shares jump", "shares surge", "shares fall",
    "shares plunge", "shares drop", "shares rally", "shares slip", "rallies",
    "52-week", "target price", "target", "chart", "breakout", "rsi", "technical", "trading",
    "quarterly results", "q1", "q2", "q3", "q4", "net profit", "earnings",
    "revenue", "ebitda", "margin", "loss", "profit", "stock", "stocks", "market", "brokerage"
]

BIG_EVENT_TERMS = [
    "acquisition", "acquire", "merger", "stake", "joint venture", "ipo",
    "demerger", "dividend", "bonus", "contract", "order win", "invests",
    "investment", "sebi", "rbi", "expansion", "ceo", "board meeting", "deal"
]

def check_relevance(art: Dict[str, Any], search_terms: List[str]) -> Tuple[bool, int]:
    """
    Strict regex whole-word matching to eliminate unrelated articles,
    with priority scoring for market price behavior, charts, and major corporate events.
    Returns (is_relevant, relevance_score).
    """
    title = art.get("title", "")
    summary = art.get("summary", "")
    full_text = f"{title} {summary}".lower()
    
    matched_term = False
    base_score = 0
    common_dictionary_tickers = {"reliance", "titan", "idea", "target", "power", "sun", "sail"}
    for term in search_terms:
        if len(term) < 2:
            continue
            
        pattern = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
        
        m_title = pattern.search(title)
        if m_title:
            matched_word = m_title.group(0)
            if term.lower() in common_dictionary_tickers and matched_word.islower():
                pass  # False positive like "reliance on suppliers"
            else:
                matched_term = True
                base_score = max(base_score, 12)

        m_sum = pattern.search(summary)
        if m_sum:
            matched_word = m_sum.group(0)
            if term.lower() in common_dictionary_tickers and matched_word.islower():
                pass
            else:
                matched_term = True
                base_score = max(base_score, 4)
            
    if not matched_term:
        return (False, 0)
        
    score = base_score
    
    # Priority 1: Stock Market / Price Behavior / Indicators / Earnings
    for t in MARKET_BEHAVIOR_TERMS:
        if re.search(r"\b" + re.escape(t) + r"\b", full_text):
            score += 15
            break

    # Priority 2: Major Corporate Events (M&A, IPO, Deals)
    for t in BIG_EVENT_TERMS:
        if re.search(r"\b" + re.escape(t) + r"\b", full_text):
            score += 10
            break

    # Priority 3: Freshness / Recency boost
    pub_ts = art.get("published_ts")
    if pub_ts:
        age_hours = (time.time() - pub_ts) / 3600
        if age_hours <= 24:
            score += 8
        elif age_hours <= 48:
            score += 4
        elif age_hours <= 72:
            score += 2

    return (True, score)

def fetch_rss_headlines() -> List[Dict[str, Any]]:
    """Fetch raw headlines from general Indian financial RSS feeds."""
    raw_articles = []
    
    for feed in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed["url"])
            outlet = feed["outlet"]
            for entry in parsed.entries[:25]:
                title = _clean_html(entry.get("title", ""))
                summary = _clean_html(entry.get("summary", ""))
                link = entry.get("link", "").strip()
                published = entry.get("published", entry.get("updated", ""))
                
                pub_ts = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub_ts = time.mktime(entry.published_parsed)
                    except Exception:
                        pass
                
                if title:
                    raw_articles.append({
                        "outlet": outlet,
                        "title": title,
                        "summary": summary,
                        "url": link,
                        "published": published,
                        "published_ts": pub_ts
                    })
        except Exception:
            continue

    return raw_articles

def _parse_google_news_feed(url: str, max_days: int = 4) -> List[Dict[str, Any]]:
    articles = []
    try:
        parsed = feedparser.parse(url)
        now_ts = time.time()
        max_age_sec = (max_days * 24 + 12) * 3600
        
        for entry in parsed.entries[:60]:
            raw_title = entry.get("title", "").strip()
            summary_raw = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            published = entry.get("published", entry.get("updated", ""))
            
            pub_ts = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_ts = time.mktime(entry.published_parsed)
                    if (now_ts - pub_ts) > max_age_sec:
                        continue  # Skip news older than max_days
                except Exception:
                    pass
            
            outlet = "Financial Media"
            if "source" in entry and isinstance(entry["source"], dict) and "title" in entry["source"]:
                outlet = entry["source"]["title"].strip()
            elif " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                outlet = parts[1].strip()
                raw_title = parts[0].strip()
                
            clean_title = _clean_html(raw_title)
            clean_summary = _clean_html(summary_raw)
            
            if clean_title:
                articles.append({
                    "outlet": outlet,
                    "title": clean_title,
                    "summary": clean_summary,
                    "url": link,
                    "published": published,
                    "published_ts": pub_ts
                })
    except Exception:
        pass
    return articles

def fetch_google_news_for_company(symbol: str, max_days: int = 4) -> List[Dict[str, Any]]:
    """
    Query Google News RSS for targeted Indian stock headlines.
    Restricts results to the last 3-4 days (or max 7 days if few articles).
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    info = company_info(sym)
    
    name = info["name"] if info else sym
    clean_name = re.sub(r"(?i)\s+(limited|ltd\.?|corporation|inc\.?|\(india\))\b", "", name).strip()
    
    if clean_name.lower() != sym.lower():
        query_base = f'"{clean_name}" OR "{sym}"'
    else:
        query_base = f'"{sym}" stock'
        
    # Try last 3 days first
    url_3d = f"https://news.google.com/rss/search?q={urllib.parse.quote(query_base + ' when:3d')}&hl=en-IN&gl=IN&ceid=IN:en"
    articles = _parse_google_news_feed(url_3d, max_days=max_days)
    
    # Fallback to 7 days if fewer than 5 articles found
    if len(articles) < 5:
        url_7d = f"https://news.google.com/rss/search?q={urllib.parse.quote(query_base + ' when:7d')}&hl=en-IN&gl=IN&ceid=IN:en"
        articles = _parse_google_news_feed(url_7d, max_days=7)
        
    return articles

def _extract_cluster_ts(c: Dict[str, Any]) -> float:
    """Extract exact epoch timestamp for a cluster, checking sources for seconds precision."""
    best_ts = 0.0
    import email.utils
    for s in c.get("sources", []):
        if not isinstance(s, dict):
            continue
        if s.get("published_ts") and float(s["published_ts"]) > best_ts:
            best_ts = float(s["published_ts"])
        pub_str = s.get("published", "")
        if pub_str:
            try:
                dt = email.utils.parsedate_to_datetime(pub_str)
                ts = dt.timestamp()
                if ts > best_ts:
                    best_ts = ts
            except Exception:
                pass
    if best_ts > 0:
        return best_ts

    ts = c.get("published_ts")
    if ts and isinstance(ts, (int, float)) and float(ts) > 0:
        return float(ts)

    date_str = c.get("date", "")
    if date_str:
        try:
            parsed = email.utils.parsedate_to_datetime(date_str)
            return parsed.timestamp()
        except Exception:
            pass
        from datetime import datetime
        for fmt in ("%a, %d %b %Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(date_str[:16].strip(), fmt)
                return dt.timestamp()
            except Exception:
                pass
    return 0.0

def refresh_news_for_company(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch live targeted news (last 3-4 days), strictly filter by whole-word regex and
    market behavior relevance, mathematically cluster identical events, and return TOP 10.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    search_terms = get_company_search_terms(sym)
    
    # 1. Fetch targeted company articles within the 3-day freshness window
    google_articles = fetch_google_news_for_company(sym, max_days=4)
    
    # 2. Fetch general RSS feeds
    general_articles = fetch_rss_headlines()
    
    # 3. Combine articles and deduplicate by URL or normalized title
    combined = []
    seen = set()
    for art in google_articles + general_articles:
        key = art.get("url") or art.get("title", "").lower()[:60]
        if key not in seen:
            seen.add(key)
            combined.append(art)
            
    # 4. Strict relevance filtering and priority scoring
    scored_articles = []
    for art in combined:
        is_rel, score = check_relevance(art, search_terms)
        if is_rel:
            art["priority_score"] = score
            scored_articles.append((score, art))
            
    # Sort articles by priority score descending
    scored_articles.sort(key=lambda x: x[0], reverse=True)
    matched_articles = [item[1] for item in scored_articles[:30]]
    
    # 5. Cluster matched articles using cosine similarity (threshold 0.60)
    clusters = cluster_raw_articles(matched_articles, similarity_threshold=0.60)
    
    # 6. Rank clusters by recency (most recent to oldest):
    for c in clusters:
        src_scores = [s.get("priority_score", 10) for s in c.get("sources", []) if isinstance(s, dict)]
        base_c_score = max(src_scores) if src_scores else 10
        multi_outlet_bonus = (len(c.get("outlets", [])) - 1) * 6
        c["priority_score"] = base_c_score + multi_outlet_bonus
        if not c.get("published_ts"):
            c["published_ts"] = _extract_cluster_ts(c)
        
    # Sort clusters strictly by recency (most recent to oldest) with priority score as tiebreaker
    clusters.sort(key=lambda c: (_extract_cluster_ts(c), c.get("priority_score", 0)), reverse=True)
    
    # 7. Strictly limit to top 10 news clusters (no endless scroll overload)
    top_10_clusters = clusters[:10]
    
    # 8. Save to cache
    cache_path = _news_file(sym)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(top_10_clusters, f, indent=2)
        
    return top_10_clusters

def load_news_clusters(symbol: str, max_age_hours: int = 1) -> List[Dict[str, Any]]:
    """Load cached news clusters or refresh if stale."""
    sym = resolve_ticker(symbol) or symbol.upper()
    file_path = _news_file(sym)

    if not os.path.exists(file_path):
        return refresh_news_for_company(sym)
        
    age = time.time() - os.path.getmtime(file_path)
    if age > (max_age_hours * 3600):
        try:
            return refresh_news_for_company(sym)
        except Exception:
            pass

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            for c in data:
                if not c.get("published_ts"):
                    c["published_ts"] = _extract_cluster_ts(c)
            data.sort(key=lambda c: (_extract_cluster_ts(c), c.get("priority_score", 0)), reverse=True)
        return data

def _historical_news_file(symbol: str) -> str:
    return str(Path(NEWS_DIR) / f"{symbol.upper()}_historical_news.json")

def fetch_historical_google_news(symbol: str, max_days: int = 365) -> List[Dict[str, Any]]:
    """
    Query Google News RSS for up to 1-year of Indian financial headlines for `symbol`.
    Clusters and ranks major market catalysts, quarterly performance, and corporate risks.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    info = company_info(sym)
    name = info["name"] if info else sym
    clean_name = re.sub(r"(?i)\s+(limited|ltd\.?|corporation|inc\.?|\(india\))\b", "", name).strip()
    search_terms = get_company_search_terms(sym)

    if clean_name.lower() != sym.lower():
        query_base = f'"{clean_name}" OR "{sym}" stock'
    else:
        query_base = f'"{sym}" stock'

    url_1y = f"https://news.google.com/rss/search?q={urllib.parse.quote(query_base + ' when:1y')}&hl=en-IN&gl=IN&ceid=IN:en"
    raw_articles = _parse_google_news_feed(url_1y, max_days=max_days)

    if not raw_articles:
        return []

    scored_articles = []
    for art in raw_articles:
        is_rel, score = check_relevance(art, search_terms)
        if is_rel:
            art["priority_score"] = score
            scored_articles.append((score, art))

    scored_articles.sort(key=lambda x: x[0], reverse=True)
    matched_articles = [item[1] for item in scored_articles[:60]]

    clusters = cluster_raw_articles(matched_articles, similarity_threshold=0.60)

    for c in clusters:
        src_scores = [s.get("priority_score", 10) for s in c.get("sources", []) if isinstance(s, dict)]
        base_c_score = max(src_scores) if src_scores else 10
        multi_outlet_bonus = (len(c.get("outlets", [])) - 1) * 6
        c["priority_score"] = base_c_score + multi_outlet_bonus
        if not c.get("published_ts"):
            c["published_ts"] = _extract_cluster_ts(c)

    clusters.sort(key=lambda c: (_extract_cluster_ts(c), c.get("priority_score", 0)), reverse=True)

    cache_path = _historical_news_file(sym)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(clusters[:30], f, indent=2)

    return clusters[:30]

def load_historical_news_clusters(symbol: str, max_age_hours: int = 24) -> List[Dict[str, Any]]:
    """Load cached 1-year historical news clusters or refresh if stale."""
    sym = resolve_ticker(symbol) or symbol.upper()
    file_path = _historical_news_file(sym)

    if not os.path.exists(file_path):
        try:
            return fetch_historical_google_news(sym, max_days=365)
        except Exception:
            return []

    age = time.time() - os.path.getmtime(file_path)
    if age > (max_age_hours * 3600):
        try:
            return fetch_historical_google_news(sym, max_days=365)
        except Exception:
            pass

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for c in data:
                    if not c.get("published_ts"):
                        c["published_ts"] = _extract_cluster_ts(c)
                data.sort(key=lambda c: (_extract_cluster_ts(c), c.get("priority_score", 0)), reverse=True)
            return data
    except Exception:
        return []

def search_news_events(symbol: str, query: str) -> Dict[str, Any]:
    """
    Search clustered news events for a company across both recent (3-day)
    and 1-year historical archives.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    recent_clusters = load_news_clusters(sym)
    historical_clusters = load_historical_news_clusters(sym)

    # Deduplicate clusters by cluster_id and headline
    seen_ids = set()
    combined_clusters = []
    for c in (recent_clusters + historical_clusters):
        cid = c.get("cluster_id") or c.get("theme_title", "")[:40].lower()
        if cid not in seen_ids:
            seen_ids.add(cid)
            combined_clusters.append(c)

    if not combined_clusters:
        return {
            "symbol": sym,
            "results": [],
            "note": f"No news event clusters recorded for {sym}."
        }

    q_lower = query.lower()
    q_words = [w for w in re.findall(r"\b[a-zA-Z0-9]{3,}\b", q_lower) if w not in {"the", "and", "for", "with", "about", "what", "any", "are"}]
    matches = []

    for c in combined_clusters:
        text = f"{c.get('theme_title', '')} {c.get('summary', '')}".lower()
        score = sum(1 for w in q_words if w in text)
        if score > 0:
            matches.append((score, {
                "headline": c["theme_title"],
                "summary": c["summary"][:500],
                "date": c["date"],
                "outlets": c["outlets"],
                "sources": c["sources"][:3],
                "symbol": sym,
                "kind": "news_cluster"
            }))

    # Sort matches by query overlap score descending
    matches.sort(key=lambda x: x[0], reverse=True)
    match_results = [m[1] for m in matches[:6]]

    # If no keyword matches, return a mix of top recent and top historical clusters
    if not match_results:
        match_results = [
            {
                "headline": c["theme_title"],
                "summary": c["summary"][:500],
                "date": c["date"],
                "outlets": c["outlets"],
                "sources": c["sources"][:3],
                "symbol": sym,
                "kind": "news_cluster"
            }
            for c in combined_clusters[:6]
        ]

    return {
        "symbol": sym,
        "query": query,
        "results": match_results,
        "note": f"Found {len(match_results)} corroborated news event cluster(s) from past year."
    }
