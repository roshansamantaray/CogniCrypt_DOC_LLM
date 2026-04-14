# Project Deep Dive: CogniCrypt_DOC_LLM

## 1. What This Project Is Trying to Do
This project reads **CrySL rules** (formal secure-usage specifications for crypto APIs) and turns them into **developer-facing HTML documentation**.

At a high level, it runs in three stages:
1. Reads and interprets CrySL rules.
2. Converts rule semantics into plain-language sections (order, constraints, predicates, dependencies).
3. Renders full HTML docs, optionally enriched with LLM explanations and secure/insecure Java code examples.

The main output is a browsable documentation site with `rootpage.html` as the entry page in the selected report directory.

## 2. Main Goal and Final Result
### Goal
Help developers understand how to use Java crypto APIs securely, using CrySL as the source of truth.

### Final Result of a Successful Run
A generated documentation bundle that includes:
- layout pages (`rootpage.html`, `frontpage.html`, `navbar.html`, `crysl.html`)
- one per-class page under `composedRules/`
- optional cached LLM explanations and code examples under `resources/`
- optional copied `.crysl` rules under `rules/` (depending on CLI flag behavior)

## 3. End-to-End Architecture (Big Picture)
The project has two connected runtime parts:

- **Java orchestrator (primary pipeline)**
  - Entry point: `de.upb.docgen.DocumentGeneratorMain`
  - Responsible for rule parsing, section generation, dependency graphing, and HTML rendering.
- **Python LLM sidecar (optional enrichment)**
  - Called from Java through subprocesses.
  - Generates multilingual explanations and secure/insecure Java snippets.

Supporting layers:
- **CrySL resource loading** (filesystem override or bundled JAR resources)
- **Template system**
  - text clause templates (`src/main/resources/Templates/**`)
  - FreeMarker page templates (`src/main/resources/FTLTemplates/**`)
- **RAG/cache utilities** for LLM grounding and performance.

## 4. End-to-End Flow in Sequence Form
```text
User CLI
  -> DocumentGeneratorMain.main(args)
    -> DocSettings.parseSettingsFromCLI
    -> Startup preflight (critical classes)
    -> Load CrySL rules (custom dir or bundled JAR)
    -> Build ComposedRule objects per class
       -> Overview + Order + Constraints + Predicates
       -> Dependency graph sanitize/verify/order
    -> Optional LLM explanations (Java -> Python writer)
       -> cache under <reportPath>/resources/llm_cache
       -> second pass re-reads cache and reattaches explanation map to ComposedRule
    -> Optional LLM code examples (Java -> Python code writers)
       -> cache under <reportPath>/resources/code_cache
       -> write llm_codegen_failures.txt
    -> FreeMarker render
       -> root/front/sidebar/per-class pages
    -> Optional copy of CrySL rules to output/rules
  -> Open <reportPath>/rootpage.html
```

## 5. Repository Structure and Responsibilities
| Area | Purpose |
|---|---|
| `src/main/java/de/upb/docgen/**` | Main Java documentation pipeline |
| `src/main/resources/CrySLRules/**` | Bundled CrySL rule files |
| `src/main/resources/Templates/**` | Language fragments for clause sentence generation |
| `src/main/resources/FTLTemplates/**` | FreeMarker HTML templates |
| `llm/**` | Python LLM scripts (explanations, code generation, RAG/indexing) |
| `scripts/delete_disabled_code_cache_files.py` | Cache cleanup utility for placeholder outputs (including optional `--also-delete-cache-kept` cleanup) |
| `src/test/java/**` + `llm/tests/**` | Small focused tests for cache/path behavior |

## 6. Java Runtime Pipeline (Detailed)

### 6.1 Entry and Settings
- Entry point: `DocumentGeneratorMain.main`.
- Settings are global singleton: `DocSettings`.
- Only `--reportPath` is mandatory.
- CLI parsing supports:
  - input/template overrides
  - boolean section toggles
  - LLM master and per-feature toggles
  - backend selection (`openai` or `gateway`)

Important behavior:
- Many boolean flags are **inversion flags** (default is true; passing flag sets false).
- LLM flags are order-sensitive: later args can override earlier toggles.

### 6.2 Startup Preflight
Before heavy work, Java checks that a few classes exist on classpath:
- `de.upb.docgen.writer.FreeMarkerWriter`
- `freemarker.template.Configuration`
- `de.upb.docgen.llm.LLMService`

If missing, startup fails early with a classpath-focused error.

