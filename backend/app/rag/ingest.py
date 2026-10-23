import os
import chromadb
from typing import List, Dict, Any, Generator, Tuple
from app.config import CHROMA_DIR
from app.rag.embeddings import embedding_engine
from app.data_sources.companies import resolve_ticker

chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
collection = chroma_client.get_or_create_collection(
    name="india_docs",
    metadata={"hnsw:space": "cosine"}
)

def pdf_pages(path: str) -> Generator[Tuple[int, str], None, None]:
    """Extract page number and raw text from a PDF file using PyMuPDF."""
    import fitz
    doc = fitz.open(path)
    for i, page in enumerate(doc, start=1):
        text = page.get_text().strip()
        if text:
            yield i, text

def chunk_text(text: str, size: int = 1000, overlap: int = 150) -> List[str]:
    """Windowed character chunking with overlap."""
    out = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + size, text_len)
        out.append(text[start:end])
        if end == text_len:
            break
        start += size - overlap
    return out

def ingest_pdf(
    path: str,
    symbol: str,
    doc_type: str,
    fiscal_year: str,
    quarter: str = "Annual",
    basis: str = "consolidated",
    url: str = ""
) -> int:
    """
    Ingest a company PDF filing into ChromaDB with Indian fiscal metadata.
    """
    sym = resolve_ticker(symbol) or symbol.upper()
    filename = os.path.basename(path)
    
    texts = []
    metas = []
    ids = []

    for page_no, page_text in pdf_pages(path):
        chunks = chunk_text(page_text, size=1000, overlap=150)
        for j, ch in enumerate(chunks):
            texts.append(ch)
            metas.append({
                "kind": "filing",
                "symbol": sym,
                "doc_type": doc_type.lower(),
                "fiscal_year": fiscal_year.upper(),
                "quarter": quarter.upper(),
                "basis": basis.lower(),
                "page": page_no,
                "source": filename,
                "url": url
            })
            ids.append(f"{sym}_{filename}_p{page_no}_c{j}")

    if not texts:
        print(f"[Ingest] WARNING: No extractable text in {path} (scanned PDF or empty).")
        return 0

    print(f"[Ingest] Embedding and upserting {len(texts)} chunks for {sym} ({filename})...")
    embeddings = embedding_engine.encode(texts)
    collection.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=embeddings)
    return len(texts)

def ingest_text_document(
    title: str,
    content: str,
    symbol: str,
    doc_type: str,
    fiscal_year: str,
    quarter: str = "Annual",
    basis: str = "consolidated",
    source: str = "filing.txt"
) -> int:
    """Ingest raw text filing/report directly into ChromaDB."""
    sym = resolve_ticker(symbol) or symbol.upper()
    chunks = chunk_text(content, size=1000, overlap=150)
    
    texts = []
    metas = []
    ids = []
    
    for j, ch in enumerate(chunks):
        texts.append(ch)
        metas.append({
            "kind": "filing",
            "symbol": sym,
            "doc_type": doc_type.lower(),
            "fiscal_year": fiscal_year.upper(),
            "quarter": quarter.upper(),
            "basis": basis.lower(),
            "page": 1,
            "source": source,
            "url": ""
        })
        ids.append(f"{sym}_{source}_c{j}")

    embeddings = embedding_engine.encode(texts)
    collection.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=embeddings)
    return len(texts)
