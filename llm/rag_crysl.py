import os
import re
from typing import List, Dict
import numpy as np
from openai import OpenAI
from .paper_index import build_pdf_index, DocChunk, EmbeddingIndex

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")
_NUM_RE = re.compile(r"\b\d+\b")

def extract_rule_tokens(rule: Dict) -> List[str]:
    parts = []
    for key in ["SPEC","OBJECTS","EVENTS","CONSTRAINTS","REQUIRES","ENSURES","FORBIDDEN","NEGATES"]:
        parts.append(rule.get(key, ""))
    toks = []
    for seg in parts:
        if not seg:
            continue
        toks.extend(_TOKEN_RE.findall(seg))
        if seg is rule.get("CONSTRAINTS"):
            toks.extend(_NUM_RE.findall(seg))
    uniq, seen = [], set()
    for t in toks:
        low = t.lower()
        if len(t) < 3 or low in seen:
            continue
        seen.add(low)
        uniq.append(t)
    return uniq

def build_query(rule: Dict) -> str:
    return " | ".join(extract_rule_tokens(rule))

def _embed_texts(client: OpenAI, texts: List[str], model="text-embedding-3-small") -> np.ndarray:
    vectors = []
    for t in texts:
        emb = client.embeddings.create(model=model, input=t).data[0].embedding
        vectors.append(emb)
    return np.asarray(vectors, dtype="float32")

def retrieve_chunks(rule: Dict, idx: EmbeddingIndex, chunks: List[DocChunk], k=6, emb_model="text-embedding-3-small"):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    q = build_query(rule)
    q_vec = _embed_texts(client, [q], emb_model)[0]
    hits = idx.search(q_vec, k=k)
    id_map = {c.id: c for c in chunks}
    return [id_map[h[0]] for h in hits]

def build_prompt(rule: Dict, retrieved: List[DocChunk], language: str) -> str:
    if not retrieved:
        evidence = "No external language-semantics snippets retrieved."
    else:
        evidence = "\n".join(f"[{c.id}] {c.text[:420].replace(chr(10),' ')}" for c in retrieved)
    return f"""
You are a CrySL explanation assistant.

Rule:
SPEC: {rule.get('SPEC','')}
OBJECTS:
{rule.get('OBJECTS','')}
EVENTS:
{rule.get('EVENTS','')}
ORDER:
{rule.get('ORDER','N/A')}
CONSTRAINTS:
{rule.get('CONSTRAINTS','N/A')}
REQUIRES:
{rule.get('REQUIRES','N/A')}
ENSURES:
{rule.get('ENSURES','N/A')}
FORBIDDEN:
{rule.get('FORBIDDEN','N/A')}
NEGATES:
{rule.get('NEGATES','N/A')}

Evidence (language semantics):
{evidence}

Instructions:
1. Cite snippet ids \\[Cx] only for generic language semantics.
2. Concrete rule details must come solely from the rule sections.
3. If a detail is missing in both rule and evidence, mark it as unspecified.
4. Sections: Overview; Correct Usage; Parameters & Constraints; Predicates; Forbidden Patterns; Security Rationale.
5. No invented APIs or parameters.

Respond in {language}.
""".strip()

def generate_explanation(prompt: str, model="gpt-4o-mini") -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role":"system","content":"You produce accurate, grounded, citation-disciplined CrySL explanations."},
            {"role":"user","content":prompt}
        ],
        temperature=0.0,
        max_tokens=1400
    )
    return resp.choices[0].message.content.strip()