# TASK_2 — Full Project Architecture & Secure Code Generator Bottlenecks (CogniCrypt_DOC_LLM)

This document gives an end-to-end view of the repository:
- What the project does
- How **every major component** connects to others
- The exact Java → Python “secure code generation” pipeline
- The **current bottlenecks / correctness risks** in the **secure code generator side** (Python + integration points)

> Scope note: This file covers the whole repo architecture, but the “bottlenecks” section is focused on **secure code generation** (the `llm_code_writer_secure.py` path) and its supporting retrieval module `paper_index.py`.

---

## 0) What this project is

This repository generates **static documentation** for **CrySL rules** (CogniCrypt rules for secure Java cryptography API usage).

It has **two lanes**:

1) **Deterministic documentation generation (Java)**
- Reads CrySL rules
- Extracts usage patterns (ORDER), constraints, predicates, forbidden calls
- Computes cross-rule dependencies (REQUIRES/ENSURES)
- Renders a static HTML documentation site via FreeMarker

2) **Optional LLM augmentation (Python called from Java)**
- **Explanations** (Markdown) in multiple languages
- **Secure / insecure code examples**
- Uses structured JSON “rule context” produced by Java
- Can optionally ground generation with RAG from the CrySL paper PDF

---

## 1) Outputs (what the user sees)

The generator produces a website in the `--reportPath` directory, typically including:

- `rootpage.html` (frameset)
- `frontpage.html` (landing)
- `navbar.html` (sidebar)
- `crysl.html` (CrySL overview page)
- `composedRules/<FullyQualifiedClassName>.html` (one page per rule/class)

Per-class pages can contain:
- CrySL sections (ORDER / CONSTRAINTS / REQUIRES / ENSURES / FORBIDDEN)
- A **state machine** visualization (Graphviz DOT rendered by d3-graphviz)
- Dependency trees (Requires/Ensures)
- Optional LLM explanation (language dropdown)
- Optional LLM secure/insecure code examples (copy buttons; insecure hidden behind reveal)

---

## 2) Repository architecture — components & connections

### 2.1 Java “spine” components (deterministic lane)

#### A) `DocSettings.java` — CLI configuration (singleton)
- Parses CLI args, stores required paths and feature flags
- Controls whether LLM explanations/examples run and which backend is used

**Connected to:**
- `DocumentGeneratorMain` (reads settings)
- `FreeMarkerWriter` (reads feature flags for UI visibility)

#### B) `DocumentGeneratorMain.java` — orchestration pipeline
Runs the full workflow:
1. Parse settings
2. Read CrySL rules from `--rulesDir`
3. Build `ComposedRule` list (per rule)
4. Compute dependencies + ordering
5. (Optional) generate LLM explanations
6. (Optional) generate LLM secure/insecure examples
7. Render HTML

**Connected to:**
- CrySL parser/reader (external dep)
- Section builders (constraints/order/predicates/etc.)
- `Utils`, `GraphSanitizer`, `GraphVerification`, `PredicateTreeGenerator`
- `CrySLToLLMGenerator` (calls Python via `LLMService`)
- `FreeMarkerWriter` (render output)

#### C) `ComposedRule.java` — the per-class documentation model
A “view model” that contains everything FreeMarker needs:
- class identity
- order/constraints/predicates/forbidden sections
- dependency list and dependency trees
- LLM explanation map (language → markdown)
- secure/insecure code examples

**Connected to:**
- Built by `DocumentGeneratorMain`
- Passed to `FreeMarkerWriter` → `singleclass.ftl`
- Consumed by `CrySLToLLMGenerator` to build LLM JSON payload

#### D) Dependency & graph utilities
- `Utils.java` (predicate mapping, topo ordering, sanitization for LLM JSON)
- `GraphSanitizer.java` (reachability + SCC handling; cycle-safe graph)
- `GraphVerification.java` (sanity checks on ordering)
- `PredicateTreeGenerator.java` (builds tree nodes used by UI)

**Connected to:**
- `DocumentGeneratorMain` to compute dependency order and trees
- `FreeMarkerWriter` (renders trees)

