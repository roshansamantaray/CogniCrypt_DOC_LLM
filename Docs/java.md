# Java Pipeline Deep Dive

## What This Project Does (Java Perspective)
The Java side of this project takes CrySL rules (security usage rules for crypto APIs) and turns them into an HTML documentation site.

In simple terms, the Java pipeline does four main jobs:
1. Read CrySL rules.
2. Translate each rule into plain-language sections (order, constraints, predicates, and more).
3. Optionally ask Python-based LLM tools for extra explanations and secure/insecure code examples.
4. Render final HTML pages with FreeMarker templates.

The center of this flow is `DocumentGeneratorMain`. It coordinates all steps from command-line parsing to final HTML files.
Simple mental model: Java controls flow and rendering, and Python adds optional LLM-generated content.

### Quick glossary (CrySL terms used in this document)
| Term | Simple meaning |
|---|---|
| `SPEC` | The Java class that the rule is about. |
| `OBJECTS` | Variables and types used in the rule. |
| `EVENTS` | Relevant API method calls. |
| `ORDER` | Allowed call sequence (usage protocol). |
| `CONSTRAINTS` | Value/logic restrictions on parameters and usage. |
| `REQUIRES` | Predicates that must already hold before safe use. |
| `ENSURES` | Predicates guaranteed after safe use. |
| `FORBIDDEN` | Calls that should not be used. |
| Predicate | A named condition passed between rules/classes. |
| Typestate | State-machine view of allowed call order. |

## High-Level Architecture
From a Java perspective, the architecture is layered and pipeline-based.

| Layer | Main classes | Responsibility |
|---|---|---|
| Entry and configuration | `DocumentGeneratorMain`, `DocSettings` | Parse CLI flags, orchestrate full run, manage feature toggles. |
| Rule/resource loading | `CrySLReader`, `CrySLRuleReader`, `Utils`, `TemplateAbsolutePathLoader` | Load CrySL and template resources from disk or JAR. |
| Rule-to-text transformation | `ClassEventForb`, `Order`, `Constraints*`, `Ensures*`, `Negates` | Convert rule semantics into plain-language text chunks. |
| Dependency analysis | `Utils`, `PredicateTreeGenerator`, `GraphSanitizer`, `GraphVerification` | Build predicate dependency maps, trees, and stable ordering. |
| LLM orchestration | `CrySLToLLMGenerator`, `LLMService`, `CachePathResolver` | Build LLM payloads, call Python sidecars, cache outputs. |
| Rendering | `FreeMarkerWriter`, `StateMachineToGraphviz`, `.ftl` templates | Turn composed Java model into final HTML pages. |

## Main Runtime Flow (Step by Step)
This is the typical runtime path in `DocumentGeneratorMain`.

1. Parse CLI flags with `DocSettings.parseSettingsFromCLI(args)`.
2. Run startup preflight (`runStartupPreflight`) to fail fast if critical classes are missing.
3. Read CrySL rules:
   - If `--rulesDir` is provided: read from that folder.
   - Otherwise: read bundled rules from JAR resources (`CrySLReader.readRulesFromJar`).
4. Build helper maps:
   - `mapEnsures`: class -> predicates ensured by that class.
   - `mapRequires`: class -> predicates required by that class.
5. For each rule, build one `ComposedRule`:
   - load raw CrySL text,
   - generate overview section,
   - generate order text,
   - generate constraints text,
   - generate predicates text,
   - aggregate all constraint-like lines into `allConstraints`.
6. Build dependency maps between rules using `Utils.mapPredicates` and `Utils.toOnlyClassNames`.
7. Build two dependency trees with `PredicateTreeGenerator`:
   - requires -> ensures,
   - ensures -> requires.
8. For each rule, sanitize and verify dependency graph:
   - `GraphSanitizer.sanitize(...)`,
   - `GraphVerification.verifyOrdering(...)`,
   - compute leaf-to-root order via `Utils.leafToRootOrderTopo(...)`,
   - store in `ComposedRule.dependency`.