### 6.3 Rule Ingestion
Rules come from one of two sources:
- `--rulesDir`: direct filesystem loading via `CrySLRuleReader`
- default: bundled resources via `CrySLReader.readRulesFromJar()`

`CrySLReader` handles both IDE file-mode and packaged JAR mode. In JAR mode it extracts files into a temp directory (`java.io.tmpdir/cognicryptdoc_resources`) and parses from there.

### 6.4 Building Per-Rule Documentation State
For each `CrySLRule`, Java builds a `ComposedRule` object. This object is the central in-memory payload for rendering.

`ComposedRule` includes:
- identity/overview fields (class name, javadoc link)
- all generated section texts (order, constraints, predicates)
- dependency ordering
- LLM explanation map
- secure/insecure example code
- raw CrySL text for display

### 6.5 Overview and Section Builders
The pipeline instantiates clause builders and calls them per rule:

- `ClassEventForb`
  - class identity text
  - JavaDoc links
  - method/event count sentence
  - forbidden method sentences
- `Order`
  - parses `EVENTS` + `ORDER` directly from `.crysl`
  - resolves symbols from `symbol.properties`
  - emits natural language call-order statements
- `ConstraintsVc`
  - value constraints
- `ConstraintsPred`
  - predicate-related constraints with tooltip links to ensuring classes
- `ConstraintsComparison`
  - arithmetic/length comparison constraints
- `ConstraintCrySLVC`
  - implication constraints (VC implies VC)
- `ConstraintCryslnocallto`
  - noCallTo implication constraints
- `ConstraintCrySLInstanceof`
  - instanceof-style implication constraints
- `ConstraintCrySLandencmode`
  - encmode-specific implications
- `Ensures` + `EnsuresCaseTwo`
  - ensures predicate text for `this` and non-`this` cases
- `Negates`
  - negated predicate text

`FunctionUtils` is shared glue for extracting method signatures, positions, and datatype mappings.

### 6.6 Dependency Graph Pipeline
This stage maps predicate relationships across classes.

Core steps:
1. Build maps from class -> ensures predicates and class -> requires predicates.
2. Use `Utils.mapPredicates(...)` to build dependency adjacency views.
3. Convert to class-level sets (`Utils.toOnlyClassNames`).
4. Build trees for UI rendering (`PredicateTreeGenerator.buildDependencyTreeMap`).
5. For each rule:
   - sanitize graph (`GraphSanitizer.sanitize`)
   - verify ordering (`GraphVerification.verifyOrdering`)
   - compute leaf-to-root order (`Utils.leafToRootOrderTopo`)
   - store in `ComposedRule.dependency`

`GraphSanitizer` handles self-loop removal, reachable-subgraph focus, SCC collapse/expansion, and logs cycle details.

`GraphVerification` checks ordering sanity (target class must be last in leaf->root order) and reports SCC status for the start node.

### 6.7 LLM Explanations (Java Side)
If enabled, Java calls:
- `CrySLToLLMGenerator.generateExplanations(...)`
  - builds structured prompt payload from `ComposedRule` + `CrySLRule`
  - calls `LLMService.getLLMExplanation(...)`

`LLMService.getLLMExplanation`:
- picks script by backend:
  - `llm/llm_writer.py` (OpenAI)
  - `llm/llm_writer_gateway.py` (gateway)
- creates/uses:
  - `llm/temp_rules/*.json`
  - `llm/sanitized_rules/*.json`
- stores final text cache in:
  - `<reportPath>/resources/llm_cache/<class>_<language>.txt`
- captures merged stdout+stderr (`redirectErrorStream(true)`) from Python process output
- enforces 60-second process timeout per class/language call
- Java then performs a second loop that re-reads explanation cache files and overwrites `composedRule.setLlmExplanation(...)`

Languages are fixed to:
- English
- Portuguese
- German
- French

Important implementation note:
- The same language list is currently declared in both `CrySLToLLMGenerator` and `DocumentGeneratorMain`.

### 6.8 LLM Secure/Insecure Code Examples
If enabled, Java calls:
- `CrySLToLLMGenerator.generateExample(...)`
  - calls `LLMService.getLLMExample(..., "secure")`
  - calls `LLMService.getLLMExample(..., "insecure")`

`LLMService.getLLMExample`:
- writes payload to `llm/temp_example_secure.json` or `llm/temp_example_insecure.json`
- invokes:
  - `llm/llm_code_writer_secure.py`
  - `llm/llm_code_writer_insecure.py`
