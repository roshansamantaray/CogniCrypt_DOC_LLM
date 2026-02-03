import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
from pypdf import PdfReader
import faiss
from openai import OpenAI

@dataclass
class DocChunk:
    # Stable ID for RAG references (e.g., "C12")
    id: str
    # Text content of the chunk
    text: str

class EmbeddingIndex:
    def __init__(self):
        # Parallel arrays of IDs and FAISS vectors
        self.ids: List[str] = []
        self.index = None
        self.vectors = None  # np.ndarray float32

    def build(self, embeddings: np.ndarray, ids: List[str]):
        """Build a cosine-similarity FAISS index from embeddings and IDs."""
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype("float32")
        # Normalize for cosine similarity using inner product index
        faiss.normalize_L2(embeddings)
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings)
        self.vectors = embeddings
        self.ids = ids

    def search(self, vec: np.ndarray, k: int) -> List[Tuple[str, float]]:
        """Return top-k (id, score) pairs for a query embedding."""
        q = vec.astype("float32")
        faiss.normalize_L2(q)
        D, I = self.index.search(q.reshape(1, -1), k)
        return [(self.ids[i], float(D[0][j])) for j, i in enumerate(I[0]) if i != -1]

# Extract text from all pages of a PDF (best effort).
def _extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n".join(pages)

# Chunk text by paragraph with overlap to preserve context.
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
    # Add overlap from previous chunk to improve retrieval continuity.
    for c in chunks:
        if not merged:
            merged.append(c)
        else:
            tail = merged[-1][-overlap:]
            merged.append((tail + "\n" + c)[:max_chars])
    return merged

# Embed text with OpenAI embeddings and return a float32 matrix.
def _embed_texts(client: OpenAI, texts: List[str], model="text-embedding-3-small") -> np.ndarray:
    vectors = []
    for t in texts:
        emb = client.embeddings.create(model=model, input=t).data[0].embedding
        vectors.append(emb)
    return np.asarray(vectors, dtype="float32")

# Build (or load) a cached FAISS index over the CrySL paper PDF.
def build_pdf_index(pdf_path: str, cache_dir="rag_cache", emb_model="text-embedding-3-small"):
    os.makedirs(cache_dir, exist_ok=True)
    vec_p = Path(cache_dir) / "vectors.npy"
    ids_p = Path(cache_dir) / "ids.json"
    chunks_p = Path(cache_dir) / "chunks.json"
    # Reuse cached index if present.
    if vec_p.exists() and ids_p.exists() and chunks_p.exists():
        vectors = np.load(vec_p)
        ids = json.loads(ids_p.read_text(encoding="utf-8"))
        raw_chunks = json.loads(chunks_p.read_text(encoding="utf-8"))
        chunks = [DocChunk(**c) for c in raw_chunks]
        idx = EmbeddingIndex()
        idx.build(vectors, ids)
        return idx, chunks
    # Otherwise read PDF, chunk it, embed, and cache results.
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    raw_text = _extract_pdf_text(pdf_path)
    raw_chunks = _chunk_text(raw_text)
    chunks = [DocChunk(id=f"C{i}", text=t) for i, t in enumerate(raw_chunks)]
    embeddings = _embed_texts(client, [c.text for c in chunks], emb_model)
    idx = EmbeddingIndex()
    idx.build(embeddings, [c.id for c in chunks])
    np.save(vec_p, embeddings)
    ids_p.write_text(json.dumps([c.id for c in chunks]), encoding="utf-8")
    chunks_p.write_text(json.dumps([c.__dict__ for c in chunks]), encoding="utf-8")
    return idx, chunks