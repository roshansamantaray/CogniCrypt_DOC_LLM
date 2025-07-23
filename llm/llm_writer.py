#!/usr/bin/env python3
import os
import sys
import json
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

# Ensure project root is on PYTHONPATH for llm imports
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from llm.rag_utils.vector_store_manager import VectorStoreManager
from langchain.prompts import ChatPromptTemplate

def escape_braces(s: str) -> str:
    # ord('{') == 123, ord('}') == 125; map them to None to delete
    return s.replace("{", "{{").replace("}", "}}")

def crysl_to_json_lines(crysl_text):
    sections = ["SPEC", "OBJECTS", "EVENTS", "ORDER",
                "CONSTRAINTS", "REQUIRES", "ENSURES"]
    pat = re.compile(r"\b(" + "|".join(sections) + r")\b")
    matches = list(pat.finditer(crysl_text))
    out = {}
    for i, m in enumerate(matches):
        header = m.group(1)
        start = m.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(crysl_text)
        # split on real line breaks, drop any empty trailing
        raw_lines = crysl_text[start:end].strip().splitlines()
        lines = [line.strip() for line in raw_lines if line.strip()]
        out[header] = lines
    return out

def clean_llm_output(text: str) -> str:
    """
    Strip Markdown code fences, bold markers, and headers.
    """
    text = re.sub(r"```(?:java|text)?", "", text)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"^##\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def validate_and_fill(rule: dict, path: str, language: str) -> dict:
    """
    Ensure all required keys exist, warn if missing, and set defaults.
    """
    defaults = {
        'SPEC': '',
        'OBJECTS': 'None',
        'EVENTS': 'N/A',
        'ORDER': 'N/A',
        'CONSTRAINTS': 'N/A',
        'REQUIRES': 'None',
        'ENSURES': 'N/A',
        'FORBIDDEN': 'N/A',
        'LANGUAGE': language
    }
    # print(f"Warning: New Keys unaccounted in {rule.get('className')}")
    # for key in rule:
    #     if key not in defaults:
    #         print(f"Warning: unrecognized key '{key}' in {path}, ignoring.", file=sys.stderr)

    for key, default in defaults.items():
        if key not in rule:
            rule[key] = default
    # print(rule)
    return rule


def generate_semantic_query(client, model: str, class_name: str, objects: str, events: str,
                            order: str, constraints: str, requires: str,
                            ensures: str, forbidden: str) -> str:
    # Earlier Template
    prompt ="""
        You are a cryptography-documentation assistant.
        Given the CrySL rule for class `{class_name}`, produce a single-line search query
        that will retrieve the most relevant template snippets in.

        CrySL Rule:
        ```
        Objects: {objects}
        Events: {events}
        Order: {order}
        Constraints: {constraints}
        Requires: {requires}
        Ensures: {ensures}
        Forbidden: {forbidden}
        ```
        """

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful cryptography assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )
    return resp.choices[0].message.content.strip()


def generate_explanation(client, model: str, class_name: str, objects: str, events: str,
                         order: str, constraints: str, requires: str,
                         ensures: str, forbidden: str, tpl_snippets: str, explanation_language: str) -> str:
    tpl_count = len(tpl_snippets.split('\n\n──\n\n'))
    prompt = f"""
                
        You are a Cryptographic Specification Language (CrySL) expert and a Java cryptography assistant.

        You have been given these parsed CrySL elements for class `{class_name}`:
        **SPEC**: Target class → `{class_name}`  
        **OBJECTS**:  
        {objects}  
        **EVENTS**:  
        {events}  
        **ORDER** (regular‐expression sequence):  
        `{order}`  
        **CONSTRAINTS** (parameter restrictions):  
        {constraints}  
        **REQUIRES** predicates:  
        {requires}  
        **ENSURES** predicates:  
        {ensures}  
        **FORBIDDEN** methods:  
        {forbidden}

        Also, here are the top {tpl_count} retrieved template snippets to ground your explanation:
        {tpl_snippets}

        Your task is to produce a **complete, accurate, and self-contained** explanation of this rule, strictly using only the values provided above. You must:

        1. **No Hallucinations**  
            - Do not introduce any algorithms, key sizes, or methods beyond those in the JSON.  
            - If any section is empty or missing, explicitly state “_no X specified_” rather than inventing.  

        2. **CrySL Syntax Breakdown**  
            **SPEC**: Identify the target class (`className`).  
            **OBJECTS**: List each object binding (type + name).  
            **EVENTS**: Explain each labeled method call, parameters, and aggregates.  
            **ORDER**: Describe the regular-expression sequence (concatenation [,]) , alternation [|], optional [?], zero or more repetition [*],at least one or more repitition [+], grouping [()]).  
            **CONSTRAINTS**: Enumerate each parameter constraint and any conditional constraints.  
            **FORBIDDEN**: Methods that must never be called.  
            **REQUIRES**: Explained as preconditions that must already be ensured.
            **ENSURES**: Explained as postconditions that generate predicates for others.
            **NEGATES**: Explained as invalidating previously ensured predicates.  

        3. **Formal Semantics Checks**  
            **Forbidden check :** Show that no forbidden events occur.  
            **Ordering check :** Explain how the event sequence matches the ORDER regex.  
            **Constraint check :** Demonstrate all parameter constraints hold.  
            **Predicate semantics :** For each ENSURES, REQUIRES, NEGATES predicate, explain when it is generated, required, or invalidated.  

        4. **Structured Explanation**  
            Use this Markdown outline:
            1. **Overview** - Brief summary of what the rule enforces.  
            2. **Correct Usage** - Step-by-step walkthrough of events in order.  
            3. **Parameters & Constraints** - Table or list of parameters with allowed values.  
            4. **Predicates & Interactions** - Explain ENSURES/REQUIRES/NEGATES with examples.  
            5. **Forbidden Patterns** - What must never happen.  
            6. **Edge Cases** - If any optional or repeating events alter behavior.  
            7. **Security Rationale** - Why each constraint/order is necessary.

        Respond in **{explanation_language}** and be as precise as possible.
        """

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful cryptography assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    return resp.choices[0].message.content


