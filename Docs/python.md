# Python Pipeline Deep Dive

## 1. Purpose and Scope
This document explains the **Python side** of this project end-to-end and how it connects to the Java pipeline.

The Python code does two main jobs:
1. Generate multilingual LLM explanations for each CrySL rule.
2. Generate secure and insecure Java code examples.

The Java pipeline is still the main orchestrator. Python acts as a sidecar process that Java calls through subprocesses.

---

## 2. Where Python Fits in the Full System
The overall flow is:

1. Java reads CrySL rules and builds `ComposedRule` data.
2. Java optionally calls Python for LLM outputs.
3. Python prints generated text/code to stdout.
4. Java captures a merged stdout+stderr stream (`redirectErrorStream(true)`), caches results, and injects them into HTML templates.

So Python handles **content generation**, while Java handles **orchestration and rendering**.

---

## 3. Python File Map (What Each File Does)

### Core scripts (entrypoints)
- `llm/llm_writer.py`: explanation generator using OpenAI backend.
- `llm/llm_writer_gateway.py`: explanation generator using gateway backend.
- `llm/llm_code_writer_secure.py`: secure Java example generator with compile-and-repair loop.
- `llm/llm_code_writer_insecure.py`: insecure Java example generator (no compile gate).
- `llm/paper_index.py`: OpenAI PDF embedding index builder/cache loader.
- `llm/paper_index_gateway.py`: gateway PDF embedding index builder/cache loader.

### Shared utilities
- `llm/utils/writer_core.py`: shared explanation pipeline and strict explanation prompt.
- `llm/utils/llm_utils.py`: sanitized-file access, dependency extraction/formatting, CrySL parsing helpers.
- `llm/utils/rag_index_common.py`: FAISS index abstraction, PDF chunking, cache read/write.
- `llm/utils/gateway_rate_limit.py`: cross-process request throttling for gateway mode.
- `llm/utils/__init__.py`: marks `utils` as an importable package (`from utils...`) and keeps package-level API intentionally minimal.

### Runtime data files
- `llm/temp_example_secure.json`: last secure payload written by Java.
- `llm/temp_example_insecure.json`: last insecure payload written by Java.
- `llm/temp_rules/`: per-rule, per-language JSON payloads for explanations.
- `llm/sanitized_rules/`: cleaned JSON files used by Python for dependency context.

### Supporting Python tooling
- `scripts/delete_disabled_code_cache_files.py`: removes placeholder cache files (code cache and optional explanation cache).
- `llm/tests/test_delete_disabled_code_cache_files.py`: tests cache cleanup script behavior.

---

## 4. Java -> Python Boundary (Exact Handoff)

### 4.1 Java classes involved
- `DocumentGeneratorMain`
- `CrySLToLLMGenerator`
- `LLMService`
- `CachePathResolver`
- `Utils.sanitizeRuleFileSecure`

### 4.2 How Java calls Python for explanations
From `LLMService.getLLMExplanation(...)`, Java:
1. Chooses script:
   - `llm/llm_writer.py` for `openai`
   - `llm/llm_writer_gateway.py` for `gateway`
2. Builds JSON payload from CrySL + composed data.
3. Writes temp input to `llm/temp_rules/temp_rule_<class>_<lang>.json` (if missing).
4. Sanitizes into `llm/sanitized_rules/sanitized_rule_<class>_<lang>.json` (if missing).
5. Checks explanation cache at `<reportPath>/resources/llm_cache/<class>_<lang>.txt`.
6. If cache missing, runs Python process with args:
   - `<className>` `<language>`
7. Waits up to 60 seconds.
8. Captures merged stdout+stderr as explanation text.

### 4.3 How Java calls Python for code examples
From `LLMService.getLLMExample(...)`, Java:
1. Adds `exampleType` (`secure`/`insecure`) to payload.
2. Writes payload to:
   - `llm/temp_example_secure.json` or
   - `llm/temp_example_insecure.json`
3. Calls script:
   - `llm/llm_code_writer_secure.py` or
   - `llm/llm_code_writer_insecure.py`
4. Passes CLI args:
   - JSON path
   - `--backend <openai|gateway>`
   - `--rules-dir <absolute src/main/resources/CrySLRules path>`
5. For secure writer only, also passes:
   - `--compile-classpath <computed Java classpath>`
   - `--java-release <JVM spec version>`
   - env `JAVAC_BIN`
6. Waits up to 60 seconds and captures merged stdout+stderr.

