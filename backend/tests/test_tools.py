import pytest
from datetime import date
from app.data_sources.fiscal import fiscal_period, fiscal_period_str
from app.data_sources.companies import resolve_ticker, company_info
from app.agent.tools import _calc_rsi
from app.data_sources.news import cluster_raw_articles
import pandas as pd
import numpy as np

def test_fiscal_period():
    # End-year convention: April 2026 to March 2027 is FY27
    assert fiscal_period(date(2026, 4, 1)) == ("FY27", "Q1")
    assert fiscal_period(date(2026, 6, 30)) == ("FY27", "Q1")
    assert fiscal_period(date(2026, 7, 1)) == ("FY27", "Q2")
    assert fiscal_period(date(2026, 9, 30)) == ("FY27", "Q2")
    assert fiscal_period(date(2026, 10, 1)) == ("FY27", "Q3")
    assert fiscal_period(date(2026, 12, 31)) == ("FY27", "Q3")
    assert fiscal_period(date(2027, 1, 1)) == ("FY27", "Q4")
    assert fiscal_period(date(2027, 3, 31)) == ("FY27", "Q4")
    
    # New fiscal year starts April 1
    assert fiscal_period(date(2027, 4, 1)) == ("FY28", "Q1")
    assert fiscal_period_str(date(2026, 5, 10)) == "Q1 FY27"

def test_resolve_ticker():
    # Exact ticker
    assert resolve_ticker("RELIANCE") == "RELIANCE"
    assert resolve_ticker("TCS") == "TCS"
    assert resolve_ticker("INFY") == "INFY"
    
    # Suffixes and casing
    assert resolve_ticker("reliance.ns") == "RELIANCE"
    assert resolve_ticker("TCS.BO") == "TCS"
    assert resolve_ticker("  infy  ") == "INFY"
    
    # Aliases
    assert resolve_ticker("RIL") == "RELIANCE"
    assert resolve_ticker("Tata Consultancy") == "TCS"
    assert resolve_ticker("Infosys") == "INFY"
    
    # BSE code
    assert resolve_ticker("500325") == "RELIANCE"
    assert resolve_ticker("532540") == "TCS"
    
    # Unknown
    assert resolve_ticker("COMPLETELY_UNKNOWN_XYZ") is None

def test_rsi_bounds():
    # Monotonically increasing prices should have RSI > 70
    up = pd.Series([100 + i * 2 for i in range(30)])
    rsi_up = _calc_rsi(up, period=14).iloc[-1]
    assert 70.0 <= rsi_up <= 100.0

    # Monotonically decreasing prices should have RSI < 30
    down = pd.Series([200 - i * 2 for i in range(30)])
    rsi_down = _calc_rsi(down, period=14).iloc[-1]
    assert 0.0 <= rsi_down <= 30.0

def test_cosine_clustering():
    articles = [
        {
            "outlet": "Economic Times",
            "title": "Reliance Q2 profit rises 10% to Rs 19,000 crore on retail growth",
            "summary": "Reliance Industries reported consolidated net profit rise of 10% for the second quarter.",
            "url": "https://et.example.com/1",
            "published": "2026-10-20"
        },
        {
            "outlet": "LiveMint",
            "title": "Reliance Industries Q2 net profit jumps 10% to Rs 19,000 crore driven by retail and Jio",
            "summary": "RIL posted second quarter consolidated net profit of Rs 19,000 crore up 10% YoY.",
            "url": "https://mint.example.com/2",
            "published": "2026-10-20"
        },
        {
            "outlet": "Business Standard",
            "title": "Tata Motors commercial vehicle sales decline 5% in September",
            "summary": "Tata Motors reported a drop in domestic commercial vehicle sales for the month.",
            "url": "https://bs.example.com/3",
            "published": "2026-10-20"
        }
    ]

    clusters = cluster_raw_articles(articles, similarity_threshold=0.60)
    # The two Reliance articles should merge into 1 cluster
    assert len(clusters) == 2
    
    rel_cluster = [c for c in clusters if "Reliance" in c["theme_title"]][0]
    assert rel_cluster["article_count"] == 2
    assert "Economic Times" in rel_cluster["outlets"]
    assert "LiveMint" in rel_cluster["outlets"]