9. Explanations (if enabled): call `CrySLToLLMGenerator.generateExplanations(...)`.
10. Explanation cache pass:
    - use existing cached text if present,
    - otherwise write generated (or placeholder) text,
    - reload cache files in a second loop and attach/overwrite the final language map on each `ComposedRule`.
11. Code examples (if enabled): per rule:
    - regenerate when cache missing or retryable placeholder,
    - write secure/insecure cache files,
    - attach examples to `ComposedRule`.
12. Write codegen failure report (`llm_codegen_failures.txt`) inside code cache.
13. Initialize FreeMarker and render all pages:
    - base layout,
    - sidebar,
    - per-class pages.
14. Optionally copy CrySL rule files into output `rules/` folder.
15. Print total execution time.

## Core Data Model and Shared State
### `ComposedRule`: the central per-class DTO
`ComposedRule` is the Java object that carries everything needed by templates for one class:
- identity and link fields,
- order/constraints/predicate lines,
- full flattened constraint list,
- dependency order list,
- LLM explanations (`Map<language, text>`),
- secure/insecure code examples,
- raw CrySL text.

This object is the bridge between pipeline processing and rendering.

### Global/shared state patterns
Several classes use shared mutable state:
- `DocSettings` is a singleton and stores run-wide settings.
- `Order` has static maps (`processedresultMap`, `symbolMap`, `objectMap`) reused across calls.
- Other builders also rely on static helpers and implicit shared resources.

This is functional for single-process execution, but it is an important behavior detail for stability (covered again in Risks).

## Rule Ingestion and Resource Loading
### Rule loading path
`DocumentGeneratorMain` chooses rule source based on CLI:
- disk path via `--rulesDir`, or
- bundled resources via `CrySLReader`.

`CrySLReader` supports both IDE mode and packaged JAR mode. In JAR mode, it extracts needed files into a temp directory for parsing.

### Template and resource loading path
- FreeMarker templates (`.ftl`) can come from:
  - `--ftlTemplatesPath`, or
  - bundled JAR resources through `CrySLReader.readFTLFromJar(...)`.
- Language text templates (`src/main/resources/Templates/*`) can come from:
  - `--langTemplatesPath`, or
  - classpath fallback via `Utils.getTemplatesTextString(...)`.
- `symbol.properties` is loaded by `Order.getSymValues()` from override path or JAR fallback.

### `TemplateAbsolutePathLoader`
`FreeMarkerWriter.setupFreeMarker(...)` uses `TemplateAbsolutePathLoader`, which allows FreeMarker to load templates by absolute filesystem path or `file:` URI. This supports both override mode and extracted temp-file mode.

### `FTLTemplateLoaderFromJar`
This class extracts an FTL template from bundled resources via `Utils.extract(...)`. In current pipeline wiring, rendering mainly uses `CrySLReader.readFTLFromJar(...)`, so `FTLTemplateLoaderFromJar` is effectively a legacy/alternate helper.

## Natural-Language Section Generation Pipeline
This pipeline turns CrySL semantic structures into plain-language text lines.

### Overview section
Handled by `ClassEventForb`:
- class name sentence,
- JavaDoc link,
- method count summary,
- forbidden methods list.

It uses text fragments from `src/main/resources/Templates/*` and substitutes values via `StringSubstitutor`.

### ORDER section
Handled by `Order`:
- reads raw `.crysl` file text,
- parses `EVENTS` and `ORDER` sections,
- resolves label aggregates,
- maps symbols (`*`, `+`, `?`, `|`, `(`, `)`) to readable phrases,
- creates structured natural-language order lines.

This class does heavy string parsing and is one of the most complex parts of the pipeline.

### Constraint sections
Built by multiple specialized classes:
- `ConstraintsVc`: value constraints on parameters.
- `ConstraintsPred`: predicate-related constraints.
- `ConstraintsComparison`: arithmetic/comparison constraints.
- `ConstraintCrySLVC`: implication constraints built from value constraints.
- `ConstraintCryslnocallto`: `noCallTo(...)` constraints.
- `ConstraintCrySLInstanceof`: `instanceof` style implication constraints.
- `ConstraintCrySLandencmode`: `encmode` + call/noCall mixed constraints.