def process_rule(path: str, language: str, client, vs_mgr, model: str):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # print(f"Read {len(content)} characters from {path}")
    except Exception as e:
        print(f"Error loading JSON from {path}: {e}", file=sys.stderr)
        return
    content = escape_braces(content)
    # print(type(content))
    # print(content)
    crysl_data = crysl_to_json_lines(content)
    # print(crysl_data)
    rule = validate_and_fill(crysl_data, path, language)
    # print(rule)
    class_name = rule['SPEC']
    objects = rule['OBJECTS']
    events = rule['EVENTS']
    order = rule['ORDER']
    constraints = rule['CONSTRAINTS']
    requires = rule['REQUIRES']
    ensures = rule['ENSURES']
    forbidden = rule['FORBIDDEN']
    explanation_language = rule['LANGUAGE']

    # Stage 1: semantic query
    try:
        query = generate_semantic_query(client, model, class_name, objects, events, order, constraints, requires, ensures, forbidden)
    except OpenAIError as e:
        print(f"LLM semantic-query error for {class_name}: {e}", file=sys.stderr)
        return

    # Stage 2: retrieval
    tpl_chunks = vs_mgr.similarity_search(query, k=3)
    snippets = "\n\n──\n\n".join(chunk.page_content for chunk in tpl_chunks)
    # print(snippets)

    # Stage 3: explanation
    # print(rule)
    try:
        raw_out = generate_explanation(client, model, class_name, objects, events, order, constraints, requires, ensures, forbidden, snippets, explanation_language)
    except OpenAIError as e:
        print(f"LLM explanation error for {class_name}: {e}", file=sys.stderr)
        return

    cleaned = clean_llm_output(raw_out)
    print(cleaned)


def main():
    parser = argparse.ArgumentParser(
        description="Generate CrySL rule explanations via LLM and FAISS retrieval"
    )
    parser.add_argument(
        'class_name_full', nargs='+',
        help='Class Name of the CrySL File'
    )
    parser.add_argument(
        'language', nargs='+',
        help='Explaination Language of the CrySL File'
    )
    parser.add_argument(
        '--index-path', '-i',
        default='llm/rag_utils/template_faiss_index',
        help='Path to FAISS index directory'
    )
    parser.add_argument(
        '--model', '-m', default='gpt-4o-mini',
        help='OpenAI model to use for completions'
    )
    args = parser.parse_args()
    class_name = args.class_name_full
    class_name = class_name[0]
    language = args.language
    # print(language)
    # print(type(class_name))
    # print(class_name)
    class_name = class_name.rsplit('.', 1)[-1]
    file_name = class_name+".crysl"
    directory = "C:/Users/rosha/OneDrive - Universität Paderborn/College/Work/Codes/CogniCrypt_DOC_LLM/src/main/resources/CrySLRules"    # Change to the directory you want to search

    full_path = os.path.join(directory, file_name)

    if os.path.isfile(full_path):
        pass
    else:
        print(f"{file_name} not found in {directory}.")
        return

    load_dotenv()
    vs_mgr = VectorStoreManager()
    vs_mgr.load_store(index_path=args.index_path)
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    process_rule(full_path, language, client, vs_mgr, args.model)

if __name__ == '__main__':
    main()