#### E) Rendering layer
- `FreeMarkerWriter.java` (writes HTML files)
- `singleclass.ftl` (per-class page layout)
- External JS libs used by template:
    - d3-graphviz + hpcc-wasm for Graphviz rendering
    - marked.js for Markdown rendering

**Connected to:**
- `ComposedRule` (rule content, LLM outputs)
- dependency trees (`TreeNode`)
- state machine DOT text (from state machine converter)

---

### 2.2 Java → Python “LLM augmentation” connector

#### A) `CrySLToLLMGenerator.java` — context packer
Creates structured dictionaries (`cryslData`) from:
- `ComposedRule` (already formatted text sections)
- `CrySLRule` (raw rule model)
  Calls `LLMService` for:
- explanations (multi-language)
- code examples (secure/insecure)

#### B) `LLMService.java` — process runner + explanation caching
- Locates Python executable (prefers `llm/.venv/...`)
- Writes temp JSON files to `llm/temp_rules` (explanations) and to `llm/temp_example_secure.json` (examples)
- Writes sanitized JSON files to `llm/sanitized_rules`
- Executes Python scripts
- Captures stdout as the “LLM result”
- Caches explanation text under `Output/resources/llm_cache/...`
- Code example caching is mainly done by Java (`Output/resources/code_cache/...`)

**Connected to:**
- Secure generator script: `llm/llm_code_writer_secure.py`
- Insecure generator script (mirror): `llm/llm_code_writer_insecure.py`
- Explanation scripts: `llm/llm_writer*.py`
- Sanitizer: `Utils.sanitizeRuleFileSecure(...)`

---

## 3) Secure Code Generation (Python) — what happens end-to-end

### 3.1 Entry point
**Script:** `llm_code_writer_secure.py`  
**Called by:** Java `LLMService.getLLMExample(..., type="secure")`

It expects **one argument**:
- `json_path` → path to Java-written temp JSON (e.g., `llm/temp_example_secure.json`)

### 3.2 Inputs used by the secure generator
The secure generator builds context from multiple sources:

1) **Temp JSON from Java**
- Contains at least `className`
- Often contains `objects`, `events`, `order`, `constraints`, `requires`, `ensures`, `forbidden`

2) **Sanitized structured JSON (preferred where available)**
- Looks for `llm/sanitized_rules/sanitized_rule_{fqcn}_{lang}.json`
- If language-specific is missing, falls back to English

3) **Raw CrySL rule text**
- Reads `src/main/resources/CrySLRules/<SimpleName>.crysl`
- Splits into sections (OBJECTS, EVENTS, ORDER, CONSTRAINTS, REQUIRES, ENSURES, FORBIDDEN)
- Prefers these raw sections over the JSON when present

4) **Cached explanation text**
- Reads `Output/resources/llm_cache/<safeFQCN>_English.txt` (or other language)
- Injects explanation into prompt for extra grounding

5) **Optional RAG from CrySL paper**
- Uses `tse19CrySL.pdf`
- Builds/loads FAISS index via `paper_index.py`
- Retrieves top-k relevant chunks and injects into system context

### 3.3 Dependency-aware grounding (cross-rule)
The secure generator also pulls context from dependencies:
- It reads the main rule’s `dependency` list (from sanitized JSON)
- For each dependency, it loads the dependency’s sanitized JSON
- Extracts and formats:
    - dependency constraints (what related classes require)
    - dependency ensures (what related classes guarantee)

This is intended to help code generation satisfy cross-class predicates.

