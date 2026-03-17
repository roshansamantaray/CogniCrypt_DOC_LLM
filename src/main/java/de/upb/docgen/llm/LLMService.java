package de.upb.docgen.llm;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.regex.Pattern;
import java.util.concurrent.TimeUnit;
import com.google.gson.Gson;
import de.upb.docgen.utils.Utils;

/**
 * Author: Roshan Samantaray
 **/

public class LLMService {

    // Resolve project-relative paths for the LLM sidecar scripts and caches.
    private static final Path PROJECT_ROOT = Paths.get(System.getProperty("user.dir"));
    private static final Path VENV_PY_UNIX = PROJECT_ROOT.resolve(Paths.get(".venv", "bin", "python"));
    private static final Path VENV_PY_WIN  = PROJECT_ROOT.resolve(Paths.get(".venv", "Scripts", "python.exe"));

    /**
     * Detect whether the current OS is Windows for Python fallback selection.
     */
    private static boolean isWindows() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        return os.contains("win");
    }

    /**
     * Resolve the Python executable, preferring the project venv if present.
     */
    private static String resolvePythonExecutable() {
        if (Files.isExecutable(VENV_PY_UNIX)) {
            return VENV_PY_UNIX.toString();
        }
        if (Files.isExecutable(VENV_PY_WIN)) {
            return VENV_PY_WIN.toString();
        }
        return isWindows() ? "python" : "python3";
    }

    /**
     * Build a javac compile classpath from runtime classpath plus local build outputs.
     */
    private static String buildCompileClasspath() {
        LinkedHashSet<String> entries = new LinkedHashSet<>();
        String cp = System.getProperty("java.class.path", "");
        if (cp != null && !cp.isBlank()) {
            for (String part : cp.split(Pattern.quote(File.pathSeparator))) {
                String trimmed = part == null ? "" : part.trim();
                if (!trimmed.isEmpty()) {
                    entries.add(trimmed);
                }
            }
        }

        Path targetClasses = PROJECT_ROOT.resolve(Paths.get("target", "classes"));
        if (Files.exists(targetClasses)) {
            entries.add(targetClasses.toAbsolutePath().toString());
        }

        Path libDir = PROJECT_ROOT.resolve(Paths.get("target", "lib"));
        if (Files.isDirectory(libDir)) {
            try {
                try (var stream = Files.list(libDir)) {
                    stream
                        .filter(p -> p.getFileName().toString().endsWith(".jar"))
                        .sorted()
                        .forEach(p -> entries.add(p.toAbsolutePath().toString()));
                }
            } catch (IOException ignored) {
                // Best-effort classpath enrichment; keep existing entries.
            }
        }

        return String.join(File.pathSeparator, entries);
    }

    /**
     * Resolve javac --release value from the running JVM, defaulting to 21.
     */
    private static String resolveJavaRelease() {
        String spec = System.getProperty("java.specification.version", "21").trim();
        if (spec.contains(".")) {
            String[] parts = spec.split("\\.");
            return parts[parts.length - 1];
        }
        return spec.isEmpty() ? "21" : spec;
    }

    /**
     * Resolve javac from the running JVM's java.home when possible.
     */
    private static String resolveJavacBinary() {
        Path javaHome = Paths.get(System.getProperty("java.home", ""));
        Path javac = javaHome.resolve(Paths.get("bin", isWindows() ? "javac.exe" : "javac"));
        if (Files.isExecutable(javac)) {
            return javac.toAbsolutePath().toString();
        }
        return "javac";
    }

    /**
     * Generate multilingual explanations via the Python LLM sidecar with caching.
     */
    public static Map<String, String> getLLMExplanation(Map<String, String> cryslData, List<String> LANGUAGES, String backend) throws IOException {
        Gson gson = new Gson();
        // Choose backend-specific Python script.
        String pythonScriptPath;
        if (backend.equalsIgnoreCase("openai")) {
            pythonScriptPath = "llm/llm_writer.py";
        } else if (backend.equalsIgnoreCase("gateway")) {
            pythonScriptPath = "llm/llm_writer_gateway.py";
        } else {
            throw new IOException("Unsupported LLM backend: " + backend);
        }
        Map<String, String> result = new HashMap<>();

        // Prepare temp/sanitized folders under llm/.
        Path base = PROJECT_ROOT.resolve("llm");
        Path tempFolder = base.resolve("temp_rules");
        Path sanitizedFolder = base.resolve("sanitized_rules");
        Files.createDirectories(base);
        Files.createDirectories(tempFolder);
        Files.createDirectories(sanitizedFolder);

        // Cache folder for explanation outputs.
        Path cacheFolder = PROJECT_ROOT.resolve("Output").resolve("resources").resolve("llm_cache");
        Files.createDirectories(cacheFolder);

        String pythonPath = resolvePythonExecutable();

        for (String lang: LANGUAGES) {
            // Add language to the payload and create a sanitized JSON input.
            cryslData.put("explanationLanguage", lang);

            String className = cryslData.get("className");
            String classNameSafe = className.replaceAll("[^a-zA-Z0-9.\\-]", "_");
            String json = gson.toJson(cryslData);
            Path tempIn = tempFolder.resolve("temp_rule_" + classNameSafe + "_" + lang + ".json");
            if (!Files.exists(tempIn)) {
                try (OutputStreamWriter writer = new OutputStreamWriter(Files.newOutputStream(tempIn), StandardCharsets.UTF_8)) {
                    writer.write(json);
                }
            }
            Path sanitizedOut = sanitizedFolder.resolve("sanitized_rule_" + classNameSafe + "_" + lang + ".json");
            if (!Files.exists(sanitizedOut)) {
                Utils.sanitizeRuleFileSecure(tempIn, sanitizedOut, base);
            }

            // Use cached explanation if available.
            Path cacheFile = cacheFolder.resolve(classNameSafe + "_" + lang + ".txt");
            if (Files.exists(cacheFile)) {
                String cached = Files.readString(cacheFile, StandardCharsets.UTF_8);
                result.put(lang, cached.trim());
                continue; // skip Python process
            }

            // Spawn the Python process for the selected backend.
            ProcessBuilder pb = new ProcessBuilder(
                    pythonPath,
                    pythonScriptPath,
                    className,
                    lang
            );
            File projectRoot = PROJECT_ROOT.toFile();
            pb.directory(projectRoot);
            pb.redirectErrorStream(true);
            pb.environment().put("PYTHONIOENCODING", "utf-8");

            Process process = pb.start();
            StringBuilder output = new StringBuilder();
            try (BufferedReader reader =
                         new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    output.append(line).append('\n');
                }
            }

            // Enforce a time limit for LLM calls.
            try {
                boolean finished = process.waitFor(60, TimeUnit.SECONDS);
                if (!finished) {
                    process.destroyForcibly();
                    throw new IOException("LLM python process timed out for " + className + " / " + lang);
                }
                int exit = process.exitValue();
                if (exit != 0) {
                    // still return output, but annotate or throw depending on desired behavior
                    throw new IOException("LLM python process exited with code " + exit + " for " + className + " / " + lang + ". Output: " + output.toString());
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IOException("Interrupted while waiting for LLM python process", e);
            }

            String outStr = output.toString().trim();
            result.put(lang, outStr);
            // cache write (optional)
            try (OutputStreamWriter cw = new OutputStreamWriter(Files.newOutputStream(cacheFile), StandardCharsets.UTF_8)) {
                cw.write(outStr);
            } catch (IOException ignored) {
                // non-fatal: caching failure shouldn't break main flow
            }
        }
        return result;
    }

    /**
     * Generate a secure or insecure example via the Python sidecar.
     */
    public static String getLLMExample(Map<String, String> cryslData, String type) throws IOException {
        // Mark the request type (secure/insecure) and write a temp JSON input.
        cryslData.put("exampleType", type);
        Gson gson = new Gson();
        String json = gson.toJson(cryslData);

        Path tempFile = PROJECT_ROOT.resolve("llm").resolve("temp_example_" + type + ".json");
        Files.createDirectories(tempFile.getParent());
        try (OutputStreamWriter writer = new OutputStreamWriter(Files.newOutputStream(tempFile), StandardCharsets.UTF_8)) {
            writer.write(json);
        }

        // Call the Python generator for the example type.
        String pythonScriptPath = "llm/llm_code_writer_" + type + ".py";
        String pythonPath = resolvePythonExecutable();
        String rulesDir = Paths.get("src", "main", "resources", "CrySLRules")
                .toAbsolutePath()
                .toString();

        List<String> command = new ArrayList<>(List.of(
                pythonPath,
                pythonScriptPath,
                tempFile.toString(),
                "--rules-dir", rulesDir
        ));
        if ("secure".equalsIgnoreCase(type)) {
            command.add("--compile-classpath");
            command.add(buildCompileClasspath());
            command.add("--java-release");
            command.add(resolveJavaRelease());
        }

        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(PROJECT_ROOT.toFile());
        pb.redirectErrorStream(true);
        if ("secure".equalsIgnoreCase(type)) {
            pb.environment().put("JAVAC_BIN", resolveJavacBinary());
        }

        Process process = pb.start();
        StringBuilder output = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                output.append(line).append('\n');
            }
        }

        // Enforce a time limit for example generation.
        try {
            boolean finished = process.waitFor(60, TimeUnit.SECONDS);
            if (!finished) {
                process.destroyForcibly();
                throw new IOException("LLM python example process timed out for type " + type);
            }
            int exit = process.exitValue();
            if (exit != 0) {
                throw new IOException("LLM python example process exited with code " + exit + ". Output: " + output.toString());
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while waiting for LLM python example process", e);
        }

        return output.toString().trim();
    }

}
