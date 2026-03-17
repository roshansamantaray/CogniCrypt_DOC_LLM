# CogniCrypt_DOC_LLM
CogniCrypt_DOC_LLM generates HTML documentation for cryptographic APIs from CrySL rules.

It converts formal CrySL usage specifications into developer-facing pages (overview, call order, constraints, predicates, dependency trees, CrySL rule text), and can optionally enrich those pages with:
- LLM explanations (English, Portuguese, German, French)
- secure and insecure Java code examples

The documentation entry page is `rootpage.html` inside your configured output directory.

## What This Project Contains
- Java documentation pipeline (`src/main/java/de/upb/docgen/**`)
- FreeMarker templates for HTML rendering (`src/main/resources/FTLTemplates/**`)
- Language templates used to build natural-language rule text (`src/main/resources/Templates/**`)
- Bundled CrySL rules (`src/main/resources/CrySLRules/**`)
- Python LLM sidecar for explanation/code generation (`llm/**`)

## Prerequisites
- Java 21
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

## Run Consistency (IDE + CLI)
Canonical reproducible run path:

```bash
mvn clean compile
mvn -DskipTests package
java -jar target/DocGen-0.0.1-SNAPSHOT.jar --reportPath /absolute/path/to/output
```

For IntelliJ runs:
- Reload Maven project after dependency changes.
- Rebuild the project before running (`Build > Rebuild Project`).
- If startup preflight reports missing classes, rebuild first and ensure the Maven classpath is active.

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
- `--llm-backend=<openai|gateway>`

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

Use Gateway backend:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm-backend=gateway
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

Notes:
- OpenAI backend is used for explanations and code examples.
- `OPENAI_API_KEY` is required when running with `--llm-backend=openai`.

### Gateway backend (UPB AI-Gateway)
Set:

```bash
export GATEWAY_API_KEY=<your_gateway_key>
export GATEWAY_BASE_URL=https://ai-gateway.uni-paderborn.de/v1/
export GATEWAY_CHAT_MODEL=<gateway_chat_model>
export GATEWAY_EMB_MODEL=<gateway_embedding_model>
export GATEWAY_RPM=10
```

Use:
- `--llm-backend=gateway`

Discover available gateway models:

```bash
python llm/llm_writer_gateway.py --list-models
```

Notes:
- Gateway backend is used for both explanations and secure/insecure code examples.
- Example scripts are invoked internally with `--backend=<openai|gateway>` from Java; no fallback to OpenAI is performed in gateway mode.
- For gateway-backed examples, set `GATEWAY_CHAT_MODEL` and `GATEWAY_EMB_MODEL` (or pass explicit script overrides).
- If `GATEWAY_CHAT_MODEL` is unset, the gateway explanation default is `gwdg.qwen3-30b-a3b-instruct-2507`.
- Gateway requests (chat + embeddings, including examples) are throttled client-side using a shared cross-process limiter with default `GATEWAY_RPM=10` (set `GATEWAY_RPM` to override).

### First-time run (required for LLM features)

Before setting API keys, run a one-time preprocessing pass to generate **sanitized CrySL rule JSONs** (one per `.crysl` file per language). These are written to `llm/sanitized_rules/` and are consumed by the Python sidecar.

Important: sanitized JSON generation is tied to the LLM explanation flow in `DocSettings`, so it must run with `--llm=on` (or explicitly `--llm-explanations=on`).

1. **Run once without API keys, but with LLM enabled** (this generates `llm/sanitized_rules/*`):

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm=on \
  --llm-examples=off
```

2. **Delete the generated output folder** (so the next run starts clean):

```bash
rm -rf /absolute/path/to/output
```

3. **Configure your backend/API keys, then run again with LLM features as needed**:

```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/output \
  --llm=on
```

> Tip: you can enable/disable explanations/examples independently with `--llm-explanations=...` and `--llm-examples=...`.

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