### 3.4 Prompt formation
The secure prompt typically includes:
- OBJECTS / EVENTS / ORDER
- CONSTRAINTS
- REQUIRES / ENSURES
- FORBIDDEN
- Dependency constraints + dependency ensures
- Cached explanation
- Optional RAG chunks
- Strong instruction:
    - output **only Java code**
    - wrap with ```java fences
    - avoid TODO/null placeholders
    - choose strongest allowed algorithms
    - never use forbidden calls
    - align with order (typestate)

### 3.5 LLM call and output
The script calls OpenAI chat completions with:
- low temperature (~0.2)
- max tokens (~2000)
  Prints the model response to stdout. Java captures it and caches it.

---

## 4) `paper_index.py` — RAG index builder and retriever (support module)

### 4.1 What it does
- Reads text from a PDF via `pypdf`
- Chunks text into overlapping segments
- Embeds chunks using OpenAI embeddings (`text-embedding-3-small`)
- Builds a FAISS cosine-similarity index (via normalized vectors and inner product)
- Stores cache files in `rag_cache/`:
    - `vectors.npy`
    - `ids.json`
    - `chunks.json`
- On future runs, loads from cache instead of re-embedding

### 4.2 How it connects to secure generation
`llm_code_writer_secure.py` uses `build_pdf_index(...)` to:
- load/build the index
- embed a query string derived from CrySL sections
- retrieve the most relevant paper chunks
- add them as “REFERENCE MATERIAL” for the LLM

---

## 5) Bottlenecks & issues — Secure Code Generator Side (Python + integration)

This section is focused on **what currently limits correctness, speed, stability, and reproducibility** for secure code generation.

### 5.1 Correctness & “wrong input” risks

#### Issue 1 — Secure generator reads CrySL from a fixed resources folder
- It loads `src/main/resources/CrySLRules/<SimpleName>.crysl`.
- Java reads rule objects from `--rulesDir`.
- If these diverge, secure generation can be grounded on a *different version* of the rule than Java used.

**Fix direction**
- Pass the actual rule file path (from `--rulesDir`) into the Java temp JSON and have Python read that path.

#### Issue 2 — `<SimpleName>.crysl` collisions are possible
If two rules share the same simple class name (different packages), the secure generator can pick the wrong file.

**Fix direction**
- Name rule files by fully qualified name (safe encoding), or include a mapping table.

#### Issue 3 — No post-validation of generated code
Currently, the script assumes the LLM output is correct if it “looks like Java”.
There is **no check** for:
- forbidden calls appearing
- required calls missing
- compilation errors

**Fix direction**
- Add a compile check (see section 6) and/or basic static checks:
    - forbidden method name blacklist
    - ensure required types/calls exist
    - reject TODO/null placeholders

#### Issue 4 — Dependency context can be noisy or stale
The script trusts the dependency list from sanitized JSON. If that list is wrong or outdated, it injects misleading constraints/ensures.

**Fix direction**
- Ensure sanitized JSON is refreshed deterministically (hash/version)
- Consider a max dependency budget (top N most important deps)

---

### 5.2 Performance & cost bottlenecks

#### Issue 5 — Embeddings are generated one chunk at a time
`paper_index.py` calls embeddings per chunk in a loop.

**Impact**
- Slow indexing
- Higher overhead/cost

**Fix direction**
- Batch embeddings: call embeddings API with `input=[chunk1, chunk2, ...]` (in batches).

#### Issue 6 — No cache invalidation for the RAG index
Cache files are reused even if:
- the PDF changes
- chunk size/overlap changes
- embedding model changes

**Fix direction**
- Use a cache key based on:
    - PDF hash
    - chunk params
    - embedding model id
- Store cache under `rag_cache/<cache_key>/...`

#### Issue 7 — RAG retrieval is performed for every rule generation
Even when RAG adds little value for some rules, it still executes retrieval logic.

**Fix direction**
- Make RAG optional per run and/or per rule
- Add a heuristic: use RAG only when constraints/order is “complex”

---

### 5.3 Reproducibility & debugging bottlenecks

#### Issue 8 — Stale sanitized rule JSON selection is implicit
The script tries languages in order and uses the first found sanitized file. Silent fallback can hide missing/stale files.

**Fix direction**
- Always load the intended language (or explicitly log the fallback)
- Prefer using a single canonical sanitized file per rule

#### Issue 9 — Output is not guaranteed to be “code only”
The prompt requests fenced Java code, but the script prints whatever the model returns. If the model returns prose + code, Java may cache messy output.

**Fix direction**
- Add an output normalizer in Python:
    - extract ```java block; if none, fail/retry
