import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agent.agent import run_agent
from app.data_sources.companies import list_companies, resolve_ticker, company_info
from app.data_sources.news import load_news_clusters, refresh_news_for_company
from app.agent.tools import get_price_history, compute_indicators
from app.rag.ingest import ingest_pdf, ingest_text_document

app = FastAPI(
    title="India Stock Research Agent",
    description="Research terminal for Indian equities (NSE/BSE) with deterministic tools, filing RAG, and clustered news."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    ticker: Optional[str] = None

class IngestTextRequest(BaseModel):
    symbol: str
    title: str
    content: str
    doc_type: str
    fiscal_year: str
    quarter: Optional[str] = "Annual"
    basis: Optional[str] = "consolidated"

@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Query message cannot be empty.")
    return run_agent(req.message, req.ticker)

@app.get("/api/tickers")
def get_tickers():
    return {"companies": list_companies()[:50]}

@app.get("/api/tickers/search")
def search_tickers_endpoint(q: str = "", limit: int = 25):
    from app.data_sources.companies import search_companies
    return {"query": q, "results": search_companies(q, limit=limit)}

def sanitize_floats(obj: Any) -> Any:
    """Recursively replaces any NaN or Inf floats with None for valid JSON compliance."""
    import math
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_floats(v) for v in obj]
    return obj

@app.get("/api/tickers/{symbol}/overview")
def get_company_overview(symbol: str):
    sym = resolve_ticker(symbol)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Company '{symbol}' not found.")
    
    info = company_info(sym)
    prices = get_price_history(sym, days=30)
    indicators = compute_indicators(sym)
    
    from app.data_sources.filings import get_filings_status, ensure_latest_filings
    filing_status = get_filings_status(sym)
    if not filing_status.get("indexed"):
        import threading
        threading.Thread(target=ensure_latest_filings, args=(sym,), daemon=True).start()
    
    return sanitize_floats({
        "company": info,
        "price_summary": prices,
        "indicators": indicators,
        "filings": filing_status
    })

@app.get("/api/filings/{symbol}/status")
def get_filings_status_endpoint(symbol: str):
    sym = resolve_ticker(symbol)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Company '{symbol}' not found.")
    from app.data_sources.filings import get_filings_status
    return get_filings_status(sym)

@app.post("/api/filings/{symbol}/sync")
def sync_filings_endpoint(symbol: str):
    sym = resolve_ticker(symbol)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Company '{symbol}' not found.")
    from app.data_sources.filings import ensure_latest_filings
    res = ensure_latest_filings(sym, force_check=True)
    return res

@app.get("/api/news/clusters/{symbol}")
def get_news_clusters(symbol: str, refresh: bool = False):
    sym = resolve_ticker(symbol)
    if not sym:
        raise HTTPException(status_code=404, detail=f"Company '{symbol}' not found.")
    
    if refresh:
        clusters = refresh_news_for_company(sym)
    else:
        clusters = load_news_clusters(sym)
        
    return {"symbol": sym, "clusters": clusters}

@app.post("/api/ingest/text")
def ingest_text_endpoint(req: IngestTextRequest):
    chunks = ingest_text_document(
        title=req.title,
        content=req.content,
        symbol=req.symbol,
        doc_type=req.doc_type,
        fiscal_year=req.fiscal_year,
        quarter=req.quarter or "Annual",
        basis=req.basis or "consolidated",
        source=f"{req.title.replace(' ', '_')}.txt"
    )
    return {"status": "success", "chunks_indexed": chunks, "symbol": req.symbol}

@app.post("/api/ingest/pdf")
async def ingest_pdf_upload(
    file: UploadFile = File(...),
    symbol: str = Form(...),
    doc_type: str = Form(...),
    fiscal_year: str = Form(...),
    quarter: str = Form("Annual"),
    basis: str = Form("consolidated")
):
    from app.config import FILINGS_DIR
    target_dir = Path(FILINGS_DIR) / symbol.upper()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / file.filename
    
    with open(target_path, "wb") as f:
        content = await file.read()
        f.write(content)
        
    chunks = ingest_pdf(
        path=str(target_path),
        symbol=symbol,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        quarter=quarter,
        basis=basis
    )
    return {"status": "success", "filename": file.filename, "chunks_indexed": chunks}

# Mount static frontend
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
