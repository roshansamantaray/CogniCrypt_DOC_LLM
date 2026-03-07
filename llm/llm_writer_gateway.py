#!/usr/bin/env python3
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
from openai import OpenAI

from paper_index_gateway import build_pdf_index, get_gateway_client
from utils.writer_core import (
    WriterCLIConfig,
    build_explanation_prompt,
    build_system_messages,
    process_rule_core,
    run_writer_main,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "src" / "main" / "resources" / "CrySLRules"
PDF_PATH = PROJECT_ROOT / "tse19CrySL.pdf"


def _embed_texts(client: OpenAI, texts: List[str], model: str = "YOUR_EMBEDDING_MODEL") -> np.ndarray:
    """Return float32 embeddings for a list of strings using a gateway embedding model."""
    resp = client.embeddings.create(model=model, input=texts)
    return np.asarray([d.embedding for d in resp.data], dtype="float32")


def make_rag_context(
    client: OpenAI,
    idx,
    chunks,
    emb_model: str,
    rule_sections_txt: Dict[str, str],
    k: int = 6,
    per_chunk_max: int = 900,
) -> str:
    """Build a retrieval context block from top-k CrySL-paper chunks."""
    syntax_boost = """
    CRYSL language syntax and semantics:
    - Sections: SPEC, OBJECTS, EVENTS, ORDER, CONSTRAINTS, REQUIRES, ENSURES, FORBIDDEN
    - Typestate / usage protocols: ORDER as a regex over EVENTS; use of aggregates
    - Predicates: REQUIRES / ENSURES; NEGATES; 'after' placement for predicate generation
    - Helper functions: alg(), mode(), padding(), length(), neverTypeOf(), callTo(), noCallTo()
    - Examples to retrieve: KeyGenerator (Fig. 2), Cipher (Fig. 3), PBEKeySpec (Fig. 4)
    - EBNF grammar and formal semantics
    """.strip()

    query_text = "\n".join(
        [
            syntax_boost,
            "THIS RULE:",
            "SPEC: " + (rule_sections_txt.get("SPEC") or ""),
            "OBJECTS: " + (rule_sections_txt.get("OBJECTS") or ""),
            "EVENTS: " + (rule_sections_txt.get("EVENTS") or ""),
            "ORDER: " + (rule_sections_txt.get("ORDER") or ""),
            "CONSTRAINTS: " + (rule_sections_txt.get("CONSTRAINTS") or ""),
            "REQUIRES: " + (rule_sections_txt.get("REQUIRES") or ""),
            "ENSURES: " + (rule_sections_txt.get("ENSURES") or ""),
        ]
    ).strip()

    if not hasattr(idx, "index") or idx.index is None or not chunks:
        return ""

    qvec = _embed_texts(client, [query_text], model=emb_model)[0]
    hits = idx.search(qvec, k)

    def _normalize_pdf_text(s: str) -> str:
        return s.replace("\ufb01", "fi").replace("\ufb02", "fl").replace("\u00ad", "").strip()

    chunk_by_id = {getattr(c, "id", None): c for c in chunks}
    rag_snippets: List[str] = []

    for rank, (hid, _score) in enumerate(hits, start=1):
        c = chunk_by_id.get(hid)
        if not c:
            continue
        tag = f"[C{rank}]"
        text = _normalize_pdf_text(getattr(c, "text", ""))
        if per_chunk_max and len(text) > per_chunk_max:
            text = text[:per_chunk_max].rsplit(" ", 1)[0] + " ..."
        rag_snippets.append(f"{tag} {text}")

    return "\n\n".join(rag_snippets) if rag_snippets else ""


def generate_explanation(
    client: OpenAI,
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
    """Generate a full natural-language rule explanation via gateway chat completion."""
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

    sys_msgs = build_system_messages(rag_block)
    resp = client.chat.completions.create(
        model=model,
        messages=sys_msgs + [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
    )
    return resp.choices[0].message.content


def process_rule(
    crysl_path: str,
    language: str,
    client: OpenAI,
    model: str,
    target_fqcn: str,
    idx=None,
    chunks=None,
    k: int = 6,
    emb_model: str = "YOUR_EMBEDDING_MODEL",
):
    """Run the shared single-rule pipeline with gateway-specific callbacks."""
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


def main():
    """CLI entrypoint for gateway-backed explanation generation."""
    cli_config = WriterCLIConfig(
        description="Generate CrySL rule explanations via UPB AI-Gateway",
        model_default="gwdg.llama-3.3-70b-instruct",
        model_help="Gateway model to use for completions",
        pdf_default=PDF_PATH,
        emb_model_default="YOUR_EMBEDDING_MODEL",
        emb_model_help="Gateway embedding model for RAG queries",
        model_env_var="GATEWAY_CHAT_MODEL",
        emb_model_env_var="GATEWAY_EMB_MODEL",
    )

    run_writer_main(
        rules_dir=RULES_DIR,
        cli_config=cli_config,
        init_client_fn=get_gateway_client,
        build_pdf_index_fn=build_pdf_index,
        process_rule_fn=process_rule,
    )


if __name__ == "__main__":
    main()