- passes backend and rules-dir; for secure mode also passes compile classpath and Java release
- captures merged stdout+stderr (`redirectErrorStream(true)`)
- enforces 60-second process timeout

Cache path:
- `<reportPath>/resources/code_cache/<class>_secure.txt`
- `<reportPath>/resources/code_cache/<class>_insecure.txt`

The Java layer includes placeholder logic:
- retries generation if file is missing or contains known placeholder/failure text
- writes `llm_codegen_failures.txt` report into code cache

### 6.9 FreeMarker Rendering
`FreeMarkerWriter` performs final rendering:
1. `setupFreeMarker` with `TemplateAbsolutePathLoader`
2. `createCogniCryptLayout`
   - `frontpage.html`, `rootpage.html`, `crysl.html`
3. `createSidebar`
   - `navbar.html`
4. `createSinglePage`
   - one HTML file per rule in `composedRules/`

Template source strategy:
- if `--ftlTemplatesPath` is set: load from absolute path
- otherwise: load from bundled resources via `CrySLReader.readFTLFromJar`

### 6.10 Optional Rule Export
If `--booleanF` is passed (which flips `booleanF` to `false`), Java copies CrySL rules into:
- `<reportPath>/rules/`

Source of copied files:
- from `--rulesDir` if provided
- otherwise from bundled resources

## 7. Template Behavior (What Gets Shown)

### 7.1 `rootpage.ftl`
Creates a frameset layout:
- left frame: `navbar.html`
- right frame: content page (`frontpage.html` by default)

### 7.2 `sidebar.ftl`
Shows:
- navigation links to each class page
- class search box

### 7.3 `frontpage.ftl`
Shows static onboarding/help sections about generated docs.

### 7.4 `crysl.ftl`
Shows an educational page explaining CrySL concepts and how to read docs.

### 7.5 `singleclass.ftl`
Main per-class page; renders sections:
- Overview
- Order (+ optional graph)
- Constraints
- Predicates
- Requires Tree / Ensures Tree (optional)
- LLM Explanation (language selector)
- LLM Code Examples
- CrySL Rule (optional)

Also includes:
- client-side Graphviz rendering (d3/d3-graphviz via CDN)
- collapsible sections
- tooltip display for cross-rule predicate links
- copy buttons for code blocks

Boolean-template mapping in practice:
- `booleanA`: graph visibility
- `booleanB`: help button visibility
- `booleanC`: dependency tree section visibility
- `booleanD`: raw CrySL section visibility
- `booleanE` and `booleanF` are passed into template input, but not actively used in `singleclass.ftl` conditions

## 8. Python LLM Sidecar (Detailed)

### 8.1 Explanation Writers
Scripts:
- `llm/llm_writer.py` (OpenAI)
- `llm/llm_writer_gateway.py` (gateway)

Shared core:
- `llm/utils/writer_core.py`
- `llm/utils/llm_utils.py`

Scope nuance:
- Explanation writers share `llm_utils.py`.
- Secure code writer keeps local helper reimplementations instead of importing `llm_utils.py`.

Core explanation flow:
1. Parse class name + language + optional model/RAG args.
2. Load corresponding `.crysl` file.
3. Build normalized section text.
4. Load sanitized JSON context and dependency context.
5. Optionally build RAG context from CrySL paper PDF.
6. Call chat model with strict prompt structure.
7. Clean output and print; Java captures merged stdout+stderr on the subprocess boundary.

### 8.2 Secure Code Writer
Script: `llm/llm_code_writer_secure.py`

Key behavior:
- backend-aware client/model selection
- builds a shaped CrySL contract with section caps
- loads dependency constraints/ensures from sanitized rules
- builds/loads a short CrySL primer (cached)
- prompts LLM for secure Java code
- deterministic post-pass:
  - normalize class name
  - auto-import known types
  - normalize known API mistakes
- compile gate with `javac`
- iterative repair loop using compiler errors
- outputs fenced Java code only when successful

Important runtime controls (env):
- `CRYSLDOC_COMPILE_CHECK` (default on)
- `CRYSLDOC_COMPILE_STRICT`
- `CRYSLDOC_JAVAC_REQUIRED`
- `CRYSLDOC_MAX_REPAIRS` (default 7)
- `JAVAC_BIN`

### 8.3 Insecure Code Writer
Script: `llm/llm_code_writer_insecure.py`