### 4.4 Important integration notes
- Java prefers project virtualenv Python (`.venv/bin/python` or `.venv/Scripts/python.exe`) and falls back to `python3`/`python`.
- Java merges Python stderr into stdout before reading process output, so warnings/debug logs can appear in captured text.
- Java then uses that merged output directly for LLM sections.
- Java caches both explanations and examples under `reportPath/resources`.
- Java language support is currently declared in two places (`CrySLToLLMGenerator` and `DocumentGeneratorMain`), so list updates must stay synchronized.

---

## 5. Data Contracts (Payloads and Fields)

### 5.1 Explanation payload (Java-generated)
Main fields passed through temp/sanitized rule files:
- `className`
- `objects`
- `events`
- `order`
- `constraints`
- `requires`
- `ensures`
- `forbidden`
- `dependency`
- `explanationLanguage`

Sanitizer (`Utils.sanitizeRuleFileSecure`) strips HTML/control chars and normalizes arrays.

### 5.2 Example payloads (`temp_example_secure.json`, `temp_example_insecure.json`)
These include rule context such as:
- `className`
- `objects`
- `events`
- `order`
- `constraints`
- `requires`
- `ensures`
- `forbidden`
- `exampleType`

Observed behavior from current files:
- Payload strings may include HTML tags/tooltips because they come from composed documentation text.
- Secure writer mostly rebuilds prompt context from raw `.crysl` rule text and uses payload as fallback.
- Insecure writer uses payload fields directly in prompt text.

---

## 6. Explanation Pipeline (OpenAI + Gateway)

### 6.1 Entrypoints
- OpenAI: `llm_writer.py`
- Gateway: `llm_writer_gateway.py`

Both are thin wrappers around shared logic in `utils/writer_core.py`.

### 6.2 Shared pipeline in `writer_core.py`
`run_writer_main(...)` does:
1. Load `.env`.
2. Parse CLI:
   - `class_name_full` (FQCN)
   - `language`
   - optional model/pdf/k/embedding model
3. Resolve `.crysl` file by simple class name in `src/main/resources/CrySLRules`.
4. Initialize LLM client.
5. Optionally build/load PDF index.
6. Call `process_rule_fn(...)` backend wrapper.

`process_rule_core(...)` then:
1. Read raw `.crysl` text.
2. Parse sections (SPEC/OBJECTS/EVENTS/ORDER/CONSTRAINTS/REQUIRES/ENSURES/FORBIDDEN).
3. Build dependency context from sanitized files:
   - dependency constraints
   - dependency ensures
4. Load primary sanitized summary.
5. Build optional RAG block.
6. Build strict explanation prompt (`build_explanation_prompt`).
7. Call backend-specific `generate_explanation_fn`.
8. Clean output (remove stray fences) and print.

### 6.3 Prompt style and constraints
`build_explanation_prompt(...)` uses a strict structure:
- forces exact section headings (Overview, Correct Usage, etc.)
- bans CrySL notation/event labels in final prose
- asks for plain, practical language
- injects dependencies and sanitized context
- optionally enforces UTF-8 note

This keeps output consistent and easier to render in documentation.

### 6.4 RAG behavior in explanation scripts
Both writer variants use the same retrieval idea:
1. Build query from CrySL sections + “syntax boost” text.
2. Embed query.
3. Search FAISS index.
4. Build hidden `rag_block` snippets tagged `[C1]`, `[C2]`, ...
5. Pass as system reference text (not for direct citation).

If index is unavailable or PDF missing, explanations continue without RAG.

### 6.5 Backend differences
OpenAI (`llm_writer.py`):
- uses `OPENAI_API_KEY`
- default model `gpt-4o-mini`
- default embedding model `text-embedding-3-small`

Gateway (`llm_writer_gateway.py`):
- uses `GATEWAY_API_KEY`, optional `GATEWAY_BASE_URL`
- default chat model `gwdg.qwen3-30b-a3b-instruct-2507`
- embedding model comes from CLI/env (`GATEWAY_EMB_MODEL`) with backend-specific behavior:
  - secure writer gateway path: required (fails fast if missing and no `--emb-model`)
  - explanation gateway path: if missing/invalid, RAG can fail and execution can continue without RAG
- throttles `embeddings` and `chat.completions`
- adds `--list-models` utility mode

---

## 7. Secure Code Generation Pipeline (`llm_code_writer_secure.py`)

### 7.1 Goal
Produce one secure Java file that follows CrySL contract, then ensure it compiles.

