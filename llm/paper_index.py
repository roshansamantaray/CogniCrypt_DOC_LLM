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

def _embed_texts(client: OpenAI, texts: List[str], model="text-embedding-3-small") -> np.ndarray:
    vectors = []
    for t in texts:
        emb = client.embeddings.create(model=model, input=t).data[0].embedding
        vectors.append(emb)
    return np.asarray(vectors, dtype="float32")

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