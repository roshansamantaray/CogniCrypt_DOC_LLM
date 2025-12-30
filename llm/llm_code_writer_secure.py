import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

from paper_index import build_pdf_index

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "src" / "main" / "resources" / "CrySLRules"
SANITIZED_DIR = PROJECT_ROOT / "llm" / "sanitized_rules"
CACHE_DIR = PROJECT_ROOT / "Output" / "resources" / "llm_cache"
PDF_PATH = PROJECT_ROOT / "tse19CrySL.pdf"
FILENAME_TEMPLATE = "sanitized_rule_{fqcn}_{lang}.json"
SANITIZED_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


_SANITIZED_CACHE: Dict[Tuple[str, str], Optional[Dict]] = {}


def safe_class_name(fqcn: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.\-]", "_", fqcn)


def rule_path(fqcn: str, lang: str) -> Path:
    return SANITIZED_DIR / FILENAME_TEMPLATE.format(fqcn=fqcn, lang=lang)


def load_json_quiet(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        print(f"[WARN] Could not read {path}: {exc}", file=sys.stderr)
        return None


def load_sanitized_rule(fqcn: str, languages: List[str]) -> Optional[Dict]:
    for lang in languages:
        key = (fqcn, lang)
        if key in _SANITIZED_CACHE:
            data = _SANITIZED_CACHE[key]
            if data is not None:
                return data
            continue
        data = load_json_quiet(rule_path(fqcn, lang))
        _SANITIZED_CACHE[key] = data
        if data is not None:
            return data
    return None


def crysl_to_json_lines(crysl_text: str) -> Dict[str, List[str]]:
    sections = ["SPEC", "OBJECTS", "EVENTS", "ORDER", "CONSTRAINTS", "REQUIRES", "ENSURES", "FORBIDDEN"]

    # Match headers at start of line, allow optional ":" and trailing whitespace
    pattern = re.compile(r"(?m)^(%s)\b\s*:?\s*" % "|".join(sections))

    matches = list(pattern.finditer(crysl_text))
    parsed: Dict[str, List[str]] = {}

    for idx, match in enumerate(matches):
        header = match.group(1)
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(crysl_text)

        chunk = crysl_text[start:end].strip()
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        parsed[header] = lines

    return parsed



def lines_to_text(section) -> str:
    if isinstance(section, list):
        return "\n".join(section) if section else "_no entries_"
    if section is None:
        return "_no entries_"
    return str(section)


def clean_item(value) -> str:
    if not isinstance(value, str):
        return str(value)
    cleaned = value.strip()
    return cleaned.lstrip(",").strip() if cleaned.startswith(",") else cleaned


def format_sanitized_rule_for_prompt(data: Optional[Dict]) -> str:
    if not data:
        return "No sanitized fields supplied."
    exclude = {"dependency"}
    parts: List[str] = []
    for key, val in data.items():
        if key in exclude or val in (None, ""):
            continue
        if isinstance(val, list):
            if not val:
                continue
            lines = "\n".join(f"- {clean_item(item)}" for item in val if str(item).strip())
            if lines:
                parts.append(f"{key}:\n{lines}")
        elif isinstance(val, dict):
            if not val:
                continue
            lines = "\n".join(f"- {ik}: {clean_item(iv)}" for ik, iv in val.items())
            parts.append(f"{key}:\n{lines}")
        else:
            parts.append(f"{key}: {clean_item(val)}")
    return "\n\n".join(parts) if parts else "No sanitized fields supplied."


def _normalize_listish(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_item(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        val = value.strip()
        return [val] if val else []
    return [clean_item(value)]


def collect_dependency_constraints(target_fqcn: str, languages: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
    dep_map: Dict[str, List[str]] = {}
    order: List[str] = []
    primary = load_sanitized_rule(target_fqcn, languages)
    if not primary:
        return order, dep_map
    deps = primary.get("dependency") or []
    seen = set()
    for dep in deps:
        if dep in seen or dep == target_fqcn:
            continue
        seen.add(dep)
        order.append(dep)
        data = load_sanitized_rule(dep, languages)
        if not data:
            dep_map[dep] = []
            continue
        constraints = data.get("constraints") or data.get("constraint") or []
        if not isinstance(constraints, list):
            constraints = [constraints]
        dep_map[dep] = [clean_item(c) for c in constraints if str(c).strip()]
    return order, dep_map


def format_dependency_constraints(order: List[str], dep_map: Dict[str, List[str]]) -> str:
    if not order:
        return "No dependency constraints supplied."
    blocks: List[str] = []
    for dep in order:
        constraints = dep_map.get(dep, [])
        if not constraints:
            blocks.append(f"Dependency: {dep}\n  - (no constraints available)")
        else:
            joined = "\n".join(f"  - {entry}" for entry in constraints)
            blocks.append(f"Dependency: {dep}\n{joined}")
    return "\n\n".join(blocks)


def collect_dependency_ensures(target_fqcn: str, languages: List[str], depth: int = 1) -> Tuple[List[str], Dict[str, List[str]]]:
    dep_map: Dict[str, List[str]] = {}
    order: List[str] = []
    primary = load_sanitized_rule(target_fqcn, languages)
    if not primary:
        return order, dep_map
    roots = primary.get("dependency") or []
    seen = {target_fqcn}

    def visit(fqcn: str, current_depth: int):
        if fqcn in seen:
            return
        seen.add(fqcn)
        if fqcn not in order:
            order.append(fqcn)
        data = load_sanitized_rule(fqcn, languages)
        if not data:
            dep_map[fqcn] = []
            return
        dep_map[fqcn] = _normalize_listish(data.get("ensures"))
        if current_depth < depth:
            for nxt in _normalize_listish(data.get("dependency")):
                visit(nxt, current_depth + 1)

    for dep in roots:
        if isinstance(dep, str) and dep:
            visit(dep, 1)
    return order, dep_map


def format_dependency_ensures(primary_fqcn: str, order: List[str], dep_map: Dict[str, List[str]]) -> str:
    if not order:
        return f"No dependent component guarantees were available for {primary_fqcn}."
    lines = [
        f"### Guarantees from related components impacting {primary_fqcn}",
        "Summaries below explain what each provider ensures once used correctly. Tie these back to the secure example." ,
        "",
    ]
    for dep in order:
        ensures = dep_map.get(dep, [])
        if not ensures:
            lines.append(f"- **{dep}**: (no ensures available)")
            continue
        lines.append(f"- **{dep}**:")
        lines.extend(f"  - {entry}" for entry in ensures)
    return "\n".join(lines)


def _embed_texts(client: OpenAI, texts: List[str], model: str) -> np.ndarray:
    result = client.embeddings.create(model=model, input=texts)
    return np.asarray([row.embedding for row in result.data], dtype="float32")


def make_rag_context(client: OpenAI, idx, chunks, emb_model: str, sections: Dict[str, str], k: int = 6, per_chunk_max: int = 900) -> Tuple[str, str]:
    if not idx or not hasattr(idx, "index") or not chunks:
        return "", ""
    syntax_hint = """
    CRYSL semantics reminders:
    - SPEC, OBJECTS, EVENTS, ORDER govern valid call sequences.
    - Constraints express parameter domains, helper functions (alg(), mode(), length()).
    - Predicates (REQUIRES/ENSURES/NEGATES) encode dependency contracts between classes.
    - Forbidden calls highlight insecure API combinations.
    """.strip()
    query = "\n".join([
        syntax_hint,
        "CURRENT RULE:",
        *(f"{key}: {sections.get(key, '')}" for key in ["SPEC", "OBJECTS", "EVENTS", "ORDER", "CONSTRAINTS", "REQUIRES", "ENSURES"]),
    ])
    query_vec = _embed_texts(client, [query], model=emb_model)[0]
    distances, indices = idx.index.search(query_vec.reshape(1, -1), k)

    def normalize_chunk(text: str) -> str:
        return text.replace("\ufb01", "fi").replace("\ufb02", "fl").replace("\u00ad", "").strip()

    rag_chunks: List[str] = []
    tags: List[str] = []
    for rank, chunk_idx in enumerate(indices[0], start=1):
        if chunk_idx == -1:
            continue
        chunk = chunks[chunk_idx]
        tag = f"[C{rank}]"
        excerpt = normalize_chunk(getattr(chunk, "text", ""))
        if per_chunk_max and len(excerpt) > per_chunk_max:
            excerpt = excerpt[:per_chunk_max].rsplit(" ", 1)[0] + " ..."
        rag_chunks.append(f"{tag} {excerpt}")
        tags.append(tag)
    return "\n\n".join(rag_chunks), " ".join(tags)


def read_llm_cache(fqcn: str, language: str, cache_dir: Path) -> str:
    safe_name = safe_class_name(fqcn)
    path = cache_dir / f"{safe_name}_{language}.txt"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        print(f"[WARN] Could not read cache {path}: {exc}", file=sys.stderr)
        return ""


def build_secure_prompt(context: Dict[str, str]) -> str:
    explanation = context.get("cached_explanation") or "No narrative explanation cached."
    dep_ensures = context.get("dep_ensures_text") or "(no dependency guarantees)"
    dep_constraints = context.get("dep_constraints_text") or "(no dependency constraints)"
    return f"""
You are a senior Java cryptography engineer tasked with producing a single, self-contained, **secure** usage example for `{context['class_name']}`.

Available knowledge (reference only, do not quote verbatim):
- CrySL Summary:\n{context['crysl_summary']}
- Sanitized Constraints:\n{context['sanitized_summary']}
- Cached Explanation:\n{explanation}
- Dependency Guarantees:\n{dep_ensures}
- Dependency Constraints:\n{dep_constraints}
- Raw CrySL (excerpt):\n{context['raw_crysl_excerpt']}

Requirements:
1. Respect the EVENTS order `{context['order_txt']}` exactly as implied by the rule; translate it into real API calls.
2. Enforce every constraint (algorithms, key sizes, provider requirements) at runtime. Choose the strongest allowed option when multiples exist.
3. Reflect REQUIRES predicates as concrete preconditions (e.g., verify inputs, require keys from secure generators). Reflect ENSURES predicates as postconditions/comments.
4. NEVER invoke anything listed in FORBIDDEN. If other unsafe variants exist, mention why you avoided them via comments.
5. Include concise `//` comments explaining the security rationale behind key steps (entropy sources, parameter choices, etc.).
6. Produce real values (e.g., generate keys, seeds) rather than placeholders like `TODO` or `null`.
7. Output **Java code only**. Wrap it in ```java fences for readability, with no prose above or below the block.
""".strip()


def process_rule(json_path: Path, language: str, model: str, pdf_path: Optional[Path], k: int, emb_model: str, cache_dir: Path) -> Optional[str]:
    try:
        with json_path.open(encoding="utf-8") as handle:
            rule_payload = json.load(handle)
    except Exception as exc:
        print(f"Failed to read rule JSON {json_path}: {exc}", file=sys.stderr)
        return None

    if "className" not in rule_payload:
        print("rule JSON missing className", file=sys.stderr)
        return None

    class_name = rule_payload["className"]
    preferred_langs = [language]
    if language.lower() != "english":
        preferred_langs.append("English")

    sanitized = load_sanitized_rule(class_name, preferred_langs)
    sanitized_summary = format_sanitized_rule_for_prompt(sanitized)

    simple_name = class_name.rsplit(".", 1)[-1]
    crysl_path = RULES_DIR / f"{simple_name}.crysl"
    raw_crysl = crysl_path.read_text(encoding="utf-8") if crysl_path.exists() else ""
    crysl_sections = crysl_to_json_lines(raw_crysl) if raw_crysl else {}

    def prefer(section: str, fallback_key: str) -> str:
        if section in crysl_sections and crysl_sections[section]:
            return lines_to_text(crysl_sections[section])
        return rule_payload.get(fallback_key, "N/A")

    objects_txt = prefer("OBJECTS", "objects")
    events_txt = prefer("EVENTS", "events")
    order_txt = prefer("ORDER", "order")
    constraints_txt = prefer("CONSTRAINTS", "constraints")
    requires_txt = prefer("REQUIRES", "requires")
    ensures_txt = prefer("ENSURES", "ensures")
    forbidden_txt = prefer("FORBIDDEN", "forbidden")

    crysl_summary = "\n".join([
        f"SPEC: {class_name}",
        f"OBJECTS: {objects_txt}",
        f"EVENTS: {events_txt}",
        f"ORDER: {order_txt}",
        f"CONSTRAINTS: {constraints_txt}",
        f"REQUIRES: {requires_txt}",
        f"ENSURES: {ensures_txt}",
        f"FORBIDDEN: {forbidden_txt}",
    ])

    explanation = read_llm_cache(class_name, language, cache_dir) or read_llm_cache(class_name, "English", cache_dir)

    dep_order_constraints, dep_map_constraints = collect_dependency_constraints(class_name, preferred_langs)
    dep_constraints_text = format_dependency_constraints(dep_order_constraints, dep_map_constraints)

    dep_order_ensures, dep_map_ensures = collect_dependency_ensures(class_name, preferred_langs, depth=1)
    dep_ensures_text = format_dependency_ensures(class_name, dep_order_ensures, dep_map_ensures)

    rag_block = ""
    rag_sources = ""
    idx = chunks = None
    if pdf_path and pdf_path.exists():
        try:
            idx, chunks = build_pdf_index(str(pdf_path), emb_model=emb_model)
            sections = {
                "SPEC": class_name,
                "OBJECTS": objects_txt,
                "EVENTS": events_txt,
                "ORDER": order_txt,
                "CONSTRAINTS": constraints_txt,
                "REQUIRES": requires_txt,
                "ENSURES": ensures_txt,
            }
            rag_block, rag_sources = make_rag_context(
                client=OpenAI(api_key=os.getenv("OPENAI_API_KEY")),
                idx=idx,
                chunks=chunks,
                emb_model=emb_model,
                sections=sections,
                k=k,
            )
        except Exception as exc:
            print(f"[WARN] RAG disabled (build failed): {exc}", file=sys.stderr)

    raw_excerpt = raw_crysl if len(raw_crysl) <= 2000 else raw_crysl[:2000] + "\n..."

    prompt_ctx = {
        "class_name": class_name,
        "crysl_summary": crysl_summary,
        "sanitized_summary": sanitized_summary,
        "cached_explanation": explanation,
        "dep_ensures_text": dep_ensures_text,
        "dep_constraints_text": dep_constraints_text,
        "raw_crysl_excerpt": raw_excerpt,
        "order_txt": order_txt,
    }

    prompt = build_secure_prompt(prompt_ctx)

    system_messages = [
        {
            "role": "system",
            "content": (
                "You are a meticulous secure Java cryptography assistant. Produce production-quality code, "
                "prefer constant-time primitives, and never invent APIs outside the official JCA/JCE surface."
            ),
        }
    ]
    if rag_block:
        system_messages.append({
            "role": "system",
            "content": "REFERENCE MATERIAL (do not quote or cite):\n" + rag_block,
        })

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=model,
        messages=system_messages + [{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000,
    )
    code = response.choices[0].message.content.strip()
    print(code)
    return code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate secure Java examples grounded in CrySL specs, cached explanations, and CrySL paper RAG."
    )
    parser.add_argument("json_path", help="Path to the temp JSON produced by the Java pipeline.")
    parser.add_argument("--language", default="English", help="Language used for sanitized rules and cached explanations.")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI chat model for code generation.")
    parser.add_argument("--pdf", default=str(PDF_PATH), help="Path to the CrySL PDF for retrieval-augmented context.")
    parser.add_argument("--k", type=int, default=4, help="Number of PDF chunks to retrieve for RAG context.")
    parser.add_argument("--emb-model", default="text-embedding-3-small", help="Embedding model used for PDF retrieval queries.")
    parser.add_argument(
        "--cache-dir",
        default=str(CACHE_DIR),
        help="Directory storing llm_cache explanations (defaults to Output/resources/llm_cache).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_path = Path(args.json_path)
    language = args.language
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = Path(args.pdf) if args.pdf else None

    process_rule(
        json_path=json_path,
        language=language,
        model=args.model,
        pdf_path=pdf_path,
        k=args.k,
        emb_model=args.emb_model,
        cache_dir=cache_dir,
    )


if __name__ == "__main__":
    main()