### 7.2 High-level flow
1. Parse args (`json_path`, backend, model, pdf, emb-model, rules-dir, compile-classpath, java-release).
2. Load JSON payload and class name.
3. Initialize client + resolve models.
4. Build authoritative contract from `.crysl` sections (fallback to payload fields if section missing).
5. Shape contract to bounded size (`shape_crysl_contract`).
6. Load dependency constraints/ensures from sanitized rules.
7. Load or build CrySL primer (`load_crysl_primer`).
8. Build large secure prompt (`build_secure_prompt`).
9. Generate code (temperature 0.0).
10. Run deterministic post-processing:
   - normalize class name to `SecureUsageExample`
   - patch imports from a whitelist
   - normalize known API mistakes
11. Compile gate (`javac`) and optional iterative repair loop.
12. Print final fenced Java code.

### 7.3 Contract shaping and dependency limits
Secure writer intentionally caps prompt size:
- max dependencies
- max items per dependency
- max characters per dependency section
- max contract characters
- per-section line and character caps

This reduces prompt bloat and makes output more stable.

### 7.4 Primer strategy
`load_crysl_primer(...)`:
- starts from a fixed fallback CrySL primer scaffold
- optionally enriches with non-rule-specific PDF snippets
- filters out noisy snippets (tooling/research boilerplate)
- caches primer by backend+embedding model under `rag_cache/`

Important: secure writer follows a "semantic primer + authoritative contract" model.

### 7.5 Compile gate and repair loop
- Uses `javac` (`JAVAC_BIN` or PATH).
- Compiles temporary `SecureUsageExample.java`.
- If compilation fails, sends compiler output back to model for repair.
- Repeats up to `CRYSLDOC_MAX_REPAIRS` (default `7`).
- If still failing, raises hard error and exits non-zero.

Runtime controls:
- `CRYSLDOC_COMPILE_CHECK` (default enabled)
- `CRYSLDOC_COMPILE_STRICT`
- `CRYSLDOC_JAVAC_REQUIRED`
- `CRYSLDOC_MAX_REPAIRS` (default `7`)

### 7.6 Secure prompt behavior
The secure prompt is strict and includes guardrails like:
- follow CrySL ORDER/CONSTRAINTS/REQUIRES/FORBIDDEN exactly
- no hardcoded secrets
- no secret logging
- one public class only
- explicit import correctness
- handle errors in `main` (no `throws Exception`)

This prompt strongly steers output to compile-safe, security-safe examples.

---

## 8. Insecure Code Generation Pipeline (`llm_code_writer_insecure.py`)

### 8.1 Goal
Generate a realistic Java example that intentionally violates CrySL secure usage.

### 8.2 Flow
1. Parse args (json path, backend, optional model).
2. Load JSON payload and verify `exampleType` is insecure.
3. Build prompt that explicitly asks for misuse patterns.
4. Call model (temperature 0.3).
5. Print raw generated code.

### 8.3 Differences from secure writer
- no CrySL file re-parse
- no compile gate
- no repair loop
- no import auto-fix
- faster, lighter path by design

---

## 9. PDF Indexing and Retrieval Layer

### 9.1 OpenAI indexer (`paper_index.py`)
- builds embeddings from PDF chunks via OpenAI embeddings API
- builds FAISS cosine index
- caches vectors/ids/chunks with provider/model/pdf-aware key

### 9.2 Gateway indexer (`paper_index_gateway.py`)
- same structure, but uses gateway client and throttling

### 9.3 Shared index infra (`rag_index_common.py`)
Key pieces:
- `DocChunk`: chunk id + text
- `EmbeddingIndex`: FAISS wrapper with `build` and `search`
- `_extract_pdf_text`: best-effort extraction using `pypdf`
- `_chunk_text`: paragraph chunking with overlap
- `get_cache_paths`: provider/model/pdf signature-based cache bucket
- `load_cached_index`: integrity-checked cache loader
- `save_cached_index`: canonical cache writer

This layer keeps retrieval backend-agnostic and deterministic.

---

## 10. Gateway Throttling (`gateway_rate_limit.py`)
This utility enforces request-per-minute limits across processes.

How it works:
1. Resolve RPM from `GATEWAY_RPM` (default 10).
2. Use lock file (`.lock`) for cross-process mutual exclusion.
3. Maintain sliding-window timestamps in JSON state file.
4. If quota reached, sleep until next slot.

State files:
- `llm/.gateway_rate_limit_state.json`
- `llm/.gateway_rate_limit_state.lock`