Behavior:
- reads JSON payload
- asks model for intentionally insecure Java (intended to be valid, but not compile-validated)
- requests inline comments explaining insecurity
- no compile/repair loop

### 8.4 RAG and Indexing
Scripts:
- `llm/paper_index.py` (OpenAI embeddings)
- `llm/paper_index_gateway.py` (gateway embeddings)
- shared infra: `llm/utils/rag_index_common.py`

RAG index details:
- extracts text from `tse19CrySL.pdf`
- chunks by paragraph with overlap
- embeds chunks
- builds FAISS cosine index
- caches vectors/ids/chunks in provider/model/pdf-specific bucket under `rag_cache/`

### 8.5 Gateway Rate Limiting
`llm/utils/gateway_rate_limit.py` provides a cross-process throttle:
- default `GATEWAY_RPM=10`
- shared state files:
  - `llm/.gateway_rate_limit_state.json`
  - `llm/.gateway_rate_limit_state.lock`
- applies to both chat and embeddings in gateway scripts

## 9. CLI Flags and Behavioral Impact
| Flag | Effect |
|---|---|
| `--reportPath <dir>` | Required output root |
| `--rulesDir <dir>` | Load `.crysl` rules from filesystem instead of bundled resources |
| `--ftlTemplatesPath <dir>` | Override FreeMarker templates |
| `--langTemplatesPath <dir>` | Override text clause templates + `symbol.properties` |
| `--booleanA` | Hide state-machine graph section |
| `--booleanB` | Hide help button |
| `--booleanC` | Hide dependency trees |
| `--booleanD` | Hide raw CrySL section |
| `--booleanE` | Parsed but currently not visibly applied in template rendering |
| `--booleanF` | Triggers rule copy into `<reportPath>/rules/` (inverted semantics) |
| `--booleanG` | Use fully qualified method labels in graph edges |
| `--disable-llm-explanations` | Turn off explanation generation |
| `--disable-llm-examples` | Turn off code example generation |
| `--llm=<on/off/...>` | Master toggle for both explanation + examples |
| `--llm-explanations=<on/off/...>` | Per-feature explanation toggle |
| `--llm-examples=<on/off/...>` | Per-feature example toggle |
| `--llm-backend=<openai|gateway>` | Select Python backend path |

## 10. Output, Cache, and Artifact Layout
| Path | Produced by | Content |
|---|---|---|
| `<reportPath>/rootpage.html` | FreeMarker | frame entry page |
| `<reportPath>/frontpage.html` | FreeMarker | intro page |
| `<reportPath>/navbar.html` | FreeMarker | searchable sidebar |
| `<reportPath>/crysl.html` | FreeMarker | CrySL explainer |
| `<reportPath>/composedRules/*.html` | FreeMarker | per-class docs |
| `<reportPath>/resources/llm_cache/*.txt` | Java + Python | cached multilingual explanations |
| `<reportPath>/resources/code_cache/*_secure.txt` | Java + Python | secure code examples |
| `<reportPath>/resources/code_cache/*_insecure.txt` | Java + Python | insecure code examples |
| `<reportPath>/resources/code_cache/llm_codegen_failures.txt` | Java | failure summary |
| `<reportPath>/rules/*.crysl` | Java optional | copied rules for distribution |
| `llm/temp_rules/*.json` | Java | temporary explanation payloads |
| `llm/sanitized_rules/*.json` | Java sanitizer | cleaned prompt inputs for Python |
| `llm/temp_example_secure.json` | Java | secure code temp payload |
| `llm/temp_example_insecure.json` | Java | insecure code temp payload |
| `rag_cache/**` | Python | provider/model/pdf-scoped embedding cache |

## 11. Error Handling and Resilience Patterns

### Java Side
- CLI parse failures print full usage guidance and exit.
- Startup preflight fails fast on missing critical classes.
- Rule parsing uses batch parse with per-file fallback in `CrySLReader`.
- Subprocess timeouts are enforced at 60s for LLM scripts.
- Subprocess output capture merges stdout+stderr, so Python stderr logs can pollute captured explanation/code text.
- Cache creation uses defensive directory creation.
- Codegen placeholders prevent complete failure of final HTML generation.
- Final elapsed-time metric is printed in a `finally` block.

### Python Side
- Missing env vars throw explicit backend configuration errors.
- Optional RAG failure degrades gracefully (warn + continue without RAG).
- Secure writer compile gate blocks non-compiling output unless explicitly relaxed.
- Gateway scripts throttle calls to reduce 429-like pressure.