Each class maps CrySL AST fragments back to method signatures and parameter positions, then renders text using template snippets.

### Predicate sections
- `Ensures`: predicates related to `this`.
- `EnsuresCaseTwo`: predicates not tied to `this`, including return-value and parameter cases.
- `Negates`: negated predicate reporting.

These classes also add tooltip links that connect classes through predicate relationships.

### Utility support in this stage
`FunctionUtils` provides repeated method-signature and parameter-position extraction logic used across clause builders.

## Dependency Graph Pipeline (Requires/Ensures, Trees, Ordering)
This stage builds and stabilizes inter-class predicate dependencies.

### Step 1: Build directional maps
`Utils.mapPredicates(...)` maps:
- predicates provided by one class,
- to classes that depend on those predicates.

Then `Utils.toOnlyClassNames(...)` reduces mapping to class-name adjacency sets.

### Step 2: Build tree view for templates
`PredicateTreeGenerator.buildDependencyTreeMap(...)` turns adjacency into tree roots (`TreeNode<String>`) for both:
- requires tree,
- ensures tree.

These trees are rendered in `singleclass.ftl` with expand/collapse behavior.

### Step 3: Sanitize dependency graph for ordering
`GraphSanitizer.sanitize(...)`:
- defensive-copies graph,
- removes nulls and self-loops,
- keeps only nodes reachable from current class,
- collapses strongly connected components (SCCs) for stable behavior,
- expands back to an adjacency usable for ordering.

### Step 4: Verify and order
`GraphVerification.verifyOrdering(...)`:
- recomputes leaf-to-root order,
- checks the current class is the last item,
- runs Tarjan SCC analysis on reachable graph and reports cycle context.

`Utils.leafToRootOrderTopo(...)` then computes the final order used by the rule (`ComposedRule.dependency`).

## LLM Integration on the Java Side
Java does not call model APIs directly. It orchestrates Python sidecars.

### `CrySLToLLMGenerator`
This class builds `Map<String, String>` payloads per rule:
- class name,
- objects,
- events summary,
- order,
- constraints,
- requires,
- dependency list (currently in explanation path),
- ensures,
- forbidden methods.

Then it calls `LLMService`:
- `getLLMExplanation(...)` for multilingual explanations,
- `getLLMExample(...)` for secure/insecure code.

### `LLMService` responsibilities
1. Choose Python executable (prefer local `.venv`).
2. Choose backend script (`openai` or `gateway`) for explanations.
3. Generate temp JSON payloads.
4. Sanitize rule payload JSON via `Utils.sanitizeRuleFileSecure(...)`.
5. Resolve cache paths via `CachePathResolver` under `<reportPath>/resources/...`.
6. Spawn Python process with arguments.
7. Merge stderr into stdout (`redirectErrorStream(true)`) and read one combined output stream.
8. Enforce 60-second timeout.
9. Return output or raise clear `IOException` on errors.

### Java↔Python handoff details
- Explanation scripts receive class and language.
- Example scripts receive temp JSON plus `--backend` and `--rules-dir`; secure flow also gets compile classpath/release and `JAVAC_BIN` env.
- Java captures merged stdout+stderr from Python processes, so Python stderr logs can appear in captured text/code output.
- Java stores outputs in report-scoped cache files and uses placeholders when generation fails or is disabled.

### `CachePathResolver`
Centralizes two cache directories:
- `<reportPath>/resources/llm_cache`
- `<reportPath>/resources/code_cache`

It normalizes report path and rejects null/blank inputs.

## FreeMarker Rendering and Final HTML Output
### Rendering pipeline (`FreeMarkerWriter`)
1. `setupFreeMarker(...)`: configures loader and runtime settings.
2. `createCogniCryptLayout(...)`: writes `frontpage.html`, `rootpage.html`, `crysl.html`.
3. `createSidebar(...)`: writes `navbar.html` with searchable class list.
4. `createSinglePage(...)`: writes one HTML file per class under `composedRules/`.