Used by:
- `llm_writer_gateway.py`
- `paper_index_gateway.py`
- `llm_code_writer_insecure.py` (gateway mode)
- `llm_code_writer_secure.py` (gateway mode)

Implementation details that matter in practice:
- `DEFAULT_GATEWAY_RPM` is `10`; `GATEWAY_RPM` values that are empty, non-integer, or `<= 0` fall back to `10`.
- Locking is OS-specific:
  - Windows: `msvcrt.locking(...)`
  - POSIX (Linux/macOS): `fcntl.flock(...)`
- The limiter writes timestamps with temp-file replacement (`.tmp` -> real file) to reduce corruption risk during concurrent writes.
- State is shared in `llm/.gateway_rate_limit_state.json`, so separate scripts/processes coordinate against one global gateway budget.
- When limit is hit, sleep events are logged to stderr with operation labels like `embeddings` or `chat.completions`.

### 10.1 Utility Modules Deep Dive

#### 10.1.1 Utility execution map

| Utility file | Direct callers | Why it is critical |
|---|---|---|
| `llm/utils/writer_core.py` | `llm_writer.py`, `llm_writer_gateway.py` | Central orchestrator for explanation CLI flow and shared prompt contract. |
| `llm/utils/llm_utils.py` | `llm/utils/writer_core.py` | Builds dependency context and parses CrySL sections for explanation writers; secure code writer currently reimplements parallel helpers locally. |
| `llm/utils/rag_index_common.py` | `paper_index.py`, `paper_index_gateway.py` | Defines chunk/index/cache contract used by both OpenAI and gateway RAG. |
| `llm/utils/gateway_rate_limit.py` | gateway writer/index/code scripts | Prevents gateway overrun by enforcing a cross-process RPM window. |
| `llm/utils/__init__.py` | Python import system | Ensures `utils.*` imports resolve consistently across entrypoint scripts. |

#### 10.1.2 `writer_core.py`: the shared explanation control plane

What it does:
- Defines `WriterCLIConfig`, which lets each backend inject provider-specific defaults (`model`, embedding model, env-var override names) while keeping one shared CLI shape.
- Builds one strict explanation prompt (`build_explanation_prompt`) and one common system-message structure (`build_system_messages`) so OpenAI and gateway produce similarly structured docs.

How control flows:
1. `run_writer_main(...)` loads `.env`, resolves defaults, parses CLI, and resolves the `.crysl` file from the simple class name.
2. It builds optional RAG index/chunks (if PDF exists), but degrades safely to non-RAG on failures.
3. It calls backend `process_rule_fn(...)`.
4. `process_rule_core(...)` parses CrySL, pulls dependency context/sanitized summaries from `llm_utils.py`, optionally adds RAG context, calls backend completion callback, cleans output, and prints final text.

Why this design matters:
- Provider differences are injected as callbacks, so business logic stays in one place.
- Prompt contract drift is reduced because there is one central prompt builder.

#### 10.1.3 `llm_utils.py`: rule parsing and dependency context builder

What it does:
- Defines the sanitized-rule path contract via `rule_path(...)`.
- Reads JSON safely with warning/error logs (`load_json`).
- Parses raw CrySL into canonical sections (`crysl_to_json_lines`).
- Fills missing rule sections with defaults (`validate_and_fill`).
- Collects dependency constraints (`collect_dependency_constraints`) and dependency ENSURES (`collect_dependency_ensures`, depth-limited and cycle-safe).
- Formats dependency blocks deterministically for prompt insertion.

Important behavioral details:
- Constraint collection is direct-dependency oriented.
- ENSURES collection can recurse with depth control.
- `format_sanitized_rule_for_prompt(...)` excludes `dependency` from the summary body and focuses on fields that help language generation.
- `llm_code_writer_secure.py` does not import this module; it carries local helper implementations with similar names and slightly different signatures.

#### 10.1.4 `rag_index_common.py`: shared retrieval contract

What it does:
- `DocChunk` carries stable `id` + `text`.
- `EmbeddingIndex` wraps FAISS cosine retrieval, validates dimensions, normalizes vectors, and supports empty-index states.
- `_extract_pdf_text` and `_chunk_text` define provider-neutral document preprocessing.
- Cache paths are built by `get_cache_paths(...)` using provider + embedding model + PDF absolute path + PDF size/mtime signature hashed into a bucket key.
- `load_cached_index(...)` validates structural integrity before reuse.
- `save_cached_index(...)` persists the canonical triplet (`vectors.npy`, `ids.json`, `chunks.json`).

