import os
import requests
from typing import List
from app.config import EMBEDDING_PROVIDER, EMBED_MODEL, GEMINI_API_KEY

_local_model = None

class EmbeddingEngine:
    def __init__(self):
        self.provider = EMBEDDING_PROVIDER.lower()
        self.model_name = EMBED_MODEL
        self.gemini_key = GEMINI_API_KEY
        self.hf_token = os.getenv("HF_TOKEN", "")

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        # 1. Google Gemini Embeddings (only if explicitly configured as gemini)
        if self.provider == "gemini" and self.gemini_key and self.gemini_key != "your_gemini_api_key_here":
            try:
                from google import genai
                client = genai.Client(api_key=self.gemini_key)
                response = client.models.embed_content(
                    model="models/gemini-embedding-001",
                    contents=texts
                )
                return [emb.values for emb in response.embeddings]
            except Exception as e:
                print(f"[Embeddings] Gemini cloud embed failed: {e}. Falling back to local.")

        # 2. Hugging Face Inference API (Cloud API with fast timeout)
        if self.provider == "huggingface" and self.hf_token:
            try:
                headers = {"Authorization": f"Bearer {self.hf_token}"}
                api_url = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{self.model_name}"
                res = requests.post(api_url, headers=headers, json={"inputs": texts, "options": {"wait_for_model": False}}, timeout=2.0)
                if res.status_code == 200:
                    return res.json()
            except Exception:
                pass

        # 3. ChromaDB ONNX Default Embedding (Fast, lightweight, no PyTorch needed)
        global _local_model
        if _local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                _local_model = SentenceTransformer(self.model_name)
            except Exception:
                from chromadb.utils import embedding_functions
                _local_model = embedding_functions.DefaultEmbeddingFunction()

        if hasattr(_local_model, "encode"):
            emb = _local_model.encode(texts, normalize_embeddings=True)
            return emb.tolist()
        else:
            return _local_model(texts)

embedding_engine = EmbeddingEngine()
