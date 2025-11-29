import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple
import time
import types

import numpy as np
from pypdf import PdfReader
import faiss
import requests
from requests.exceptions import RequestException, HTTPError

@dataclass
class DocChunk:
    id: str
    text: str

class EmbeddingIndex:
    def __init__(self):
        self.ids: List[str] = []
        self.index = None
        self.vectors = None  # np.ndarray float32

    def build(self, embeddings: np.ndarray, ids: List[str]):
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype("float32")
        faiss.normalize_L2(embeddings)
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings)
        self.vectors = embeddings
        self.ids = ids

    def search(self, vec: np.ndarray, k: int) -> List[Tuple[str, float]]:
        q = vec.astype("float32")
        faiss.normalize_L2(q)
        D, I = self.index.search(q.reshape(1, -1), k)
        return [(self.ids[i], float(D[0][j])) for j, i in enumerate(I[0]) if i != -1]

def _extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)

def _chunk_text(text: str, max_chars=1800, overlap=300) -> List[str]:
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks, buf = [], ""
    for para in paragraphs:
        if len(buf) + len(para) + 1 <= max_chars:
            buf = (buf + "\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    merged = []
    for c in chunks:
        if not merged:
            merged.append(c)
        else:
            tail = merged[-1][-overlap:]
            merged.append((tail + "\n" + c)[:max_chars])
    return merged

# --- Ollama client wrapper (lightweight) ---
class OllamaClient:
    def __init__(self, base_url: str = None, timeout: int = 30):
        # default Ollama local server URL; can be overridden with OLLAMA_URL env var
        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        # Keep timeout as the numeric value provided (do not rstrip)
        self.timeout = timeout

    def _post(self, path: str, json_payload):
        url = self.base_url.rstrip("/") + path
        # small retry logic for transient failures
        retries = 2
        backoff = 0.5
        last_exc = None
        for attempt in range(retries + 1):
            try:
                resp = requests.post(url, json=json_payload, timeout=self.timeout)
                resp.raise_for_status()
                # attempt to decode JSON, raise clear error if invalid
                try:
                    return resp.json()
                except ValueError as e:
                    raise RuntimeError(f"Non-JSON response from Ollama at {url}: {e}")
            except RequestException as e:
                last_exc = e
                if attempt < retries:
                    time.sleep(backoff * (1 + attempt))
                    continue
                raise
        # if we somehow exit loop without returning, raise last exception
        raise last_exc

    # nested helper classes kept for compatibility but not used for binding
    class embeddings:
        @staticmethod
        def create(model: str, input):
            # wrapper to be replaced at runtime by bound method
            raise NotImplementedError()

    class generate:
        @staticmethod
        def create(model: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2):
            raise NotImplementedError()

def _make_ollama_client():
    client = OllamaClient()
    # bind functional implementations that use the instance base_url
    def embeddings_create(model: str, input):
        # Ollama embeddings API expects { "model": "...", "input": [...] }
        payload = {"model": model, "input": input}
        return client._post("/api/embeddings", payload)

    def generate_create(model: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2):
        # simple generate wrapper. Ollama generate endpoint typically accepts {"model":..., "prompt":...}
        payload = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": temperature}
        try:
            return client._post("/api/generate", payload)
        except RequestException:
            # fallback to a completion-like endpoint if needed
            return client._post("/api/completions", payload)

    # attach small namespaces to the client instance (won't mutate nested classes)
    client.embeddings = types.SimpleNamespace(create=embeddings_create)
    client.generate = types.SimpleNamespace(create=generate_create)
    return client

def _embed_texts(client: OllamaClient, texts: List[str], model="text-embedding-3-small") -> np.ndarray:
    # batch embeddings in a single request
    resp = client.embeddings.create(model=model, input=texts)
    # expected shape: {"data":[{"embedding":[...]}...]}
    data = resp.get("data") if isinstance(resp, dict) else None
    if not data:
        # attempt to handle direct list response
        if isinstance(resp, list):
            arr = [item.get("embedding") if isinstance(item, dict) else item for item in resp]
            return np.asarray(arr, dtype="float32")
        raise RuntimeError("Unexpected embeddings response from Ollama: %r" % (resp,))
    return np.asarray([d["embedding"] for d in data], dtype="float32")

def build_pdf_index(pdf_path: str, cache_dir="rag_cache", emb_model="text-embedding-3-small"):
    os.makedirs(cache_dir, exist_ok=True)
    vec_p = Path(cache_dir) / "vectors.npy"
    ids_p = Path(cache_dir) / "ids.json"
    chunks_p = Path(cache_dir) / "chunks.json"
    if vec_p.exists() and ids_p.exists() and chunks_p.exists():
        vectors = np.load(vec_p)
        ids = json.loads(ids_p.read_text(encoding="utf-8"))
        raw_chunks = json.loads(chunks_p.read_text(encoding="utf-8"))
        chunks = [DocChunk(**c) for c in raw_chunks]
        idx = EmbeddingIndex()
        idx.build(vectors, ids)
        return idx, chunks

    client = _make_ollama_client()
    raw_text = _extract_pdf_text(pdf_path)
    raw_chunks = _chunk_text(raw_text)
    chunks = [DocChunk(id=f"C{i}", text=t) for i, t in enumerate(raw_chunks)]
    # batch embed all chunk texts
    embeddings = _embed_texts(client, [c.text for c in chunks], emb_model)
    idx = EmbeddingIndex()
    idx.build(embeddings, [c.id for c in chunks])
    np.save(vec_p, embeddings)
    ids_p.write_text(json.dumps([c.id for c in chunks]), encoding="utf-8")
    chunks_p.write_text(json.dumps([c.__dict__ for c in chunks]), encoding="utf-8")
    return idx, chunks

# expose helper for other modules
def get_ollama_client():
    return _make_ollama_client()