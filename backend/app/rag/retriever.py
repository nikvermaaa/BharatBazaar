from typing import Dict, Any, Optional, List
from app.config import TOP_K
from app.rag.ingest import collection
from app.rag.embeddings import embedding_engine
from app.data_sources.companies import resolve_ticker

def search_filings_rag(
    symbol: str,
    query: str,
    fiscal_year: Optional[str] = None,
    doc_type: Optional[str] = None,
    k: int = TOP_K
) -> Dict[str, Any]:
    """
    Filtered semantic search in ChromaDB enforcing the single-company isolation rule.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    
    # Hierarchical filter strategy:
    # 1. Full filter: (symbol, kind: filing, fiscal_year, doc_type)
    # 2. Relax fiscal year: (symbol, kind: filing, doc_type)
    # 3. Relax doc_type: (symbol, kind: filing)
    # Company isolation (symbol: sym, kind: filing) is ALWAYS strictly preserved.
    filter_stages = []
    
    # Stage 1: Full filter
    base_1 = [{"symbol": sym}, {"kind": "filing"}]
    if fiscal_year:
        base_1.append({"fiscal_year": fiscal_year.strip().upper()})
    if doc_type:
        base_1.append({"doc_type": doc_type.strip().lower()})
    filter_stages.append(base_1)
    
    # Stage 2: Relax fiscal year if it was specified
    if fiscal_year:
        base_2 = [{"symbol": sym}, {"kind": "filing"}]
        if doc_type:
            base_2.append({"doc_type": doc_type.strip().lower()})
        filter_stages.append(base_2)
        
    # Stage 3: Relax doc_type as well
    if doc_type:
        base_3 = [{"symbol": sym}, {"kind": "filing"}]
        filter_stages.append(base_3)

    q_emb = embedding_engine.encode([query])
    
    results = None
    for stage_filters in filter_stages:
        where_filter = {"$and": stage_filters} if len(stage_filters) > 1 else stage_filters[0]
        try:
            res = collection.query(
                query_embeddings=q_emb,
                n_results=k,
                where=where_filter
            )
            if res and res.get("documents") and len(res["documents"]) > 0 and len(res["documents"][0]) > 0:
                results = res
                break
        except Exception:
            continue

    hits: List[Dict[str, Any]] = []
    if results and results.get("documents") and len(results["documents"]) > 0:
        docs = results["documents"][0]
        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
        for doc, meta in zip(docs, metas):
            hits.append({
                "text": doc,
                "source": meta.get("source", "filing"),
                "page": meta.get("page", 1),
                "fiscal_year": meta.get("fiscal_year", "N/A"),
                "quarter": meta.get("quarter", "N/A"),
                "basis": meta.get("basis", "consolidated"),
                "doc_type": meta.get("doc_type", "filing"),
                "symbol": sym,
                "url": meta.get("url", "")
            })

    if not hits:
        return {
            "symbol": sym,
            "query": query,
            "results": [],
            "note": f"I did not find this in the available filings for {sym}."
        }

    return {
        "symbol": sym,
        "query": query,
        "results": hits,
        "count": len(hits)
    }
