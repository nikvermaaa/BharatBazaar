import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
private_env = Path.home() / ".config" / "stock_exchange" / ".env"
if private_env.exists():
    load_dotenv(private_env, override=True)
load_dotenv(BASE_DIR / ".env")

HF_TOKEN = os.getenv("HF_TOKEN", "")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
if GEMINI_MODEL == "gemini-flash-latest":
    GEMINI_MODEL = "gemini-2.5-flash"

EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").lower()
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

MAX_STEPS = int(os.getenv("MAX_AGENT_STEPS", "6"))
TOP_K = int(os.getenv("TOP_K", "6"))

data_dir_env = os.getenv("DATA_DIR", "./data")
DATA_DIR = str(Path(data_dir_env) if os.path.isabs(data_dir_env) else (BASE_DIR / data_dir_env).resolve())

chroma_dir_env = os.getenv("CHROMA_DIR", "./chroma_db")
CHROMA_DIR = str(Path(chroma_dir_env) if os.path.isabs(chroma_dir_env) else (BASE_DIR / chroma_dir_env).resolve())

NEWS_DIR = str(Path(DATA_DIR) / "news")
PRICES_DIR = str(Path(DATA_DIR) / "prices")
FILINGS_DIR = str(Path(DATA_DIR) / "filings")

# Ensure required runtime directories exist
for directory in [DATA_DIR, CHROMA_DIR, NEWS_DIR, PRICES_DIR, FILINGS_DIR]:
    os.makedirs(directory, exist_ok=True)
