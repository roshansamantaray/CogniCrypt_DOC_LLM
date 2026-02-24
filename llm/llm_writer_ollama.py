#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# Use the Ollama-based index module
from paper_index_ollama import build_pdf_index, get_ollama_client
from utils.writer_core import (
    WriterCLIConfig,
    build_explanation_prompt,
    build_system_messages,
    process_rule_core,
    run_writer_main,
)

try:
    # ensure Python stdout uses UTF-8 (Python 3.7+)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    # fallback: rely on caller to set PYTHONIOENCODING
    pass


# Resolve project root and important folders
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "src" / "main" / "resources" / "CrySLRules"
PDF_PATH = PROJECT_ROOT / "tse19CrySL.pdf"


# Embed text using Ollama embeddings and return a float32 matrix.
def _embed_texts(client, texts: List[str], model: str = "mistral:v0.3") -> np.ndarray:
    """
    Return float32 embeddings for input texts using Ollama.

    The method accepts multiple response shapes to stay compatible with proxy and
    deployment variants that serialize embeddings differently.
    """
    vectors = []

    for t in texts:
        resp = client.embeddings.create(model=model, prompt=t)

        if isinstance(resp, dict) and "data" in resp and resp["data"]:
            vectors.append(resp["data"][0]["embedding"])
        elif isinstance(resp, dict) and "embedding" in resp:
            vectors.append(resp["embedding"])
        elif isinstance(resp, list):
            if resp and isinstance(resp[0], dict) and "embedding" in resp[0]:
                vectors.append(resp[0]["embedding"])
            else:
                vectors.append(resp)
        else:
            raise RuntimeError("Unexpected embeddings response: %r" % (resp,))

    return np.asarray(vectors, dtype="float32")


