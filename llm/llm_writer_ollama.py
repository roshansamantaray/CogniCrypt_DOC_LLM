# python
#!/usr/bin/env python3
import os
import sys
import json
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np
from dotenv import load_dotenv

# Use the Ollama-based index module
from paper_index_ollama import build_pdf_index, get_ollama_client

try:
    # ensure Python stdout uses UTF-8 (Python 3.7+)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    # fallback: rely on caller to set PYTHONIOENCODING
    pass


# Resolve project root and important folders
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "src" / "main" / "resources" / "CrySLRules"
SANITIZED_DIR = PROJECT_ROOT / "llm" / "sanitized_rules"
FILENAME_TEMPLATE = "sanitized_rule_{fqcn}_{lang}.json"
SANITIZED_DIR.mkdir(parents=True, exist_ok=True)
PDF_PATH = PROJECT_ROOT / "tse19CrySL.pdf"

def rule_path(fqcn: str, lang: str) -> Path:
    sanitized_name =  SANITIZED_DIR / FILENAME_TEMPLATE.format(fqcn=fqcn, lang=lang)
    return sanitized_name

def load_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] Missing file: {path}", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Could not read {path}: {e}", file=sys.stderr)
    return None

def clean_item(s):
    if not isinstance(s, str):
        return str(s)
    s2 = s.strip()
    if s2.startswith(","):
        s2 = s2.lstrip(",").strip()
    return s2

def collect_dependency_constraints(target_fqcn: str, language: str) -> Tuple[List[str], Dict[str, List[str]]]:
    dep_to_constraints : Dict[str, List[str]] = {}
    deps_order: List[str] = []

    primary_path = rule_path(target_fqcn, language)
    primary = load_json(primary_path)
    if not primary:
        return deps_order, dep_to_constraints

    deps = primary.get("dependency") or []
    seen = set()
    for dep in deps:
        if dep == target_fqcn or dep in seen:
            continue
        seen.add(dep)
        deps_order.append(dep)

        dep_path = rule_path(dep, language)
        dep_json = load_json(dep_path)
        if not dep_json:
            dep_to_constraints[dep] = []
            continue

        constraints = dep_json.get("constraints")
        if constraints is None:
            constraints = dep_json.get("constraint")
        if constraints is None:
            constraints = []
        if not isinstance(constraints, list):
            constraints = [constraints]
        dep_to_constraints[dep] = [clean_item(c) for c in constraints]

    return deps_order, dep_to_constraints

def format_dependency_constraints(deps_order: List[str], dep_to_constraints: Dict[str, List[str]]) -> str:
    if not deps_order:
        return "No dependency constraints supplied."
    parts = []
    for dep in deps_order:
        constraints = dep_to_constraints.get(dep, []) or []
        if not constraints:
            parts.append(f"Dependency: {dep}\n  - (no constraints)")
        else:
            lines = "\n".join(f"  - {c}" for c in constraints)
            parts.append(f"Dependency: {dep}\n{lines}")
    return "\n\n".join(parts)