### How templates consume Java-populated data
`singleclass.ftl` consumes:
- overview fields (`rule.composedClassName`, links),
- order list (`rule.order`),
- all constraint lists,
- ensures/negates lists,
- dependency trees (`requires`, `ensures` root nodes),
- LLM explanations for 4 languages,
- secure/insecure code examples,
- raw CrySL text,
- a separate state machine DOT input key (`stateMachine`, computed from CrySL usage pattern),
- UI toggle booleans (`booleanA`..`booleanD` used directly; `booleanE`/`booleanF` are passed but currently unused in template conditions).

Other key templates:
- `sidebar.ftl`: class navigation/search.
- `rootpage.ftl`: frameset container linking navbar + content.
- `frontpage.ftl` and `crysl.ftl`: explanatory landing content.

### Graph rendering
`StateMachineToGraphviz.toGraphviz(...)` converts usage pattern graph into DOT. The template uses `d3-graphviz` in browser to render it.

## CLI, Flags, and Behavioral Switches
`DocSettings` is the single source of CLI behavior.

| Flag | Behavior impact |
|---|---|
| `--reportPath <dir>` | Required. Output root and cache base. |
| `--rulesDir <dir>` | Use external CrySL files instead of bundled rules. |
| `--ftlTemplatesPath <dir>` | Override FreeMarker templates. |
| `--langTemplatesPath <dir>` | Override sentence template text and symbols. |
| `--booleanA` | Hide state machine graph section (toggle semantics are inverse in code: passing flag sets false). |
| `--booleanB` | Hide help button. |
| `--booleanC` | Hide dependency trees. |
| `--booleanD` | Hide raw CrySL section. |
| `--booleanE` | Parsed and passed into template context, but currently not used by template conditions (legacy behavior). |
| `--booleanF` | Copy CrySL rules into output `rules/` folder (flag flips internal boolean to false; naming is inverted). |
| `--booleanG` | Use fully qualified labels in graph edges (toggle semantics are inverse in code: passing flag sets false and flips labeling mode). |
| `--llm=<on/off/...>` | Master toggle for both explanations and examples. |
| `--llm-explanations=<...>` | Toggle explanations only. |
| `--llm-examples=<...>` | Toggle examples only. |
| `--disable-llm-explanations` | Hard-disable explanations. |
| `--disable-llm-examples` | Hard-disable examples. |
| `--llm-backend=<openai|gateway>` | Select backend for both explanation and example generation. |

## Caching, Filesystem Layout, and Generated Artifacts
The Java pipeline uses report-scoped caches and writes stable output artifacts.

| Path | Produced artifact |
|---|---|
| `<reportPath>/rootpage.html` | Main entry page (frameset). |
| `<reportPath>/frontpage.html` | Landing content. |
| `<reportPath>/navbar.html` | Left navigation. |
| `<reportPath>/crysl.html` | CrySL language explanation page. |
| `<reportPath>/composedRules/<FQCN>.html` | Per-class documentation page. |
| `<reportPath>/resources/llm_cache/<class>_<lang>.txt` | Explanation cache text files. |
| `<reportPath>/resources/code_cache/<class>_secure.txt` | Secure code example cache. |
| `<reportPath>/resources/code_cache/<class>_insecure.txt` | Insecure code example cache. |
| `<reportPath>/resources/code_cache/llm_codegen_failures.txt` | Summary of codegen failures/placeholders. |
| `<reportPath>/rules/*.crysl` | Copied rules (when copy flag behavior allows). |
| `llm/temp_rules/*.json` | Temporary rule payloads for LLM scripts. |
| `llm/sanitized_rules/*.json` | Sanitized JSON payloads consumed by Python sidecars. |

## Error Handling and Resilience Patterns
The Java pipeline is defensive in several places:

1. Startup preflight checks for missing critical classes before full work starts.
2. CLI parser rejects invalid/missing required arguments and exits early.
3. Resource readers support both IDE and JAR runtime modes.
4. LLM subprocess calls enforce timeouts and report exit-code errors with output context (captured from merged stdout+stderr).
5. Cache directories are created defensively and normalized from report path.
6. Example generation uses retryable-placeholder logic to regenerate only when needed.
7. Failure placeholders and failure report file keep output usable even when LLM calls fail.
8. Graph verification throws when ordering invariants fail (`start` must end leaf->root order).

