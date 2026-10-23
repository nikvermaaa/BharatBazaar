from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class CompanySchema(BaseModel):
    name: str
    nse_symbol: str
    bse_code: str
    sector: str
    aliases: List[str] = []

class PriceSummarySchema(BaseModel):
    symbol: str
    company_name: str
    currency: str = "INR"
    as_of: str
    last_close: float
    period_days: int
    period_start: str
    period_high: float
    period_low: float
    change_pct: float
    source: str

class IndicatorSchema(BaseModel):
    symbol: str
    as_of: str
    last_close: float
    rsi_14: float
    macd: float
    macd_signal: float
    macd_hist: float
    sma_50: Any
    sma_200: Any
    price_vs_sma50_pct: Optional[float] = None
    price_vs_sma200_pct: Optional[float] = None
    annualized_volatility_30d_pct: float
    source: str
    note: str

class NewsClusterSource(BaseModel):
    outlet: str
    title: str
    url: str
    published: str

class NewsClusterSchema(BaseModel):
    cluster_id: str
    theme_title: str
    date: str
    article_count: int
    outlets: List[str]
    summary: str
    sources: List[NewsClusterSource]

class ChatRequestSchema(BaseModel):
    message: str = Field(..., description="User query about an Indian stock")
    ticker: Optional[str] = Field(None, description="Optional company ticker context")

class CitationSchema(BaseModel):
    type: str
    source: Optional[str] = None
    page: Optional[int] = None
    symbol: Optional[str] = None
    fiscal_year: Optional[str] = None
    url: Optional[str] = None

class ChatResponseSchema(BaseModel):
    answer: str
    sources: List[CitationSchema] = []
    tool_log: List[Dict[str, Any]] = []