- Or enforce full-file-only output and validate.

#### Issue 10 — Token truncation can produce incomplete code
`max_tokens` can truncate long outputs. If truncation happens, Java will still cache it.

**Fix direction**
- Detect truncation (`finish_reason == "length"`) and retry with higher limit or a “continue” prompt.

---

### 5.4 Security / safety-adjacent risks

#### Issue 11 — Explanation cache is treated as trusted context
Cached explanation text is injected into the prompt. If it contains mistakes or unexpected content, it can steer code generation incorrectly.

**Fix direction**
- Treat explanation cache as optional; prefer structured CrySL fields
- Add a short “explanation may be wrong” guard or reduce its weight in prompt

#### Issue 12 — No sanitization of prompt-embedded content beyond JSON sanitization
If any upstream strings contain weird markup, they can pollute the prompt and cause model confusion.

**Fix direction**
- Use sanitized JSON as the primary source whenever possible
- Apply minimal normalization before prompt assembly

---

## 6) “Compilable Java” quality gate (recommended)

### 6.1 Why compilation matters
If the generated code does not compile, it is objectively invalid:
- missing imports
- wrong types/method signatures
- incomplete classes/methods
- syntax errors

### 6.2 Two practical strategies

#### Strategy A (best): enforce “full Java file” in the prompt
Require the model to output:
- imports
- one public class (e.g., `public class SecureExample`)
- `public static void main(String[] args) throws Exception`
  Then compile directly.

#### Strategy B: wrap snippet into a compilable harness
If the model outputs only statements, wrap them into:
- a minimal class + `main` method
  Then compile.

### 6.3 Where to implement compilation check

#### Option 1 — Java-side compilation (recommended)
Use `javax.tools.JavaCompiler`:
- compile generated `SecureExample.java` in memory or in a temp dir
- capture diagnostics
- only cache output if compilation succeeds
- if it fails, optionally retry once with compiler errors

#### Option 2 — Python-side compilation
Call `javac` on a temp file:
- requires a JDK installed and `javac` available
- capture stderr for diagnostics
- retry with errors

### 6.4 Minimal “repair loop”
1) Generate code
2) Compile
3) If fail, send compiler errors to LLM: “Fix compilation errors; output full Java file only”
4) Compile again
5) Cache only if pass

---

## 7) Concrete “next tasks” (secure generator improvement roadmap)

### P0 (must do first)
- [ ] Use the correct CrySL source path (from `--rulesDir`) in secure generation.
- [ ] Add a compilation gate (JavaCompiler or javac) and only cache compilable output.
- [ ] Normalize outputs: extract Java fenced block; fail/retry if missing.

### P1 (high ROI)
- [ ] Batch embeddings in `paper_index.py`.
- [ ] Implement cache invalidation for `rag_cache` (keyed by PDF hash + params).
- [ ] Add truncation detection and retry if `finish_reason == "length"`.

### P2 (quality & maintainability)
- [ ] Make RAG optional per run and/or conditional per rule.
- [ ] Reduce reliance on cached explanation text; prefer structured sanitized fields.
- [ ] Add lightweight “CrySL compliance checks” (forbidden calls, required steps, placeholders).

---

## 8) File index (key files by responsibility)

### Java (pipeline)
- `DocSettings.java` — CLI + global settings
- `DocumentGeneratorMain.java` — orchestration + caching + HTML generation
- `ComposedRule.java` — doc model per rule/class

### Java (LLM interface)
- `CrySLToLLMGenerator.java` — packages rule context for LLM
- `LLMService.java` — spawns Python scripts, manages explanation cache
- `Utils.java` — sanitization + predicate mapping + topo ordering

### Java (dependency & rendering)
- `GraphSanitizer.java`, `GraphVerification.java`, `PredicateTreeGenerator.java`
- `FreeMarkerWriter.java` + `singleclass.ftl`

### Python (secure generator side)
- `llm_code_writer_secure.py` — secure code example generator
- `paper_index.py` — PDF indexing + retrieval for RAG

---

**End of TASK_2.md**