## 12. Class-by-Class Map (Java Core)
| Class | Responsibility |
|---|---|
| `DocumentGeneratorMain` | Orchestrates full Java pipeline end-to-end |
| `DocSettings` | Global runtime settings singleton + CLI parser |
| `CrySLReader` | Reads bundled rules/templates from resources/JAR safely |
| `ComposedRule` | Main per-class data model for rendered documentation |
| `ClassEventForb` | Overview fields, JavaDoc links, forbidden method text |
| `Order` | Parses ORDER/EVENTS directly from `.crysl`, emits order language |
| `ConstraintsVc` | Value constraint sentence generation |
| `ConstraintsPred` | Predicate constraint sentence generation + tooltip linking |
| `ConstraintsComparison` | Comparison/length/arithmetic constraint sentence generation |
| `ConstraintCrySLVC` | VC implication constraint text |
| `ConstraintCryslnocallto` | noCallTo implication constraint text |
| `ConstraintCrySLInstanceof` | instanceof implication constraint text |
| `ConstraintCrySLandencmode` | encmode implication constraint text |
| `Ensures` | Ensures text for predicates involving `this` |
| `EnsuresCaseTwo` | Ensures text for non-`this` predicates/return values |
| `Negates` | Negated predicate text |
| `FunctionUtils` | Shared method/position/type extraction helpers |
| `FreeMarkerWriter` | Configures FreeMarker and renders all HTML pages |
| `StateMachineToGraphviz` | Converts CrySL state machines to DOT strings |
| `PredicateTreeGenerator` | Builds dependency trees for template rendering |
| `TreeNode` | Simple generic tree node model |
| `Utils` | Sanitizer, resource extraction, predicate mapping, topo ordering, utility functions |
| `GraphSanitizer` | Graph cleanup, SCC handling, reachability focus |
| `GraphVerification` | Ordering/SCC verification diagnostics |
| `CachePathResolver` | Canonical cache-dir path resolver under reportPath |
| `TemplateAbsolutePathLoader` | FreeMarker loader for absolute paths and `file:` URIs |
| `FTLTemplateLoaderFromJar` | Legacy template extractor utility (currently not in main flow) |
| `Constant` | Static resource path constant (legacy/limited usage) |
| `CrySLToLLMGenerator` | Bridges ComposedRule/CrySLRule data into LLMService calls |
| `LLMService` | Java->Python subprocess bridge for explanations and examples |

## 13. Python Component Map
| Script/Module | Responsibility |
|---|---|
| `llm/llm_writer.py` | OpenAI explanation generation wrapper |
| `llm/llm_writer_gateway.py` | Gateway explanation generation wrapper |
| `llm/utils/writer_core.py` | Shared explanation flow and prompt orchestration |
| `llm/utils/llm_utils.py` | Sanitized-file lookup, dependency extraction, formatting helpers |
| `llm/llm_code_writer_secure.py` | Secure code generation with compile/repair loop |
| `llm/llm_code_writer_insecure.py` | Insecure code generation script |
| `llm/paper_index.py` | OpenAI-based PDF embedding index builder |
| `llm/paper_index_gateway.py` | Gateway-based PDF embedding index builder |
| `llm/utils/rag_index_common.py` | FAISS/chunk/cache shared index logic |
| `llm/utils/gateway_rate_limit.py` | Cross-process RPM limiter |

## 14. Key Feature Set (What Users Actually Get)
- Full per-class secure-usage docs from CrySL rules.
- Natural-language sections for order, constraints, predicates.
- Interactive dependency trees and graph visualization.
- Optional multilingual LLM explanations.
- Optional secure/insecure Java examples.
- Caching to avoid repeated expensive LLM calls.
- Flexible resource/template overrides via CLI.
- Works both from IDE file resources and packaged JAR resources.

## 15. Technical Risks and Fragile Spots

### Risk 1: Global mutable/static state in parser-style classes
- **Where**: `DocSettings` singleton, static maps in `Order` (`processedresultMap`, `symbolMap`, `objectMap`).
- **Why it matters**: makes behavior sensitive to call order and difficult to parallelize safely.
- **When it can surface**: concurrent runs in same JVM, future refactors to multi-threaded execution, early returns that bypass expected cleanup patterns.