Why this is important:
- OpenAI and gateway indexers stay behaviorally aligned because they share this module.
- Cache integrity checks avoid silently using malformed retrieval artifacts.

#### 10.1.5 `gateway_rate_limit.py`: cross-process throttle implementation

What it does:
- Maintains a sliding 60-second timestamp window.
- Grants a new request slot only if timestamps in-window are below configured RPM.
- Uses filesystem locking so multiple Python processes coordinate correctly.

Why it matters:
- Without this shared limiter, concurrent gateway scripts can exceed provider limits and fail unpredictably.

#### 10.1.6 `utils/__init__.py`: package boundary

What it does:
- Contains only a module docstring, but still has architectural value:
  - Marks `llm/utils` as a package.
  - Keeps imports explicit (`from utils.writer_core import ...`) rather than relying on package-level re-exports.

Why this matters:
- Import behavior is predictable and avoids hidden coupling through wildcard package exports.

---

## 11. Caching and Filesystem Layout (Python Perspective)

### 11.1 Rule payload and sanitized caches
- `llm/temp_rules/temp_rule_<class>_<lang>.json`
- `llm/sanitized_rules/sanitized_rule_<class>_<lang>.json`

### 11.2 Example payload files
- `llm/temp_example_secure.json`
- `llm/temp_example_insecure.json`

### 11.3 Report-scoped output caches (managed by Java, consumed/produced with Python)
- `<reportPath>/resources/llm_cache/*.txt`
- `<reportPath>/resources/code_cache/*.txt`

### 11.4 Retrieval caches
- `rag_cache/<provider>__<model>__<hash>/vectors.npy`
- `rag_cache/<provider>__<model>__<hash>/ids.json`
- `rag_cache/<provider>__<model>__<hash>/chunks.json`
- `rag_cache/crysl_primer_<backend>_<model>.txt`

---

## 12. End-to-End Flow: Explanation Path
```text
Java(DocumentGeneratorMain)
  -> CrySLToLLMGenerator.generateExplanations
    -> LLMService.getLLMExplanation
      -> write temp_rule JSON
      -> sanitize to sanitized_rule JSON (if missing)
      -> check reportPath llm_cache
      -> run llm_writer.py or llm_writer_gateway.py
         -> writer_core.run_writer_main/process_rule_core
            -> parse .crysl + deps + optional RAG
            -> call chat model
            -> print explanation
      -> Java captures merged stdout+stderr
      -> first pass: write/read per-language llm_cache files
      -> second pass: reload cache files and overwrite composedRule.llmExplanation map
  -> FreeMarker renders explanation into singleclass.ftl
```

---

## 13. End-to-End Flow: Code Example Path
```text
Java(DocumentGeneratorMain)
  -> CrySLToLLMGenerator.generateExample
    -> LLMService.getLLMExample(type=secure/insecure)
      -> write temp_example_<type>.json
      -> run llm_code_writer_<type>.py
         secure:
           -> parse crysl contract + deps + primer
           -> call model
           -> post-process + compile gate + repair loop
           -> print fenced Java
         insecure:
           -> prompt directly from payload
           -> call model
           -> print Java
      -> Java captures merged stdout+stderr
      -> Java cleans fences (for template embedding)
      -> Java writes reportPath code_cache files
  -> FreeMarker renders secure/insecure blocks in singleclass.ftl
```

---

## 14. Environment Variables and Backend Configuration

### OpenAI path
- `OPENAI_API_KEY`

### Gateway path
- `GATEWAY_API_KEY`
- `GATEWAY_BASE_URL` (optional; default provided)
- `GATEWAY_CHAT_MODEL` (optional default)
- `GATEWAY_EMB_MODEL`
  - required for secure writer in gateway mode unless `--emb-model` is passed
  - also used by gateway explanation RAG path (missing/invalid values can disable/derail RAG while chat path may still run)
- `GATEWAY_RPM` (optional; default 10)

Also relevant for secure compile path:
- `JAVAC_BIN`
- `CRYSLDOC_COMPILE_CHECK`
- `CRYSLDOC_COMPILE_STRICT`
- `CRYSLDOC_JAVAC_REQUIRED`
- `CRYSLDOC_MAX_REPAIRS`

### Python package requirements
From `requirements.txt`, core runtime packages are:
- `numpy`
- `requests`
- `python-dotenv`
- `pypdf`
- `openai`
- `faiss-cpu`

