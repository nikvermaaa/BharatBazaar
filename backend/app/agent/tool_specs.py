TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Fetch historical and latest price summary (close, period high/low, % change, multi-horizon returns: 1D, 1M, 3M, 6M, YTD, 1Y) for an Indian stock (NSE/BSE in INR).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "NSE symbol or company name (e.g. RELIANCE, TCS, INFY, HDFCBANK, ITC)."
                    },
                    "days": {
                        "type": "integer",
                        "description": "Number of days of history to inspect (default 30)."
                    }
                },
                "required": ["ticker"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_indicators",
            "description": "Calculate deterministic technical indicators (RSI 14, MACD, 50-day SMA, 200-day SMA, 30-day volatility) using price series.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "NSE symbol or company name (e.g. RELIANCE, TCS, INFY)."
                    }
                },
                "required": ["ticker"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_filings",
            "description": "Search official corporate regulatory filings (Quarterly Results, Annual Reports, Investor Presentations, Concall Transcripts) via vector RAG. Autonomously indexes multi-quarter financial results tables and transcripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "NSE symbol or company name (e.g. RELIANCE, TCS)."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query describing what fact, metric, or topic you are looking for in the filing."
                    },
                    "fiscal_year": {
                        "type": "string",
                        "description": "Optional Indian fiscal year filter (e.g. FY24, FY25, FY26)."
                    },
                    "doc_type": {
                        "type": "string",
                        "description": "Optional document type filter: 'results', 'annual_report', 'presentation', 'concall', or 'shareholding'."
                    }
                },
                "required": ["ticker", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Search recent (3-day) and historical (up to 1 year) deduplicated corporate news event clusters from Indian financial dailies (Economic Times, LiveMint, Business Standard, Reuters, Moneycontrol) for market context, catalysts, and risks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {
                        "type": "string",
                        "description": "NSE symbol or company name (e.g. RELIANCE, TCS, INFY)."
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query for news event, development, management action, historical trend, or market risk/catalyst."
                    }
                },
                "required": ["ticker", "query"]
            }
        }
    }
]