## Key Classes and Responsibilities (Class-by-Class Map)
### Core orchestration and config
| Class | Responsibility |
|---|---|
| `DocumentGeneratorMain` | Full end-to-end orchestration. |
| `DocSettings` | Parse/store CLI settings and feature flags. |
| `ComposedRule` | Per-rule aggregate model consumed by templates. |

### Rule ingestion and resource loading
| Class | Responsibility |
|---|---|
| `CrySLReader` | Read rules/templates/symbol resources from disk or JAR. |
| `TemplateAbsolutePathLoader` | FreeMarker loader for absolute paths and `file:` URIs. |
| `FTLTemplateLoaderFromJar` | Legacy helper for extracting FTL files from classpath/JAR. |
| `Utils` | Shared utility hub: sanitization, resource extraction, template loading, graph helpers. |
| `Constant` | Static resource path constant (legacy-style constant holder). |

### Rule-to-text transformers
| Class | Responsibility |
|---|---|
| `ClassEventForb` | Class name/link/event count/forbidden method summaries. |
| `Order` | Parse EVENTS/ORDER text and produce readable order narrative. |
| `ConstraintsVc` | Value constraint sentence generation. |
| `ConstraintsPred` | Predicate constraint sentence generation. |
| `ConstraintsComparison` | Arithmetic/comparison constraint rendering. |
| `ConstraintCrySLVC` | VC implication constraint rendering. |
| `ConstraintCryslnocallto` | `noCallTo` implication rendering. |
| `ConstraintCrySLInstanceof` | `instanceof` implication rendering. |
| `ConstraintCrySLandencmode` | Combined VC + encmode call/noCall constraints. |
| `Ensures` | ENSURES for `this`-related predicates. |
| `EnsuresCaseTwo` | ENSURES for return-value/parameter predicates. |
| `Negates` | NEGATES sentence generation. |
| `FunctionUtils` | Shared method signature and parameter helper logic. |

### Dependency graph and tree logic
| Class | Responsibility |
|---|---|
| `PredicateTreeGenerator` | Build tree structures for template visualization. |
| `TreeNode` | Generic node structure for dependency trees. |
| `GraphSanitizer` | Reachability cleanup, self-loop removal, SCC collapse. |
| `GraphVerification` | Ordering invariant checks + SCC diagnostics. |

### LLM orchestration boundary
| Class | Responsibility |
|---|---|
| `CrySLToLLMGenerator` | Build payload map and invoke LLM service methods. |
| `LLMService` | Subprocess bridge to Python LLM scripts + timeout/cache control. |
| `CachePathResolver` | Canonical report-scoped cache directory resolution. |

### Rendering and visualization
| Class | Responsibility |
|---|---|
| `FreeMarkerWriter` | Render all HTML artifacts from composed model. |
| `StateMachineToGraphviz` | Convert CrySL usage graph to DOT text. |

### Non-pipeline Java file
| Class | Responsibility |
|---|---|
| `de.upb.userstudy.StringEncryption` | Demo/example crypto code; not part of the documentation pipeline flow. |

## Technical Risks and Fragile Spots
### 1) Global mutable/static state
- **Risk:** Shared static maps/singletons (`DocSettings`, `Order` static maps) can carry accidental state across runs or future parallelization.
- **Why it matters:** Hidden shared state increases hard-to-debug behavior differences.
- **When it can surface:** Re-entrant usage, tests running in parallel, or future service-style runtime.

### 2) Parser and regex fragility
- **Risk:** `Order` and several constraint builders rely heavily on manual string splitting/regex replacements.
- **Why it matters:** Small syntax differences in CrySL formatting can break extraction or produce wrong sentences.
- **When it can surface:** New rule authoring style, unusual spacing, nested constructs, or edge-case symbols.

