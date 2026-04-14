# DocumentGeneratorMain Deep Dive (Simple Version)

This file explains `DocumentGeneratorMain.java` in plain language.
It focuses on:
- what the class does,
- what each method does,
- how the flow moves from start to finish,
- and what important code snippets mean.

Main source file:
`src/main/java/de/upb/docgen/DocumentGeneratorMain.java`

---

## 1) What this class does

`DocumentGeneratorMain` is the top-level orchestrator for the Java pipeline.

It controls the full runtime:
1. parse CLI settings,
2. load CrySL rules,
3. build `ComposedRule` objects,
4. compute dependency order,
5. call LLM sidecar flow (if enabled),
6. manage report-scoped caches,
7. render final HTML pages.

If someone asks “where is the main Java flow?”, this is the file.

---

## 2) Class-level fields and what they mean

### `ruleReader`
```java
private static final CrySLRuleReader ruleReader = new CrySLRuleReader();
```
What it does:
- Reads CrySL rules from a filesystem directory when `--rulesDir` is provided.

Why it matters:
- This is the non-JAR path for loading rules.

### `CRITICAL_STARTUP_CLASSES`
```java
private static final List<String> CRITICAL_STARTUP_CLASSES = List.of(
    "de.upb.docgen.writer.FreeMarkerWriter",
    "freemarker.template.Configuration",
    "de.upb.docgen.llm.LLMService"
);
```
What it does:
- Defines classes that must exist before pipeline execution continues.

Why it matters:
- Fails early if runtime/classpath is broken.

---

## 3) Method-by-method explanation

## 3.1 `main(String[] args)`

This is the full pipeline entrypoint.
It is the first method that runs.

During execution it calls other helper methods in this order:
1. `runStartupPreflight()` near startup
2. `isRetryablePlaceholder(...)` inside example-cache checks
3. `isFailurePlaceholder(...)` when collecting failure entries
4. `failureReason(...)` when formatting failure details
5. `writeCodegenFailureReport(...)` at the end of the example stage

Below in Section 4, `main(...)` is explained stage-by-stage.

---

## 3.2 `runStartupPreflight()`

### What it does
- Loops through `CRITICAL_STARTUP_CLASSES`.
- Calls `Class.forName(...)` for each class.
- Throws `IllegalStateException` if any class is missing.

### Core snippet
```java
Class.forName(className, false, cl);
```

### Why this is useful
- It avoids late failures deep in rendering/LLM logic.
- You get a clear startup error with classpath info.

### Behavior summary
- Input: none
- Output: none
- Side effect: may throw and stop startup

---

## 3.3 `isRetryablePlaceholder(String content, boolean secure)`

### What it does
- Checks whether a cached example file contains a placeholder instead of real code.
- Handles both secure and insecure placeholder strings.

### Placeholder types it recognizes
- unavailable
- disabled by flag
- failed with error prefix

### Why this is useful
- Lets the pipeline regenerate code when cache has only fallback text.

---

## 3.4 `isFailurePlaceholder(String content, boolean secure)`

### What it does
- Wrapper method that currently delegates to `isRetryablePlaceholder(...)`.

### Why it exists
- Keeps failure-check logic centralized and readable at callsites.

---

## 3.5 `failureReason(String content, boolean secure)`

### What it does
- Extracts readable reason text from:
  - `// LLM secure example failed: ...`
  - `// LLM insecure example failed: ...`
- Returns `"unknown"` or `"example unavailable"` for fallback cases.

### Why this is useful
- The failure report file can show per-rule failure reasons.

---

## 3.6 `writeCodegenFailureReport(File codeCacheDir, List<String> failures)`

### What it does
- Writes `llm_codegen_failures.txt` under code cache.
- Includes timestamp.
- Writes either:
  - list of failures, or
  - “No LLM code generation failures.”

### Core snippet
```java
File report = new File(codeCacheDir, "llm_codegen_failures.txt");
Files.writeString(report.toPath(), sb.toString());
```

### Important behavior
- This method is called at the end of the example loop.
- Report file is written every run, not only on failure.

---

## 4) `main(...)` stage-by-stage flow

## Stage A: Start timer and parse settings

### Code snippet
```java
final long start = System.nanoTime();
DocSettings docSettings = DocSettings.getInstance();
docSettings.parseSettingsFromCLI(args);
runStartupPreflight();
```

### What it does
- Starts runtime timing.
- Parses all CLI flags.
- Runs classpath preflight check.

### Why it matters
- Ensures runtime config and dependencies are ready before heavy work starts.

---

## Stage B: Load CrySL rules

### Code snippet
```java
if (docSettings.getRulesetPathDir() != null && !docSettings.getRulesetPathDir().trim().isEmpty()) {
    rules = ruleReader.readFromDirectory(new File(docSettings.getRulesetPathDir()));
} else {
    rules = CrySLReader.readRulesFromJar();
}
```

### What it does
- Uses filesystem rules when `--rulesDir` is given.
- Otherwise uses bundled JAR resources.

### Why it matters
- Supports both development mode and packaged mode.

---

## Stage C: Initialize section builders

### What it does
- Creates helper objects for each documentation section:
  - class/event/forbidden,
  - ORDER,
  - value/predicate/comparison constraints,
  - ensures/negates.

### Why it matters
- Keeps section generation split by responsibility.

---

## Stage D: Build predicate maps (`mapEnsures`, `mapRequires`)

### What it does
- Precomputes class -> predicate mappings for dependency and cross-rule relations.

### Why it matters
- These maps are reused while building `ComposedRule` content.

---

## Stage E: Build one `ComposedRule` per CrySL rule