Test dependency:
- `pytest`

Practical note:
- LLM scripts expect Python 3 and normally run inside project `.venv`.
- Without FAISS-related packages, RAG index building paths can fail and then degrade to non-RAG behavior.

---

## 15. Error Handling and Failure Behavior

### Explanation scripts
- Missing API keys/model config -> explicit errors (often non-zero exit at startup/client init).
- Some per-rule generation failures are caught in shared flow and may return no explanation text without forcing a non-zero process exit.
- Missing `.crysl` file -> prints error and returns.
- RAG/index failures -> warning; continues without RAG.
- Java side wraps failures as IO errors and may store placeholder/fallback text.

### Secure code script
- Missing className/payload -> returns `None` and exits 1.
- Backend/model config error -> returns `None` and exits 1.
- Compile failures after max repairs -> raises runtime error (non-zero exit).
- Java records failures as placeholder text and adds to failure report.

### Insecure code script
- Wrong `exampleType` -> exits non-zero.
- Backend errors -> exits non-zero.

### Java-side process guard
- 60-second timeout per Python subprocess call.
- Non-zero exit leads to IO exception on Java side.
- Java reads merged stdout+stderr (`redirectErrorStream(true)`), so stderr logs can pollute captured text/code output.

### Cache cleanup utility behavior
`scripts/delete_disabled_code_cache_files.py` supports:
- deriving cache paths from `--report-path`
- overriding with `--cache-dir` and `--llm-cache-dir`
- optional deletion of `// cache-kept example` entries via `--also-delete-cache-kept`
- optional explanation-placeholder cleanup with `--also-delete-disabled-explanations`
- dry-run mode

---

## 16. Final Result Produced by the Python Side
When everything succeeds, Python contributes:
1. Clean multilingual explanations for each class.
2. Secure Java example code (compile-validated path).
3. Insecure Java example code (misuse demonstration).
4. Cached retrieval artifacts for faster future runs.

These outputs are not a final UI by themselves. Java ingests them and renders final HTML pages.

---

## 17. Current Technical Risks and Fragile Spots (Python + Boundary)

### Risk 1: Cache staleness is likely
- Explanation and code caches are reused aggressively.
- Existing files can block regeneration unless placeholder conditions are met.
- Backend/model/prompt changes may not invalidate old cache automatically.

### Risk 2: `temp_rules` and `sanitized_rules` are write-once in Java path
- Java only creates those files if missing.
- If upstream rule content changes, old sanitized JSON can remain.

### Risk 3: Custom `--rulesDir` on Java side is not fully mirrored in Python explanation path
- Explanation writers resolve `.crysl` from default `src/main/resources/CrySLRules` by script constants.
- This can drift from Java’s active rule source when custom rules directory is used.

### Risk 4: Secure compile loop increases quality but also latency/failure surface
- Multiple repair iterations can be slow.
- Missing `javac` or strict compile settings can force failures.

### Risk 5: Insecure writer has no compile validation
- Output may be syntactically plausible but not guaranteed to compile.

### Risk 6: Gateway throughput depends on shared lock/state files
- If state files become corrupted or lock behavior is disrupted, pacing can degrade.

### Risk 7: Payload text may contain HTML-like markup
- Insecure writer prompt uses payload directly, so noisy markup can leak into prompt context.

### Risk 8: Large secure prompts can become unstable
- Strong guardrails are good, but very long prompts can still cause model variability or truncation tradeoffs.

### Risk 9: CrySL section parsing in `llm_utils.crysl_to_json_lines` is header-pattern based
- Parsing depends on section-header regex matching and assumes expected section naming/layout.
- If rule formatting deviates, sections can be split incorrectly and downstream prompt quality drops.

### Risk 10: RAG cache key tracks PDF by path + size/mtime signature
- This is fast and practical, but it is not a full file-content hash.
- Rare edge cases (metadata anomalies/manual timestamp edits) can produce stale cache reuse.

### Risk 11: Utility duplication between `llm_utils.py` and secure writer helpers
- Explanation writers use shared `llm_utils.py`, but secure writer maintains local helper copies.
- Behavior can drift silently when one side changes and the other is not updated in lockstep.

---

## 18. Practical Mental Model
Use this simple model:

- Java decides **when** and **for which class** Python runs.
- Python decides **how** to ask the model and **what** text/code to emit.
- Java decides **how to cache**, **how to recover**, and **how to render final docs**.

So Python is the generation engine; Java is the pipeline controller and final publisher.
