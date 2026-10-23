import pytest
from app.data_sources.news import (
    check_relevance,
    get_company_search_terms,
    cluster_raw_articles
)

def test_company_search_terms():
    terms_rel = get_company_search_terms("RELIANCE")
    assert "RELIANCE" in terms_rel
    assert "Reliance Industries" in terms_rel
    assert "RIL" in terms_rel

    terms_jio = get_company_search_terms("JIOFIN")
    assert "JIOFIN" in terms_jio
    assert "Jio Financial Services" in terms_jio

def test_strict_regex_relevance_rejects_substrings():
    # RIL should NOT match "April 2025"
    search_terms = ["RELIANCE", "Reliance Industries", "RIL"]
    unrelated_art = {
        "title": "UBS acquires 4.8% stake in wealth manager",
        "summary": "The transaction follows a partnership announced in April 2025 by global firms."
    }
    is_rel, score = check_relevance(unrelated_art, search_terms)
    assert not is_rel
    assert score == 0

    # RIL SHOULD match when RIL is a whole word
    related_art = {
        "title": "RIL stock surges 3% ahead of quarterly earnings",
        "summary": "Reliance Industries reported robust operational growth."
    }
    is_rel, score = check_relevance(related_art, search_terms)
    assert is_rel
    assert score > 0

def test_jio_financial_relevance():
    jio_terms = ["JIOFIN", "Jio Financial Services", "Jio Financial", "JFSL"]
    
    # Genuine Jio Financial news
    art1 = {
        "title": "Jio Financial Services net profit rises 3% in Q2",
        "summary": "JFSL expanded lending book to retail and merchant segments."
    }
    is_rel, score = check_relevance(art1, jio_terms)
    assert is_rel
    assert score >= 10  # Title match

    # News that has nothing to do with Jio Financial
    art2 = {
        "title": "Tata Motors reports decline in domestic commercial vehicle sales",
        "summary": "Passenger vehicles remained steady."
    }
    is_rel, score = check_relevance(art2, jio_terms)
    assert not is_rel
    assert score == 0

def test_multi_outlet_corroboration_clustering():
    articles = [
        {
            "outlet": "Reuters",
            "title": "India's Jio Financial posts higher adjusted profit on lending growth",
            "summary": "Jio Financial Services posted higher adjusted profit driven by retail lending.",
            "url": "https://reuters.example.com/jio",
            "published": "2026-10-22 10:00"
        },
        {
            "outlet": "Moneycontrol",
            "title": "Jio Financial Q2 results: Net profit up on loan growth",
            "summary": "Jio Financial Services reported profit growth supported by its lending arm.",
            "url": "https://moneycontrol.example.com/jio",
            "published": "2026-10-22 10:05"
        },
        {
            "outlet": "Livemint",
            "title": "Jio Financial Q2 net profit jumps on retail lending beat",
            "summary": "Shares of Jio Financial Services rallied on strong lending growth.",
            "url": "https://livemint.example.com/jio",
            "published": "2026-10-22 10:30"
        }
    ]
    clusters = cluster_raw_articles(articles, similarity_threshold=0.55)
    assert len(clusters) == 1
    c = clusters[0]
    assert c["article_count"] == 3
    assert "Reuters" in c["outlets"]
    assert "Moneycontrol" in c["outlets"]
    assert "Livemint" in c["outlets"]
    assert len(c["sources"]) == 3

def test_market_behavior_priority_boost():
    search_terms = ["RELIANCE", "Reliance Industries"]
    
    # Article with stock market/price action
    market_art = {
        "title": "Reliance Industries share price surges 3% on breakout",
        "summary": "Technical indicators suggest bullish momentum."
    }
    _, market_score = check_relevance(market_art, search_terms)
    
    # Generic CSR article
    csr_art = {
        "title": "Reliance Industries sponsors green energy youth summit",
        "summary": "Community program launched across western states."
    }
    _, csr_score = check_relevance(csr_art, search_terms)
    
    # Market behavior must score significantly higher
    assert market_score > csr_score
    assert market_score >= 25

def test_cluster_published_timestamp_and_recency():
    articles = [
        {
            "outlet": "Mint",
            "title": "Reliance Q2 Results Announced",
            "summary": "Reliance announced strong results.",
            "url": "https://mint.com/1",
            "published": "2026-10-20 10:00",
            "published_ts": 1792470000.0
        },
        {
            "outlet": "Bloomberg",
            "title": "Reliance Retail Expansion in Metro Cities",
            "summary": "Reliance expands offline retail presence.",
            "url": "https://bloomberg.com/2",
            "published": "2026-10-22 14:00",
            "published_ts": 1792657200.0
        }
    ]
    clusters = cluster_raw_articles(articles, similarity_threshold=0.8)
    assert len(clusters) == 2
    # Verify published_ts is populated
    assert all("published_ts" in c for c in clusters)
    # When sorted by recency descending, the newer one comes first
    clusters.sort(key=lambda c: (c.get("published_ts") or 0), reverse=True)
    assert clusters[0]["published_ts"] > clusters[1]["published_ts"]
    assert "Reliance Retail" in clusters[0]["theme_title"]

