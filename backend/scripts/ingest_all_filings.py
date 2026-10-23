import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.rag.ingest import ingest_pdf, ingest_text_document

def ingest_all():
    filings_dir = backend_dir / "data" / "filings"
    txt_files = list(filings_dir.glob("*/*.txt"))
    pdf_files = list(filings_dir.glob("*/*.pdf"))
    
    print(f"Found {len(txt_files)} text filing(s) and {len(pdf_files)} PDF filing(s).")
    
    for f in txt_files:
        symbol = f.parent.name
        print(f"Ingesting {symbol}: {f.name}...")
        with open(f, "r", encoding="utf-8") as fh:
            content = fh.read()
        chunks = ingest_text_document(
            title=f.stem,
            content=content,
            symbol=symbol,
            doc_type="results",
            fiscal_year="FY25",
            quarter="Q1",
            basis="consolidated",
            source=f.name
        )
        print(f"  -> Ingested {chunks} chunks for {symbol}")

    for f in pdf_files:
        symbol = f.parent.name
        print(f"Ingesting PDF {symbol}: {f.name}...")
        chunks = ingest_pdf(
            path=str(f),
            symbol=symbol,
            doc_type="results",
            fiscal_year="FY25",
            quarter="Q1",
            basis="consolidated"
        )
        print(f"  -> Ingested {chunks} chunks for {symbol}")

    print("All filings ingested successfully into ChromaDB!")

if __name__ == "__main__":
    ingest_all()