# Generate text with Ollama and normalize common response shapes.
def _generate_text(client, model: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> str:
    """
    Generate text through the Ollama client and normalize common payload formats.
    """
    resp = client.generate.create(model=model, prompt=prompt, max_tokens=max_tokens, temperature=temperature)
    # common shapes
    if isinstance(resp, dict):
        if "text" in resp and isinstance(resp["text"], str):
            return resp["text"].strip()
        if "result" in resp and isinstance(resp["result"], str):
            return resp["result"].strip()
        if "output" in resp and isinstance(resp["output"], str):
            return resp["output"].strip()
        if "choices" in resp and isinstance(resp["choices"], list) and resp["choices"]:
            c0 = resp["choices"][0]
            if isinstance(c0, dict):
                if "message" in c0 and isinstance(c0["message"], dict):
                    return c0["message"].get("content", "").strip()
                if "text" in c0:
                    return c0.get("text", "").strip()
    # fallback: stringify
    return str(resp)


# Build RAG context using the CrySL paper index and this rule's sections.
def make_rag_context(
    client,
    idx,  # from paper_index_ollama.build_pdf_index
    chunks,  # list of DocChunk (must have .text)
    emb_model: str,
    rule_sections_txt: Dict[str, str],
    k: int = 6,
    per_chunk_max: int = 900,
) -> str:
    """
    Build a retrieval context block from top-k CrySL-paper chunks.

    Inputs:
    - client: Ollama client used for query embedding.
    - idx/chunks: index/chunk pair from paper_index_ollama.
    - rule_sections_txt: normalized CrySL sections for this rule.
    Returns:
    - rag_block: chunk-id-tagged snippets used as hidden reference context.
    """
    syntax_boost = """
    CRYSL language syntax and semantics:
    - Sections: SPEC, OBJECTS, EVENTS, ORDER, CONSTRAINTS, REQUIRES, ENSURES, FORBIDDEN
    - Typestate / usage protocols: ORDER as a regex over EVENTS; use of aggregates
    - Predicates: REQUIRES / ENSURES; NEGATES; 'after' placement for predicate generation
    - Helper functions: alg(), mode(), padding(), length(), neverTypeOf(), callTo(), noCallTo()
    - Examples to retrieve: KeyGenerator (Fig. 2), Cipher (Fig. 3), PBEKeySpec (Fig. 4)
    - EBNF grammar and formal semantics
    """.strip()

    query_parts = [syntax_boost]
    for s in ("SPEC", "OBJECTS", "EVENTS", "ORDER", "CONSTRAINTS", "REQUIRES", "ENSURES", "FORBIDDEN"):
        v = rule_sections_txt.get(s)
        if v:
            query_parts.append(f"{s}:\n{v}")
    query = "\n\n".join(query_parts)

    if not idx or not hasattr(idx, "index") or idx.index is None or not chunks:
        return ""

    q_vec = _embed_texts(client, [query], model=emb_model)[0]
    # Use the shared EmbeddingIndex wrapper, which normalizes vector shapes and
    # returns (chunk_id, score) pairs.
    hits = idx.search(q_vec, k)
    # Build an O(1) ID lookup so hit mapping stays cheap even for larger chunk sets.
    chunk_by_id = {getattr(c, "id", None): c for c in chunks}
    rag_items = []
    for hid, score in hits:
        matching = chunk_by_id.get(hid)
        if not matching:
            continue
        text = getattr(matching, "text", "")
        if per_chunk_max and len(text) > per_chunk_max:
            text = text[:per_chunk_max] + " ..."
        rag_items.append(f"[{matching.id}] {text}\n")
    rag_block = "\n\n".join(rag_items)
    return rag_block


# Build the LLM prompt and request a structured explanation.
def generate_explanation(
    client,
    model: str,
    class_name: str,
    objects: str,
    events: str,
    order: str,
    constraints: str,
    requires: str,
    ensures: str,
    forbidden: str,
    dep_constraints_text: str,
    dep_ensures_text: str,
    sanitized_summary: str,
    raw_crysl_text: str,
    explanation_language: str,
    rag_block: str = "",
) -> str:
    """Generate a full natural-language rule explanation through Ollama."""
    # Build the strict user prompt from CrySL sections and dependency summaries.
    prompt = build_explanation_prompt(
        class_name=class_name,
        objects=objects,
        events=events,
        order=order,
        constraints=constraints,
        requires=requires,
        ensures=ensures,
        forbidden=forbidden,
        dep_constraints_text=dep_constraints_text,
        dep_ensures_text=dep_ensures_text,
        sanitized_summary=sanitized_summary,
        raw_crysl_text=raw_crysl_text,
        explanation_language=explanation_language,
        include_utf8_line=True,
    )

    # Compose base system guidance plus optional hidden RAG reference material.
    sys_msgs = build_system_messages(rag_block)

    # call Ollama-style generate wrapper
    return _generate_text(
        client,
        model,
        "\n\n".join([m["content"] for m in sys_msgs]) + "\n\n" + prompt,
        max_tokens=1600,
        temperature=0.2,
    )


# Orchestrate a single rule's explanation generation pipeline.
def process_rule(
    crysl_path: str,
    language: str,
    client,
    model: str,
    target_fqcn: str,
    idx=None,
    chunks=None,
    k: int = 6,
    emb_model: str = "mistral:v0.3",
):
    """Run the shared single-rule pipeline with Ollama-specific callbacks."""
    return process_rule_core(
        crysl_path=crysl_path,
        language=language,
        client=client,
        model=model,
        target_fqcn=target_fqcn,
        make_rag_context_fn=make_rag_context,
        generate_explanation_fn=generate_explanation,
        idx=idx,
        chunks=chunks,
        k=k,
        emb_model=emb_model,
    )


# CLI entrypoint: parse args, init Ollama client, optional RAG index, and run.
def main():
    """CLI entrypoint for Ollama-backed explanation generation."""
    # Provider defaults are passed to shared CLI/runtime orchestration. Environment
    # overrides are resolved in run_writer_main via model_env_var settings.
    cli_config = WriterCLIConfig(
        description="Generate CrySL rule explanations via Ollama LLM (with dependency ENSURES + constraints, optional RAG)",
        model_default="llama3.1:70b",
        model_help="Ollama model to use for completions (e.g., 'llama3.1:70b' or 'mistral:v0.3')",
        pdf_default=str(PDF_PATH),
        emb_model_default="mistral:v0.3",
        emb_model_help="Embedding model for RAG queries (Ollama model name)",
        model_env_var="OLLAMA_MODEL",
        emb_model_env_var="OLLAMA_EMB_MODEL",
    )

    # Delegate argument parsing, CrySL resolution, optional RAG indexing, and processing.
    run_writer_main(
        rules_dir=RULES_DIR,
        cli_config=cli_config,
        init_client_fn=get_ollama_client,
        build_pdf_index_fn=build_pdf_index,
        process_rule_fn=process_rule,
    )


# Standard entry guard for CLI usage.
if __name__ == "__main__":
    main()