### Risk 2: In-place sorting side effect on `composedRuleList`
- **Where**: `FreeMarkerWriter.createSidebar` sorts `composedRuleList` in place.
- **Why it matters**: `createSinglePage` pairs `composedRuleList[i]` with `crySLRules[i]`; if order differs, state-machine graph/data pairing can drift.
- **When it can surface**: non-deterministic or non-alphabetical rule read order.

### Risk 3: Regex/string-heavy clause parsing fragility
- **Where**: `Order`, several constraint classes, and helper regex parsing.
- **Why it matters**: minor format changes in CrySL text can break mapping logic or produce wrong sentences.
- **When it can surface**: new rule syntax patterns, unusual spacing/comments/edge cases.

### Risk 4: Graph recovery heuristics may infer wrong dependencies
- **Where**: `GraphSanitizer` “recover missing deps for start” heuristic.
- **Why it matters**: heuristic recovery can over- or under-connect graph relationships.
- **When it can surface**: sparse or asymmetrical predicate maps, rare rule combinations.

### Risk 5: Verification checks are partly diagnostic, not fully enforcing
- **Where**: `GraphVerification` logs SCC results and enforces only selected ordering condition.
- **Why it matters**: cycles may still be present as warnings while pipeline proceeds.
- **When it can surface**: highly interconnected predicate graphs.

### Risk 6: Cache staleness for explanations
- **Where**: explanation cache in `<reportPath>/resources/llm_cache` and `llm/temp_rules` / `llm/sanitized_rules` write-once behavior.
- **Why it matters**: stale cached content can mask updated rules/templates/prompts.
- **When it can surface**: reruns after rule changes without cache cleanup.

### Risk 7: Backend/model changes do not automatically invalidate all caches
- **Where**: explanation/code cache filenames are class/language/type based, not backend+model keyed at Java layer.
- **Why it matters**: output can silently mix old/new backend results.
- **When it can surface**: switching `--llm-backend`, models, or prompts across runs.

### Risk 8: Subprocess timeout windows can be tight for long generations
- **Where**: Java enforces 60s timeout per Python call.
- **Why it matters**: legitimate slow responses become failures/placeholders.
- **When it can surface**: high latency APIs, heavy models, gateway contention.

### Risk 9: Template/data contract is tightly coupled
- **Where**: `singleclass.ftl` expects specific keys (`rule.*`, language entries, code fields, tree roots).
- **Why it matters**: missing keys/null maps can break rendering or sections silently.
- **When it can surface**: future schema refactor in `ComposedRule` or pipeline short-circuit paths.

### Risk 10: Legacy/unused paths can cause maintenance confusion
- **Where**: `FTLTemplateLoaderFromJar`, `Constant`, partly unused boolean flags (`booleanE`) in rendered behavior.
- **Why it matters**: increases cognitive load and risk of wrong assumptions in future changes.
- **When it can surface**: cleanup/refactor tasks, onboarding of new contributors.

### Risk 11: Limited automated test coverage for core text generation logic
- **Where**: current tests focus mostly on path/cache utility behavior.
- **Why it matters**: complex clause logic and rendering contracts are mostly unguarded by tests.
- **When it can surface**: parser/template changes, rule grammar evolution.

### Risk 12: Duplicated explanation language list in Java orchestration path
- **Where**: `CrySLToLLMGenerator` and `DocumentGeneratorMain` each define their own `LANGUAGES` list.
- **Why it matters**: language support can drift if only one definition is updated.
- **When it can surface**: language additions/removals or partial refactors.

## 16. Example End-to-End Run Walkthrough

### Example command (LLM disabled)
```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/Output \
  --llm=off
```

### What happens
1. CLI is parsed, `reportPath` validated.
2. Rules are loaded (filesystem override or bundled resources).
3. For each rule, Java computes all textual sections + dependency info.
4. LLM generation is skipped; placeholders/cached values are used as needed.
5. FreeMarker renders full HTML site.
6. You open `/absolute/path/to/Output/rootpage.html`.

### Example command (LLM enabled via OpenAI)
```bash
set -a; source llm/.env; set +a
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/Output \
  --llm=on \
  --llm-backend=openai
```

This adds explanation and code generation and writes caches in `resources/`.

## 17. Practical Summary
If you think about this project as a pipeline, the simplest mental model is:

- **CrySL in** -> **Java transforms it into structured human-readable sections** -> **optional Python LLM enriches text/code** -> **FreeMarker renders final docs** -> **HTML site out**.

The Java side is the authoritative orchestrator and data shaper. The Python side is an optional augmentation layer. The generated HTML pages are the final product developers consume.
