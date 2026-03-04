# CogniCrypt_DOC_LLM
CogniCrypt_DOC_LLM generates HTML documentation for cryptographic APIs from CrySL rules.

It converts formal CrySL usage specifications into developer-facing pages (overview, call order, constraints, predicates, dependency trees, CrySL rule text), and can optionally enrich those pages with:
- LLM explanations (English, Portuguese, German, French)
- secure and insecure Java code examples

The documentation entry page is `rootpage.html` inside your configured output directory.

For a deeper architecture walkthrough, see `PROJECT_GUIDE.md`.

## What This Project Contains
- Java documentation pipeline (`src/main/java/de/upb/docgen/**`)
- FreeMarker templates for HTML rendering (`src/main/resources/FTLTemplates/**`)
- Language templates used to build natural-language rule text (`src/main/resources/Templates/**`)
- Bundled CrySL rules (`src/main/resources/CrySLRules/**`)
- Python LLM sidecar for explanation/code generation (`llm/**`)

## Prerequisites
- Java 11
- Maven
- Python 3 (required only for LLM features)

## Build
```bash
mvn clean install
```

or

```bash
mvn -DskipTests package
```

Generated JAR:
- `target/DocGen-0.0.1-SNAPSHOT.jar`
- runtime dependencies in `target/lib/` (keep this folder next to the JAR when running outside the project root)

## Quick Start
Minimal run command (only required flag is `--reportPath`):

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar --reportPath /absolute/path/to/output
```

Open:
- `/absolute/path/to/output/rootpage.html`

## CLI Usage
### Required
- `--reportPath <output_dir>`

### Optional input/template overrides
- `--rulesDir <path_to_crysl_rules>`
- `--ftlTemplatesPath <path_to_ftl_templates>`
- `--langTemplatesPath <path_to_lang_templates>`

### Optional UI/content toggles
Passing these flags hides/disables specific sections/features:
- `--booleanA` hide state machine graph
- `--booleanB` hide help button
- `--booleanC` hide dependency tree sections
- `--booleanD` hide CrySL rule section
- `--booleanE` turn off graphviz generation
- `--booleanF` copy CrySL rules into documentation output
- `--booleanG` switch graph label style

### Optional LLM toggles
- `--disable-llm-explanations`
- `--disable-llm-examples`
- `--llm=<on|off|true|false|1|0>`
- `--llm-explanations=<on|off|true|false|1|0>`
- `--llm-examples=<on|off|true|false|1|0>`
- `--llm-backend=<openai|ollama>`

## Example Commands
Disable all LLM features:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm=off
```

Use custom rule/template directories:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --rulesDir /absolute/path/to/rules \
  --ftlTemplatesPath /absolute/path/to/ftl \
  --langTemplatesPath /absolute/path/to/lang/templates
```

Use Ollama backend:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm-backend=ollama
```

## LLM Setup (Optional)
The Java pipeline invokes Python scripts in `llm/` for LLM explanations/examples.

Create and install Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### OpenAI backend
Set:

```bash
export OPENAI_API_KEY=<your_key>
```

Use:
- `--llm-backend=openai`

### Ollama backend
Run an Ollama server and set endpoint (if non-default):

```bash
export OLLAMA_URL=http://localhost:11434
```

Optional environment variables used by sidecar scripts:
- `OLLAMA_API_KEY`
- `OLLAMA_MODEL`
- `OLLAMA_EMB_MODEL`

Use:
- `--llm-backend=ollama`

### First-time run (required for LLM features)

Before enabling LLM explanations/examples, do a one-time preprocessing run so the project generates **sanitized CrySL rule JSONs** (one per `.crysl` file). These are written to `llm/sanitized_rules/` and are consumed by the Python sidecar.

1. **Run once with LLM off** (this creates `llm/sanitized_rules/*`):

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm=off
```

2. **Delete the generated output folder** (so the next run starts clean):

```bash
rm -rf /absolute/path/to/output
```

3. **Run again with LLM on** (after completing the Python + backend setup below):

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm=on
```

> Tip: you can also enable/disable explanations/examples separately with `--llm-explanations=...` and `--llm-examples=...`.

## Output and Cache Directories
Primary output is written to `--reportPath`.

Common generated folders:
- `<reportPath>/composedRules/` (one HTML page per class)
- `Output/resources/llm_cache/` (cached explanations)
- `Output/resources/code_cache/` (cached secure/insecure examples)
- `llm/sanitized_rules/` (sanitized rule JSON for LLM scripts)
- `rag_cache/` (cached embeddings/chunks for PDF retrieval)

## Notes
- If no override paths are provided, bundled resources are used from `src/main/resources/**`.
- LLM flags can overlap; later CLI args may override earlier ones.
- The project includes historical thesis context, but this README reflects current implementation behavior.