def _normalize_listish(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_item(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return [clean_item(value)]

def collect_dependency_ensures(primary_fqcn: str, language: str, depth: int = 1) -> Tuple[List[str], Dict[str, List[str]]]:
    """Return (deps_order, dep_to_ensures) where dep_to_ensures maps fqcn -> list[str].
    depth=1 means direct dependencies only. Cycle-safe.
    """
    dep_to_ensures: Dict[str, List[str]] = {}
    deps_order: List[str] = []

    primary = load_json(rule_path(primary_fqcn, language))
    if not primary:
        return deps_order, dep_to_ensures

    roots = primary.get("dependency") or []
    seen = {primary_fqcn}

    def visit(fqcn: str, cur_depth: int):
        if fqcn in seen:
            return
        seen.add(fqcn)
        if fqcn not in deps_order:
            deps_order.append(fqcn)

        data = load_json(rule_path(fqcn, language))
        if not data:
            dep_to_ensures[fqcn] = []
            return

        dep_to_ensures[fqcn] = _normalize_listish(data.get("ensures"))

        # Recurse if requested
        if cur_depth < depth:
            for sub in _normalize_listish(data.get("dependency")):
                visit(sub, cur_depth + 1)

    for dep in roots:
        if isinstance(dep, str) and dep:
            visit(dep, 1)

    return deps_order, dep_to_ensures

def format_dependency_ensures(primary_fqcn: str, deps_order: List[str], dep_to_ensures: Dict[str, List[str]]) -> str:
    if not deps_order:
        return f"No dependent component guarantees were available for {primary_fqcn}."

    lines = [
        f"### How related components influence {primary_fqcn}",
        ("Below are the guarantees (postconditions) that related classes provide when used correctly. "
         "Use these to explain why and how the primary class depends on them.\n")
    ]
    for fqcn in deps_order:
        ensures = dep_to_ensures.get(fqcn, []) or []
        if not ensures:
            lines.append(f"- **{fqcn}**: *(no ensures available or file missing)*")
            continue
        lines.append(f"- **{fqcn}**:")
        lines.extend([f"  - {e}" for e in ensures])
    return "\n".join(lines)

def crysl_to_json_lines(crysl_text: str) -> Dict[str, List[str]]:
    sections = [
        "SPEC",
        "OBJECTS",
        "EVENTS",
        "ORDER",
        "CONSTRAINTS",
        "REQUIRES",
        "ENSURES",
        "FORBIDDEN",
    ]
    pat = re.compile(r"\b(" + "|".join(sections) + r")\b")
    matches = list(pat.finditer(crysl_text))
    out: Dict[str, List[str]] = {}
    for i, m in enumerate(matches):
        header = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(crysl_text)
        raw_lines = crysl_text[start:end].strip().splitlines()
        lines = [line.strip() for line in raw_lines if line.strip()]
        out[header] = lines
    return out

def clean_llm_output(text: str) -> str:
    # Keep Markdown headings; just strip stray code fences
    text = re.sub(r"^```(?:\w+)?\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()

def lines_to_text(section) -> str:
    if isinstance(section, list):
        return "\n".join(section) if section else "_no entries_"
    return str(section) if section else "_no entries_"

def validate_and_fill(rule: dict, language: str) -> dict:
    defaults = {
        "SPEC": "",
        "OBJECTS": "None",
        "EVENTS": "N/A",
        "ORDER": "N/A",
        "CONSTRAINTS": "N/A",
        "REQUIRES": "None",
        "ENSURES": "N/A",
        "FORBIDDEN": "N/A",
        "LANGUAGE": language,
    }
    for key, default in defaults.items():
        if key not in rule:
            rule[key] = default
    return rule

def format_sanitized_rule_for_prompt(sanitized: dict) -> str:
    if not sanitized:
        return "No sanitized fields supplied."
    exclude = {"dependency"}
    parts = []
    for key, val in sanitized.items():
        if key in exclude or val is None:
            continue
        k = str(key)
        if isinstance(val, list):
            if not val:
                continue
            lines = "\n".join(f"- {clean_item(it)}" for it in val)
            parts.append(f"{k}:\n{lines}")
        elif isinstance(val, dict):
            if not val:
                continue
            lines = "\n".join(f"- {ik}: {clean_item(iv)}" for ik, iv in val.items())
            parts.append(f"{k}:\n{lines}")
        else:
            parts.append(f"{k}: {clean_item(val)}")
    return "\n\n".join(parts) if parts else "No sanitized fields supplied."

def _embed_texts(client, texts: List[str], model: str = "text-embedding-3-small") -> np.ndarray:
    """
    Use the Ollama client's embeddings.create to embed a list of texts.
    Accepts responses shaped as {"data":[{"embedding": [...]}, ...]} or a list.
    Returns np.ndarray of shape (n, dim) dtype float32.
    """
    resp = client.embeddings.create(model=model, input=texts)
    if isinstance(resp, dict) and "data" in resp:
        return np.asarray([d["embedding"] for d in resp["data"]], dtype="float32")
    if isinstance(resp, list):
        arr = [item.get("embedding") if isinstance(item, dict) else item for item in resp]
        return np.asarray(arr, dtype="float32")
    raise RuntimeError("Unexpected embeddings response: %r" % (resp,))

def _generate_text(client, model: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> str:
    """
    Call Ollama generate and try to extract text robustly.
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

def make_rag_context(
        client,
        idx,                   # from paper_index_ollama.build_pdf_index
        chunks,                # list of DocChunk (must have .text)
        emb_model: str,
        rule_sections_txt: Dict[str, str],
        k: int = 6,
        per_chunk_max: int = 900,
) -> Tuple[str, str]:
    """
    Returns (rag_block, rag_sources_block).
    Uses the Ollama client to embed the retrieval query and the EmbeddingIndex.search API.
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
        return "", ""

    q_vec = _embed_texts(client, [query], model=emb_model)[0]
    # Use the EmbeddingIndex.search wrapper
    hits = idx.search(q_vec, k)
    rag_items = []
    rag_ids = []
    for hid, score in hits:
        matching = next((c for c in chunks if c.id == hid), None)
        if not matching:
            continue
        text = getattr(matching, "text", "")
        if per_chunk_max and len(text) > per_chunk_max:
            text = text[:per_chunk_max] + " ..."
        rag_items.append(f"[{matching.id}] {text}\n")
        rag_ids.append(f"[{matching.id}]")
    rag_block = "\n\n".join(rag_items)
    rag_sources_block = " ".join(rag_ids)
    return rag_block, rag_sources_block

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
        dep_ensures_text: str,  # NEW
        sanitized_summary: str,
        raw_crysl_text: str,
        explanation_language: str,
        rag_block: str = "",
        rag_sources: str = "",
) -> str:
    prompt = fr"""
You are a cryptography expert who explains complex CrySL rules to Java developers in clear, natural language.

You are analyzing the CrySL specification for: `{class_name}`

Raw CrySL Data:
- OBJECTS: {objects}
- EVENTS: {events}
- ORDER: {order}
- CONSTRAINTS: {constraints}
- REQUIRES: {requires}
- ENSURES: {ensures}
- FORBIDDEN: {forbidden}
- Dependency Constraints (reference only): {dep_constraints_text}
- Dependency Guarantees (ENSURES):
{dep_ensures_text}
- Additional context: {sanitized_summary}
- Original CrySL: {raw_crysl_text}

Your Task: Create a developer-friendly guide that explains how to correctly use this cryptographic class WITHOUT using technical CrySL notation, event labels, or abstract parameter names.

CRITICAL RULES:
1. NO TABLES containing event labels (like g1, i2, u3) or parameter lists
2. NO technical identifiers from CrySL should appear in the output
3. NO abstract variable names (like prePlainText, preCipherTextOffset) in explanations
4. EVERYTHING must be explained in natural, conversational language
5. Use concrete, meaningful examples that developers can relate to
6. Focus on practical usage, not formal specifications\
7. Use any provided reference material ONLY to inform your understanding; do NOT quote it, cite it, or mention its existence in the output.

Output Structure - Use these EXACT section headings (start with ## and no leading spaces):

## Overview
Write 2-3 paragraphs explaining what this class does, its role in Java cryptography, and why developers would use it. Make it conversational and informative.

## Correct Usage
Explain the complete workflow as a narrative story. Use phrases like:
- "To start, you'll need to..."
- "The first step is to..."
- "After obtaining an instance..."
- "Finally, complete the operation by..."

Don't just list methods - explain the logical flow and the purpose of each step. Include method names naturally within sentences.

## Parameters and Constraints
Group related constraints into logical categories and explain them in full sentences. For each constraint:
- Explain WHAT is restricted and WHY
- List allowed values with explanations of when to use each
- Describe the security implications

Format as grouped bullet points with full explanations, like:
- **Algorithm choices:** [Full explanation of which algorithms are allowed and why]
- **Key requirements:** [Explanation of what types of keys are needed]
- **Data handling rules:** [Explanation of buffer sizes, offsets, etc. in practical terms]

When listing allowed values (algorithms, modes, etc.), explain what each means and when to use it.

## Method Variations and Use Cases
Group methods by their purpose and explain when to use each variation. Structure as:

### [Functional Group Name]
Explanation of what this group of methods does, followed by:
- **Scenario 1:** Description and when to use this approach
- **Scenario 2:** Description and when to use this alternative
- etc.

For example, instead of listing "init variants i1-i8", group them as "Initialization Options" and explain each scenario where you'd use different parameters.

## Security Requirements
Translate all REQUIRES/ENSURES predicates into plain English requirements that developers can understand:
- Instead of "REQUIRES: generatedKey[key]", write something like "Before using this method, ensure your key was generated using a cryptographically secure key generator"
- Explain what security guarantees the class provides after operations
- Describe any dependencies on other cryptographic operations

**Also incorporate the Dependency Guarantees below:** connect each related class's guarantees to the steps where they matter for `{class_name}`.

## Related Components & Their Guarantees
Use this section to list and explain guarantees from related classes, and explicitly tie them to `{class_name}` usage decisions. Start by summarizing the list below, then expand with plain-English implications for initialization, parameter selection, and error handling.

---
{dep_ensures_text}
---

## Common Mistakes to Avoid
Convert all FORBIDDEN items and constraint violations into practical warnings:
- Explain what NOT to do and the consequences
- Include common programming errors related to this class
- Describe what happens if required steps are skipped

## Quick Reference Checklist
Create a practical checklist written as questions a developer can verify:
- Have you [specific action]?
- Did you ensure [specific requirement]?
- Is your [component] properly [configured/initialized/etc.]?

Make each item actionable and specific to this class's requirements.

WRITING STYLE GUIDELINES:

1. **Replace Technical Terms:**
   - Event labels (g1, i2) → Describe the actual operation
   - Parameter names from CrySL → Meaningful descriptions
   - Regex patterns → Step-by-step explanations
   - Predicates → Security requirements in plain English

2. **Use Natural Language Patterns:**
   - "When you need to..." instead of "Event x1 with parameters..."
   - "This ensures that..." instead of "ENSURES: predicate[...]"
   - "You must first..." instead of "REQUIRES: predicate[...]"
   - "Never call..." instead of "FORBIDDEN: method[...]"

3. **Make It Practical:**
   - Relate to real-world scenarios
   - Explain the 'why' behind each requirement
   - Use analogies where helpful
   - Focus on what developers need to do, not on formal specifications

4. **Be Specific About Security:**
   - Explain why each constraint exists
   - Describe attack scenarios that constraints prevent
   - Clarify the security impact of each requirement

Remember: Your audience is Java developers who need to use this cryptographic class correctly but may not be security experts. Every explanation should help them understand not just WHAT to do, but WHY it matters for security.

The goal is to produce documentation that a developer can read like a tutorial, not a reference manual. They should understand how to use the class correctly without ever seeing CrySL syntax or formal notation.
Respond in **{explanation_language}** and be as precise as possible.\
Make sure that the response is in **utf-8** charset only.
"""
    sys_msgs = [
        {
            "role": "system",
            "content": (
                "You are a patient teacher who excels at explaining complex technical concepts in simple, practical terms. "
                "Use any reference material provided to interpret CrySL syntax precisely, but do NOT quote it, cite it, "
                "or mention its existence in your final answer."
            ),
        }
    ]

    # Add RAG context as hidden reference material (only if available)
    if rag_block:
        sys_msgs.append({
            "role": "system",
            "content": "REFERENCE MATERIAL (do not quote, cite, or mention this explicitly):\n" + rag_block
        })

    # call Ollama-style generate wrapper
    return _generate_text(client, model, "\n\n".join([m["content"] for m in sys_msgs]) + "\n\n" + prompt, max_tokens=1600, temperature=0.2)

def process_rule(crysl_path: str, language: str, client, model: str, target_fqcn: str, idx=None, chunks=None, k: int = 6, emb_model: str = "text-embedding-3-small"):
    try:
        with open(crysl_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error loading CrySL from {crysl_path}: {e}", file=sys.stderr)
        return

    crysl_data = crysl_to_json_lines(content)
    rule = validate_and_fill(crysl_data, language)

    # Fallback to FQCN if SPEC missing
    if isinstance(rule["SPEC"], list):
        class_name = rule["SPEC"][0] if rule["SPEC"] else target_fqcn
    else:
        class_name = rule["SPEC"] or target_fqcn

    # Prepare human-readable blocks
    objects_txt = lines_to_text(rule["OBJECTS"])
    events_txt = lines_to_text(rule["EVENTS"])
    order_txt = lines_to_text(rule["ORDER"])
    constraints_txt = lines_to_text(rule["CONSTRAINTS"])
    requires_txt = lines_to_text(rule["REQUIRES"])
    ensures_txt = lines_to_text(rule["ENSURES"])
    forbidden_txt = lines_to_text(rule.get("FORBIDDEN", "N/A"))

    # Dependency constraints (kept for reference)
    deps_order_c, dep_to_constraints = collect_dependency_constraints(target_fqcn, language)
    dep_constraints_text = format_dependency_constraints(deps_order_c, dep_to_constraints)

    # Dependency ensures (NEW)
    deps_order_e, dep_to_ensures = collect_dependency_ensures(target_fqcn, language, depth=1)
    dep_ensures_text = format_dependency_ensures(target_fqcn, deps_order_e, dep_to_ensures)

    # Load primary sanitized rule and format its human-friendly fields
    primary_sanitized = load_json(rule_path(target_fqcn, language))
    sanitized_summary = (
        format_sanitized_rule_for_prompt(primary_sanitized)
        if primary_sanitized
        else "No sanitized fields supplied."
    )

    # (Optional) RAG context from the CrySL paper
    rag_block = ""
    rag_sources = ""
    if idx is not None and chunks is not None and hasattr(idx, "index"):
        sect = {
            "SPEC": class_name,
            "OBJECTS": objects_txt,
            "EVENTS": events_txt,
            "ORDER": order_txt,
            "CONSTRAINTS": constraints_txt,
            "REQUIRES": requires_txt,
            "ENSURES": ensures_txt,
        }
        rag_block, rag_sources = make_rag_context(
            client, idx, chunks, emb_model=emb_model, rule_sections_txt=sect, k=k
        )


    try:
        raw_out = generate_explanation(
            client=client,
            model=model,
            class_name=class_name,
            objects=objects_txt,
            events=events_txt,
            order=order_txt,
            constraints=constraints_txt,
            requires=requires_txt,
            ensures=ensures_txt,
            forbidden=forbidden_txt,
            dep_constraints_text=dep_constraints_text,
            dep_ensures_text=dep_ensures_text,
            sanitized_summary=sanitized_summary,
            raw_crysl_text=content,
            explanation_language=language,
            rag_block=rag_block,
            rag_sources=rag_sources,
        )
    except Exception as e:
        print(f"LLM explanation error for {class_name}: {e}", file=sys.stderr)
        return

    cleaned = clean_llm_output(raw_out)
    print(cleaned)
    return cleaned

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate CrySL rule explanations via Ollama LLM (with dependency ENSURES + constraints, optional RAG)"
        )
    )
    parser.add_argument(
        "class_name_full",
        help=(
            "Fully qualified class name of the CrySL rule (e.g., java.security.AlgorithmParameters)"
        ),
    )
    parser.add_argument(
        "language",
        help="Explanation language (e.g., English)",
    )
    parser.add_argument(
        "--model", "-m", default=os.getenv("OLLAMA_MODEL", "llama2"),
        help="Ollama model to use for completions (e.g., 'llama2')",
    )
    parser.add_argument(
        "--pdf",
        default=str(PDF_PATH),
        help=f"Path to the CrySL paper PDF for RAG (default: {PDF_PATH})"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=6,
        help="How many chunks to retrieve from the paper for context"
    )
    parser.add_argument(
        "--emb-model",
        default="text-embedding-3-small",
        help="Embedding model for RAG queries"
    )
    args = parser.parse_args()

    class_name_full = args.class_name_full
    language = args.language

    simple_name = class_name_full.rsplit(".", 1)[-1]
    crysl_filename  = f"{simple_name}.crysl"
    crysl_full_path  = RULES_DIR / crysl_filename

    if not crysl_full_path .is_file():
        print(f"{crysl_filename} not found in {RULES_DIR}.", file=sys.stderr)
        return

    load_dotenv()
    client = get_ollama_client()
    idx = None
    chunks = None
    try:
        if args.pdf and Path(args.pdf).exists():
            idx, chunks = build_pdf_index(args.pdf, emb_model=args.emb_model)
        else:
            print(f"[INFO] Skipping RAG: PDF not found at {args.pdf}", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] RAG disabled (index build/load failed): {e}", file=sys.stderr)
    process_rule(
        str(crysl_full_path),
        language,
        client,
        args.model,
        class_name_full,
        idx=idx,
        chunks=chunks,
        k=args.k,
        emb_model=args.emb_model,
    )

if __name__ == "__main__":
    main()
