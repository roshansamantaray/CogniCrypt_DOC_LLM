import os
from typing import List
import time
import types

import numpy as np
import requests
from requests.exceptions import RequestException
from utils.rag_index_common import (
    DocChunk,
    EmbeddingIndex,
    _chunk_text,
    _extract_pdf_text,
    get_cache_paths,
    load_cached_index,
    save_cached_index,
)

# --- Ollama client wrapper (lightweight) ---
class OllamaClient:
    """Minimal transport client for Ollama-compatible `/ollama/api/*` endpoints."""

    def __init__(self, base_url: str = None, timeout: int = 30):
        """Initialize transport settings from explicit args or OLLAMA_URL defaults."""
        # default Ollama local server URL; can be overridden with OLLAMA_URL env var
        self.base_url = base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")
        # Keep timeout as the numeric value provided (do not rstrip)
        self.timeout = timeout

    def _post(self, path: str, json_payload):
        """
        POST JSON to an Ollama endpoint with retry/backoff and JSON-response enforcement.

        Raises RequestException/RuntimeError on persistent transport or decoding failures.
        """
        # base_url from OLLAMA_URL, endpoint path is expected like "/api/chat"
        url = self.base_url.rstrip("/") + "/ollama" + path

        # small retry logic for transient failures
        retries = 2
        backoff = 0.5
        last_exc = None

        # add Authorization header for remote Ollama
        headers = {}
        api_key = os.getenv("OLLAMA_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for attempt in range(retries + 1):
            try:
                resp = requests.post(url, json=json_payload, headers=headers, timeout=self.timeout)
                resp.raise_for_status()
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
        raise last_exc

    # nested helper classes kept for compatibility but not used for binding
    class embeddings:
        """Compatibility namespace; concrete callables are bound at runtime."""

        @staticmethod
        def create(model: str, input):
            """Placeholder signature used before runtime binding."""
            # wrapper to be replaced at runtime by bound method
            raise NotImplementedError()

    class generate:
        """Compatibility namespace; concrete callables are bound at runtime."""

        @staticmethod
        def create(model: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2):
            """Placeholder signature used before runtime binding."""
            raise NotImplementedError()

# Create a lightweight Ollama client instance with embeddings/chat bindings.
def _make_ollama_client():
    """Create an Ollama client with bound embeddings and chat/generate helpers."""
    client = OllamaClient()
    # bind functional implementations that use the instance base_url
    def embeddings_create(model: str, prompt: str):
        """Call the Ollama embeddings endpoint with model/prompt payload."""
        # /ollama/api/embeddings expects: {"model": "...", "prompt": "<string>"}
        payload = {"model": model, "prompt": prompt}
        return client._post("/api/embeddings", payload)

    def generate_create(model: str, prompt: str, max_tokens: int = 512, temperature: float = 0.2):
        """Call the Ollama chat endpoint using a single user-message prompt payload."""
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        return client._post("/api/chat", payload)

    # Attach per-instance helper namespaces so call sites can use
    # `client.embeddings.create(...)` and `client.generate.create(...)`.
    client.embeddings = types.SimpleNamespace(create=embeddings_create)
    client.generate = types.SimpleNamespace(create=generate_create)
    return client

# Embed a list of texts by calling Ollama's embeddings endpoint.
def _embed_texts(client: OllamaClient, texts: List[str], model="mistral:v0.3") -> np.ndarray:
    """
    Return float32 embeddings for input texts via Ollama.

    Handles multiple embedding response shapes to support different gateway/proxy
    deployments that may serialize payloads differently.
    """
    if not texts:
        return np.empty((0, 0), dtype="float32")

    vectors = []

    for t in texts:
        resp = client.embeddings.create(model=model, prompt=t)

        if isinstance(resp, dict):
            if "data" in resp and resp["data"]:
                # OpenAI-style: {"data":[{"embedding":[...]}]}
                vectors.append(resp["data"][0]["embedding"])
            elif "embedding" in resp:
                # Direct: {"embedding":[...]}
                vectors.append(resp["embedding"])
            else:
                raise RuntimeError(f"Unexpected embeddings response from Ollama: {resp!r}")
        elif isinstance(resp, list):
            # Could be [floats...] or [{"embedding":[...]}]
            if resp and isinstance(resp[0], dict) and "embedding" in resp[0]:
                vectors.append(resp[0]["embedding"])
            else:
                vectors.append(resp)
        else:
            raise RuntimeError(f"Unexpected embeddings response from Ollama: {resp!r}")

    return np.asarray(vectors, dtype="float32")

# Build (or load) a cached FAISS index over the CrySL paper PDF using Ollama embeddings.
def build_pdf_index(pdf_path: str, cache_dir="rag_cache", emb_model="mistral:v0.3"):
    """
    Load or build the Ollama-backed PDF embedding index.

    Cache keys are provider/model/pdf specific via get_cache_paths(), so this index
    does not collide with OpenAI artifacts even under a shared cache root.
    Returns:
    - (EmbeddingIndex, List[DocChunk])
    """
    # Resolve provider/model/pdf-specific cache artifact paths.
    vec_p, ids_p, chunks_p = get_cache_paths(
        cache_dir=cache_dir,
        pdf_path=pdf_path,
        provider="ollama",
        emb_model=emb_model,
    )
    # Reuse cached vectors/chunks when cache artifacts pass integrity validation.
    cached = load_cached_index(vec_p, ids_p, chunks_p)
    if cached is not None:
        return cached

    # Cache miss: extract text and create paragraph-overlap chunks from the PDF.
    raw_text = _extract_pdf_text(pdf_path)
    raw_chunks = _chunk_text(raw_text)
    chunks = [DocChunk(id=f"C{i}", text=t) for i, t in enumerate(raw_chunks)]
    if not chunks:
        # Empty-text PDFs still produce a stable empty cache entry so repeated runs
        # do not repeatedly rebuild or fail.
        idx = EmbeddingIndex()
        empty_embeddings = np.empty((0, 0), dtype="float32")
        idx.build(empty_embeddings, [])
        save_cached_index(vec_p, ids_p, chunks_p, empty_embeddings, chunks)
        return idx, chunks
    # Build embeddings and FAISS index, then persist artifacts for later reuse.
    client = _make_ollama_client()
    # Batch embed all chunk texts through provider-specific embedding parsing.
    embeddings = _embed_texts(client, [c.text for c in chunks], emb_model)
    idx = EmbeddingIndex()
    idx.build(embeddings, [c.id for c in chunks])
    save_cached_index(vec_p, ids_p, chunks_p, embeddings, chunks)
    return idx, chunks

# Expose helper for other modules to obtain an Ollama client.
def get_ollama_client():
    """Return a ready-to-use Ollama client with embeddings/generate helpers."""
    return _make_ollama_client()