### 3) Graph ordering assumptions
- **Risk:** `GraphVerification` expects leaf-to-root order to end with the start node; sanitized graph behavior is heuristic in some recovery branches.
- **Why it matters:** If dependency structure changes unexpectedly, ordering may fail or be misleading.
- **When it can surface:** Cyclic/ambiguous predicate dependencies, partial rule sets, or malformed maps.

### 4) Template/data coupling
- **Risk:** `singleclass.ftl` expects many specific fields and language keys to be present.
- **Why it matters:** Missing/renamed fields can cause rendering failures or empty sections.
- **When it can surface:** Refactoring `ComposedRule` fields, changing language list, or partial generation failures.

### 5) Java↔Python process execution edge cases
- **Risk:** LLM subprocess calls use fixed timeout and external environment assumptions.
- **Why it matters:** Slow models, network/API latency, or missing Python dependencies create placeholders instead of content.
- **When it can surface:** First-time environment setup, heavy batch runs, backend outages, slow gateway responses.

### 6) Legacy and partly unused utility paths
- **Risk:** Some utility classes/paths appear legacy or alternate (`FTLTemplateLoaderFromJar`, `Constant.rulePath`) and may diverge from active flow.
- **Why it matters:** Multiple loading paths increase maintenance complexity and confusion.
- **When it can surface:** Future edits that assume these helpers are active everywhere.

### 7) Mixed concerns in large builder classes
- **Risk:** Constraint builder classes hold parsing, mapping, and sentence rendering in long methods.
- **Why it matters:** Harder testing, harder reasoning, and higher chance of regression during changes.
- **When it can surface:** Feature additions to constraints or template variable changes.

### 8) Browser-side dependencies from CDN
- **Risk:** Some UI/rendering scripts in templates load from external CDNs.
- **Why it matters:** Offline environments or CSP-restricted deployments can break graph/markdown rendering.
- **When it can surface:** Air-gapped environments, strict enterprise browser policies.

### 9) Duplicated language list constants across Java classes
- **Risk:** Supported explanation languages are defined independently in `DocumentGeneratorMain` and `CrySLToLLMGenerator`.
- **Why it matters:** Future language changes can drift if only one list is updated.
- **When it can surface:** Adding/removing languages, refactoring explanation generation, or partial updates in PRs.

## End-to-End Example Run (From CLI to Output Files)
### Example command
```bash
java -jar target/DocGen-0.0.1-SNAPSHOT.jar \
  --reportPath /absolute/path/to/Output \
  --llm=on \
  --llm-backend=gateway
```

### ASCII sequence-style flow
```text
User CLI
  |
  v
DocumentGeneratorMain
  |-- parse args (DocSettings)
  |-- read rules (CrySLReader / CrySLRuleReader)
  |-- build ComposedRule per class
  |     |-- overview/order/constraints/predicates builders
  |     '-- aggregate all constraints
  |-- build dependency maps + trees
  |-- sanitize + verify graph + compute leaf->root order
  |-- LLM explanations (CrySLToLLMGenerator -> LLMService -> Python)
  |-- LLM code examples (CrySLToLLMGenerator -> LLMService -> Python)
  |-- attach cache/generated text to ComposedRule
  |-- render HTML (FreeMarkerWriter + templates)
  '-- write output + cache files + failure report
```

### What happens in the output directory
1. Core pages are created (`rootpage.html`, `frontpage.html`, `navbar.html`, `crysl.html`).
2. A page is created for each CrySL class under `composedRules/`.
3. LLM text/code caches are written under `resources/llm_cache` and `resources/code_cache`.
4. Optional `rules/` copy is produced based on boolean flag behavior.

## Final Result: What a Successful Run Produces
A successful Java pipeline run produces a browsable HTML documentation site with:
- per-class overview,
- order and state machine graph,
- natural-language constraints,
- ensures/negates predicate explanations,
- requires and ensures dependency trees,
- optional multilingual LLM explanations,
- optional secure/insecure Java examples,
- raw CrySL rule text.

The pipeline is designed to still generate docs when LLM calls fail. In that case, placeholders and failure reports make the run status visible without losing the rest of the documentation.