### What it does
For each rule, it:
1. resolves CrySL text (from filesystem or JAR),
2. fills overview fields (`className`, link, event count),
3. generates ORDER text (`or.runOrder(rule)`),
4. generates all constraint sections,
5. merges all constraints into `allConstraints`,
6. generates ensures/negates sections,
7. stores completed object in `composedRuleList`.

### Example snippet: raw CrySL text fallback
```java
if (cryslFile != null && cryslFile.exists()) {
    String ruleText = Files.readString(cryslFile.toPath());
    composedRule.setCryslRuleText("\n" + ruleText);
} else {
    composedRule.setCryslRuleText("// CrySL file not found for: " + simpleName);
}
```

### Why it matters
- `ComposedRule` is the renderer input model.
- This stage builds almost all non-LLM content.

---

## Stage F: Build dependency trees and order

### What it does
1. Builds dependency maps from predicate relations.
2. Builds tree models with `PredicateTreeGenerator`.
3. For each rule:
   - sanitize graph using `GraphSanitizer`,
   - verify ordering assumptions using `GraphVerification`,
   - compute final order with `Utils.leafToRootOrderTopo`,
   - store dependency list into `ComposedRule`.

### Core snippet
```java
Map<String, Set<String>> sanitized =
    GraphSanitizer.sanitize(onlyClassnamesEnsToReq, onlyClassnamesReqToEns, ruleName);
GraphVerification.verifyOrdering(ruleName, sanitized);
List<String> order = Utils.leafToRootOrderTopo(ruleName, sanitized);
composedRule.setDependency(order);
```

### Why it matters
- Dependency output becomes deterministic and validated before rendering.

---

## Stage G: LLM explanations path

### What it does
1. Resolves `<reportPath>/resources/llm_cache`.
2. If explanations enabled, runs `CrySLToLLMGenerator.generateExplanations(...)`.
3. Second pass per rule/language:
   - write cache file if missing,
   - otherwise read existing cache,
   - set final explanation map on `ComposedRule`.

### Important behavior
- Explanation attach is a two-step pattern:
  - generation step,
  - cache-reload/final-set step.

### Why it matters
- Gives reproducible cache behavior and keeps report output stable.

---

## Stage H: LLM secure/insecure example path

### What it does
For each rule:
1. resolve secure/insecure cache files in `code_cache`,
2. if generation enabled:
   - regenerate only if file missing or placeholder,
   - call `CrySLToLLMGenerator.generateExample(...)`,
   - clean markdown fences with `cleanLLMCodeBlock(...)`,
   - write files,
3. if generation disabled:
   - reuse cache if present,
   - else write disabled placeholders,
4. attach secure/insecure code to `ComposedRule`,
5. collect failure markers for report.

### Core snippet: regenerate-on-placeholder
```java
boolean secureNeedsGeneration = existingSecure == null || isRetryablePlaceholder(existingSecure, true);
boolean insecureNeedsGeneration = existingInsecure == null || isRetryablePlaceholder(existingInsecure, false);
```

### Why it matters
- Avoids unnecessary LLM calls.
- Still recovers when cache contains failure/disabled placeholders.

---

## Stage I: Write codegen failure report

### What it does
```java
writeCodegenFailureReport(codeCacheDir, codegenFailures);
```
- Writes `llm_codegen_failures.txt` for this run.

### Why it matters
- You get a single per-run summary of code generation status.

---

## Stage J: FreeMarker rendering

### What it does
1. create `Configuration`,
2. setup FreeMarker,
3. create layout pages,
4. create sidebar,
5. create per-rule pages using all composed data.

### Code snippet
```java
FreeMarkerWriter.setupFreeMarker(cfg);
FreeMarkerWriter.createCogniCryptLayout(cfg);
FreeMarkerWriter.createSidebar(composedRuleList, cfg);
FreeMarkerWriter.createSinglePage(...);
```

### Why it matters
- This is where model data becomes final HTML output.

---

## Stage K: Optional copy of `.crysl` files into output

### What it does
- If `!docSettings.isBooleanF()`, copy rule files into report `rules/` folder.
- Source can be:
  - user rules directory, or
  - bundled resources extracted from JAR.

### Why it matters
- Useful when distributing generated docs together with rule files.

---

## Stage L: Final timing in `finally`

### What it does
```java
long end = System.nanoTime();
double elapsedMs = (end - start) / 1_000_000.0;
System.out.printf("Total execution time: %.3f ms (%.3f s)%n", elapsedMs, elapsedMs / 1000.0);
```

### Why it matters
- Always prints total run duration, even when exceptions occur.

---

## 5) Mini call-chain view

```text
main(...)
  -> DocSettings.parseSettingsFromCLI
  -> runStartupPreflight
  -> CrySLReader / CrySLRuleReader
  -> section builders (Order, Constraints*, Ensures, Negates, ClassEventForb)
  -> GraphSanitizer -> GraphVerification -> Utils.leafToRootOrderTopo
  -> CrySLToLLMGenerator -> LLMService -> Python sidecar (optional)
  -> FreeMarkerWriter
```

---

## 6) Important behaviors to remember

1. Explanation languages are currently hardcoded in this class.
2. Explanations use a two-pass attach pattern.
3. Example generation can regenerate on placeholder cache content.
4. Codegen failure report file is always written.
5. Rule loading supports both filesystem and bundled JAR resources.

---

## 7) Simple meeting-ready explanation

If you need one short explanation:

`DocumentGeneratorMain` is the central Java orchestrator. It reads settings and rules, builds every documentation section into `ComposedRule`, computes and verifies dependency order, optionally calls Python LLM sidecars for explanations and examples, manages report-scoped caches, writes a codegen failure report, and renders final HTML pages with FreeMarker.
