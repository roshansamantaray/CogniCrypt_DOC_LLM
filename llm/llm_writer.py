# python
#!/usr/bin/env python3
import os
import sys
import json
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Resolve project root and important folders
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "src" / "main" / "resources" / "CrySLRules"
SANITIZED_DIR = PROJECT_ROOT / "llm" / "sanitized_rules"
FILENAME_TEMPLATE = "sanitized_rule_{fqcn}_{lang}.json"
SANITIZED_DIR.mkdir(parents=True, exist_ok=True)

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

def collect_dependency_constraints(target_fqcn: str, language: str):
    dep_to_constraints = {}
    deps_order = []

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

def format_dependency_constraints(deps_order, dep_to_constraints):
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

def _normalize_listish(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_item(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    return [clean_item(value)]

def collect_dependency_ensures(primary_fqcn: str, language: str, depth: int = 1):
    """Return (deps_order, dep_to_ensures) where dep_to_ensures maps fqcn -> list[str].
    depth=1 means direct dependencies only. Cycle-safe.
    """
    dep_to_ensures = {}
    deps_order = []

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

def format_dependency_ensures(primary_fqcn: str, deps_order, dep_to_ensures):
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

def crysl_to_json_lines(crysl_text):
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
    out = {}
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
6. Focus on practical usage, not formal specifications

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

**Also incorporate the Dependency Guarantees above:** connect each related class's guarantees to the steps where they matter for `{class_name}`.

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

The goal is to produce documentation that a developer can read like a tutorial, not a reference manual. They should understand how to use the class correctly without ever seeing CrySL syntax or formal notation.\
Respond in **{explanation_language}** and be as precise as possible.
"""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a patient teacher who excels at explaining complex technical concepts in simple, practical terms.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4000,
        stop=["```"]
    )
    return resp.choices[0].message.content

def process_rule(crysl_path: str, language: str, client, model: str, target_fqcn: str):
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

    try:
        raw_out = generate_explanation(
            client,
            model,
            class_name,
            objects_txt,
            events_txt,
            order_txt,
            constraints_txt,
            requires_txt,
            ensures_txt,
            forbidden_txt,
            dep_constraints_text,
            dep_ensures_text,  # NEW
            sanitized_summary,
            content,
            language,
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
            "Generate CrySL rule explanations via LLM (with dependency ENSURES + constraints, no RAG)"
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
        "--model",
        "-m",
        default="gpt-4o-mini",
        help="OpenAI model to use for completions",
    )
    args = parser.parse_args()

    class_name_full = args.class_name_full
    language = args.language

    simple_name = class_name_full.rsplit(".", 1)[-1]
    file_name = f"{simple_name}.crysl"
    full_path = RULES_DIR / file_name

    if not full_path.is_file():
        print(f"{file_name} not found in {RULES_DIR}.", file=sys.stderr)
        return

    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    process_rule(str(full_path), language, client, args.model, class_name_full)

if __name__ == "__main__":
    main()
