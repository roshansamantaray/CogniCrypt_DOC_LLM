# CogniCrypt_DOCC_LLM (CrySL → Documentation + LLM Explanations & Code Examples)

This repository generates a **static HTML documentation website** for cryptographic APIs from **CrySL rules** (CogniCrypt crypto-usage specifications).

It supports two “lanes”:

1. **Template-based documentation (deterministic, Java/Maven)**  
2. **LLM-assisted augmentation (optional, Python sidecar)**  
   - natural-language explanations (**English, German, French, Portuguese**)  
   - secure + insecure Java code examples  
   - optional RAG context from the included CrySL paper PDF (`tse19CrySL.pdf`)

> **Important UI note:** In the current templates, the **LLM explanation UI block is commented out** in  
> `src/main/resources/FTLTemplates/singleclass.ftl`.  
> Explanations can still be generated + cached, but they may not be visible in HTML until you **uncomment** that FreeMarker section (remove the surrounding `<#-- ... -->` block).

> **CLI note (source of truth):** CLI flags evolve. If something doesn’t work as written here, check the flag parsing in  
> `src/main/java/de/upb/docgen/DocSettings.java` (method `parseSettingsFromCLI`) for the exact supported options.

---

## Table of contents
- [What this project produces](#what-this-project-produces)
- [Quick start](#quick-start)
- [Build (Java/Maven)](#build-javamaven)
- [Run the generator](#run-the-generator)
  - [Required CLI arguments](#required-cli-arguments)
  - [Optional feature flags](#optional-feature-flags)
  - [LLM flags](#llm-flags)
  - [Common workflows](#common-workflows)
- [LLM setup (Python)](#llm-setup-python)
  - [OpenAI backend](#openai-backend)
  - [Ollama backend](#ollama-backend)
  - [RAG index and cache](#rag-index-and-cache)
  - [LLM caching](#llm-caching)
- [How the system works (architecture)](#how-the-system-works-architecture)
- [CrySL explained (easy but detailed)](#crysl-explained-easy-but-detailed)
- [Repo layout](#repo-layout)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [Contributing ideas](#contributing-ideas)

---

## What this project produces

The generator outputs a **static HTML website**. The entry point is:

- `rootpage.html` inside the chosen output folder (`--reportPath`).

There are example artifacts already in the repository:
- `latest_doc.zip`
- `interview_study/generated_doc_and_code_example.zip`

---

## Quick start

### Requirements
- **Java 11**
- **Maven**
- **Python 3.x** (only for LLM features)
- Optional: **Ollama** (only if you use the Ollama backend)

---

## Build (Java/Maven)

From the repo root:

```bash
mvn clean package
```

This produces (by default):
- `target/DocGen-0.0.1-SNAPSHOT.jar`
- `target/lib/` (dependency jars referenced by the runnable jar)

---

## Run the generator

### Required CLI arguments

The documentation generator requires **4 mandatory arguments**:

- `--rulesDir` — absolute path to CrySL rules directory
- `--FTLtemplatesPath` — absolute path to FreeMarker page templates (`FTLTemplates/`)
- `--LANGtemplatesPath` — absolute path to snippet templates (`Templates/`)
- `--reportPath` — absolute path to output folder

Example (Linux/macOS):

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --rulesDir "/ABS/PATH/to/src/main/resources/CrySLRules" \
  --FTLtemplatesPath "/ABS/PATH/to/src/main/resources/FTLTemplates" \
  --LANGtemplatesPath "/ABS/PATH/to/src/main/resources/Templates" \
  --reportPath "/ABS/PATH/to/Output"
```

Then open:

- `/ABS/PATH/to/Output/rootpage.html`

> Tip: Use **absolute** paths. The CLI parser expects absolute locations.

### Serving the generated HTML (optional)
If your browser blocks some local scripts when opening `file://...`, serve the output folder:

```bash
cd /ABS/PATH/to/Output
python3 -m http.server 8000
```

Then open `http://localhost:8000/rootpage.html`.

---

### Optional feature flags

By default, all sections/features are enabled. These flags **disable/hide** parts of the output:

- `--booleanA` — hide state machine graph
- `--booleanB` — hide help
- `--booleanC` — hide dependency trees
- `--booleanD` — hide CrySL rule section
- `--booleanE` — disable state-machine rendering/output (graph section)
- `--booleanF` — copy CrySL rules into the documentation output folder
- `--booleanG` — show fully qualified method names in the state machine graph

Example:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  ...mandatory args... \
  --booleanA --booleanC --booleanD
```

> Note: This project uses **client-side rendering** (d3-graphviz scripts embedded in the HTML). You typically do **not** need a system Graphviz installation just to view the docs.

---

### LLM flags

LLM functionality can be controlled as follows:

#### Master switch
- `--llm=on|off`  
  Applies to both explanations and examples unless overridden later by a more specific flag.

Examples:
```bash
# Turn off all LLM features
--llm=off

# Turn on all LLM features
--llm=on
```

#### Specific toggles
- `--llm-explanations=on|off`
- `--llm-examples=on|off`

#### Backend selection
- `--llm-backend=openai|ollama`

#### Convenience “disable” switches
- `--disable-llm-explanations`
- `--disable-llm-examples`

Example: generate docs + code examples, but no explanations:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  ...mandatory args... \
  --llm-backend=openai \
  --llm-explanations=off \
  --llm-examples=on
```

---

### Common workflows

#### 1) Docs only (no LLM)
```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  ...mandatory args... \
  --llm=off
```

#### 2) Docs + code examples (OpenAI)
```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  ...mandatory args... \
  --llm=on \
  --llm-backend=openai \
  --llm-explanations=off \
  --llm-examples=on
```

#### 3) Docs + explanations + examples (Ollama)
```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  ...mandatory args... \
  --llm=on \
  --llm-backend=ollama \
  --llm-explanations=on \
  --llm-examples=on
```

---

## LLM setup (Python)

The Java generator calls Python scripts under `llm/` and prefers a local virtualenv:

- `llm/.venv/bin/python` (Linux/macOS)
- `llm/.venv/Scripts/python.exe` (Windows)

### Create a virtual environment
From repo root:

```bash
cd llm
python3 -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\activate       # Windows PowerShell
pip install -r requirements.txt
```

---

### OpenAI backend

Create `llm/.env`:

```env
OPENAI_API_KEY="YOUR_KEY_HERE"
```

Run Java with:

```bash
--llm-backend=openai
```

---

### Ollama backend

For Ollama-based text generation:

```env
OLLAMA_MODEL="llama3:latest"
# Optional: embedding model used by RAG indexing
OLLAMA_EMB_MODEL="nomic-embed-text"
# Optional: endpoint + key (often empty key for local)
OLLAMA_URL="http://localhost:11434"
OLLAMA_API_KEY=""
```

Run Java with:

```bash
--llm-backend=ollama
```

---

### RAG index and cache

The project includes `tse19CrySL.pdf` (CrySL paper).  
The Python pipeline can retrieve relevant snippets from the paper to ground explanations/prompts.

- Cache directory: `rag_cache/`
  - `vectors.npy`
  - `chunks.json`
  - `ids.json`

This cache avoids recomputing embeddings on every run.

---

### LLM caching

The generator writes caches so subsequent runs do not re-call the LLM unnecessarily.

All cache paths are relative to your chosen output folder (`--reportPath`), i.e. under:

- `<reportPath>/resources/llm_cache/` (explanations)
  - files like: `<FQCN>_<LANG>.txt`
- `<reportPath>/resources/code_cache/` (examples)
  - files like: `<FQCN>_secure.txt` and `<FQCN>_insecure.txt`

Behavior:
- If LLM is enabled and a cache exists, it reuses it.
- If LLM is disabled, it still **reuses cached outputs if present**; otherwise it writes placeholders.

---

## How the system works (architecture)

### Java: deterministic documentation generation
1. Reads CrySL rules from `--rulesDir`
2. Parses them into internal objects (e.g., `ComposedRule`)
3. Builds:
   - **ORDER** state machine graph (typestate usage automaton)
   - constraint/predicate representations
   - dependency ordering across classes (ENSURES ↔ REQUIRES relationships)
4. Renders a static HTML site using:
   - page templates: `src/main/resources/FTLTemplates/*.ftl`
   - snippet templates: `src/main/resources/Templates/*`
5. Writes output HTML pages to `--reportPath`

### Java ↔ Python: LLM augmentation
When enabled:
- Java writes structured JSON “rule context” files under `llm/temp_rules/` and `llm/sanitized_rules/`
- Java calls Python scripts via `ProcessBuilder`:
  - `llm/llm_writer.py` / `llm/llm_writer_ollama.py` for explanations
  - `llm/llm_code_writer_secure.py` and `llm/llm_code_writer_insecure.py` for examples
- Results are cached and injected into the FreeMarker model

---

## CrySL explained (easy but detailed)

CrySL (“Crypto Specification Language”) is a **rule language** for describing **correct and secure usage** of cryptographic APIs.

### Why CrySL exists
Crypto libraries (e.g., Java JCA) are powerful but easy to misuse:
- wrong call order (missing init/finalization)
- insecure algorithm/mode/padding choices
- weak key sizes
- missing required preconditions

CrySL lets crypto experts write **machine-checkable usage specifications** that tools can use for:
- static analysis (misuse detection)
- documentation generation (this project)
- example generation
- and more

### Core idea: object usage = call sequence + values
CrySL models usage of an object as a **sequence of method calls** (EVENTS) plus the **values** passed/bound.

A usage is correct if it satisfies:
1. Allowed call sequence (**ORDER**)  
2. Allowed parameter/value choices (**CONSTRAINTS**)  
3. Must-not-call methods (**FORBIDDEN**)  
4. Cross-object prerequisites (**REQUIRES**)  
5. If satisfied, it produces guarantees (**ENSURES**) other rules can rely on

### ORDER = regular expression over events (typestate automaton)
`ORDER` is written like a regex (sequence, alternatives, optional, repetition).  
Tools typically compile this into a **usage automaton** (NFA/typestate).  
This project visualizes that automaton as the **state machine graph** shown in the docs.

### FORBIDDEN = “never call these”
`FORBIDDEN` lists methods that should **not** be called (always insecure or wrong in that context).  
Some rules also attach a recommended alternative (useful for better error messages).

### “after <EVENT>” = emit guarantees earlier
Some rules can declare that a predicate becomes true **immediately after a specific event**, rather than only at the end of a valid trace.  
This is useful when an intermediate call already establishes a guarantee needed elsewhere.

### Rule anatomy (sections)
- `SPEC` — which class this rule specifies
- `OBJECTS` — variables (objects/strings/ints/arrays) used in the rule
- `EVENTS` — relevant API calls, with labels and variable bindings
- `ORDER` — regex-like language over events (typestate)
- `CONSTRAINTS` — value/data-flow constraints (safe sets, ranges, implications)
- `FORBIDDEN` — always-bad methods
- `REQUIRES` — predicates that must already hold
- `ENSURES` — predicates that become true after correct usage
- `NEGATES` — predicates invalidated after a certain event (lifetime modeling)

### Predicates (the glue across classes)
Predicates connect rules. Example intuition:
- A correct `KeyGenerator` run may ENSURE `generatedKey[key, algo]`
- `Cipher.init(key, ...)` may REQUIRE that predicate

This lets tools catch “you used a key, but it’s not proven to be generated securely”.

---

## Repo layout

```
CogniCrypt_DOCC_LLM/
├── pom.xml                          # Java build (Java 11)
├── src/main/java/de/upb/docgen/...   # core generator + LLM integration hooks
├── src/main/resources/
│   ├── CrySLRules/                  # .crysl input rules
│   ├── FTLTemplates/                # FreeMarker page templates
│   └── Templates/                   # snippet templates + symbol.properties
├── llm/                             # Python LLM pipeline (OpenAI/Ollama)
│   ├── llm_writer*.py               # explanations
│   ├── llm_code_writer_*.py         # secure/insecure examples
│   ├── paper_index*.py              # RAG indexing for the CrySL paper
│   ├── temp_rules/                  # intermediate JSON context
│   └── sanitized_rules/             # sanitized JSON context
├── rag_cache/                       # persisted embeddings/chunks
├── tse19CrySL.pdf                   # CrySL paper used by RAG
├── latest_doc.zip                   # example generated docs output
└── interview_study/...              # snapshot output for a study
```

---

## Troubleshooting

### Code examples lose indentation
The Java post-processor removes markdown fences and (currently) strips leading whitespace.  
If you want pretty Java formatting, avoid left-stripping every line and only remove the ``` fences.

### LLM enabled but nothing appears in HTML
Check:
1. Are outputs written to `<reportPath>/resources/*_cache/`?
2. Is the LLM explanation block still commented out?
   - Edit `src/main/resources/FTLTemplates/singleclass.ftl` and remove the surrounding `<#-- ... -->` for that section.
3. Did you pass `--llm=on` / `--llm-examples=on` / `--llm-explanations=on`?

### Python not found
The Java side prefers `llm/.venv/...`. Ensure:
- `.venv` exists
- requirements installed
- you can run the scripts manually inside `llm/`

---

## Security notes
- Never commit real API keys into `.env`
- Treat any shared key as compromised and rotate it
- Keep `.env` local and protected

---

## Contributing ideas
- Preserve indentation and imports in generated code examples
- Improve structured prompting from CrySL sections (OBJECTS, REQUIRES, ENSURES)
- Add automated validation for generated snippets (compile + simple policy checks)
- Provide a template toggle to show/hide LLM explanation sections without editing `.ftl`
