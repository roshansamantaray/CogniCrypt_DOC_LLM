package de.upb.docgen.llm;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
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

    private static String sanitizeCacheToken(String value, String fallback) {
        String raw = value == null ? "" : value.trim();
        String cleaned = raw.replaceAll("[^a-zA-Z0-9._-]+", "_").replaceAll("^[_\\.-]+|[_\\.-]+$", "");
        return cleaned.isEmpty() ? fallback : cleaned;
    }

    private static String envOrDefault(String envName, String fallback) {
        String value = System.getenv(envName);
        if (value == null || value.trim().isEmpty()) {
            return fallback;
        }
        return value.trim();
    }

    private static String explanationChatModel(String backend) {
        if ("gateway".equalsIgnoreCase(backend)) {
            return envOrDefault("GATEWAY_CHAT_MODEL", "gwdg.llama-3.3-70b-instruct");
        }
        return "gpt-4o-mini";
    }

    private static String explanationEmbeddingModel(String backend) {
        if ("gateway".equalsIgnoreCase(backend)) {
            return envOrDefault("GATEWAY_EMB_MODEL", "YOUR_EMBEDDING_MODEL");
        }
        return "text-embedding-3-small";
    }

    public static String explanationCacheFileName(String classNameSafe, String lang, String backend) {
        String backendTag = sanitizeCacheToken(backend, "backend");
        String chatModelTag = sanitizeCacheToken(explanationChatModel(backend), "chat");
        String embModelTag = sanitizeCacheToken(explanationEmbeddingModel(backend), "emb");
        String langTag = sanitizeCacheToken(lang, "lang");
        return classNameSafe + "__expl__" + backendTag + "__" + chatModelTag + "__" + embModelTag + "__" + langTag + ".txt";
    }

    public static String exampleCacheFileName(String classNameSafe, String mode) {
        String providerTag = "openai";
        String modelTag = sanitizeCacheToken("gpt-4o-mini", "model");
        String modeTag = sanitizeCacheToken(mode, "mode");
        return classNameSafe + "__example__" + providerTag + "__" + modelTag + "__" + modeTag + ".txt";
    }

    private static String executeProcessWithTimeout(
            ProcessBuilder processBuilder,
            long timeoutSeconds,
            String timeoutErrorMessage,
            String nonZeroExitErrorPrefix
    ) throws IOException {
        Process process = processBuilder.start();
        StringBuffer output = new StringBuffer();

        Thread outputReader = new Thread(() -> {
            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    output.append(line).append('\n');
                }
            } catch (IOException ignored) {
                // Best effort capture; process exit handling is authoritative.
            }
        }, "llm-process-output-reader");
        outputReader.setDaemon(true);
        outputReader.start();

        final boolean finished;
        try {
            finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            process.destroyForcibly();
            Thread.currentThread().interrupt();
            throw new IOException("Interrupted while waiting for LLM python process", e);
        }

        if (!finished) {
            process.destroyForcibly();
            try {
                outputReader.join(2000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            throw new IOException(timeoutErrorMessage + ". Partial output: " + output);
        }

        try {
            outputReader.join(2000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }

        int exit = process.exitValue();
        if (exit != 0) {
            throw new IOException(nonZeroExitErrorPrefix + exit + ". Output: " + output);
        }
        return output.toString().trim();
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
            try (OutputStreamWriter writer = new OutputStreamWriter(Files.newOutputStream(tempIn), StandardCharsets.UTF_8)) {
                writer.write(json);
            }
            Path sanitizedOut = sanitizedFolder.resolve("sanitized_rule_" + classNameSafe + "_" + lang + ".json");
            Utils.sanitizeRuleFileSecure(tempIn, sanitizedOut, base);

            // Use cached explanation if available.
            Path cacheFile = cacheFolder.resolve(explanationCacheFileName(classNameSafe, lang, backend));
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
            String outStr = executeProcessWithTimeout(
                    pb,
                    60,
                    "LLM python process timed out for " + className + " / " + lang,
                    "LLM python process exited with code for " + className + " / " + lang + ": "
            );
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

        ProcessBuilder pb = new ProcessBuilder(
                pythonPath,
                pythonScriptPath,
                tempFile.toString(),
                "--rules-dir", rulesDir
        );
        pb.directory(PROJECT_ROOT.toFile());
        pb.redirectErrorStream(true);
        return executeProcessWithTimeout(
                pb,
                60,
                "LLM python example process timed out for type " + type,
                "LLM python example process exited with code "
        );
    }

}
