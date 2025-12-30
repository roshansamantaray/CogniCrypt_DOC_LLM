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

    private static final Path PROJECT_ROOT = Paths.get(System.getProperty("user.dir"));
    private static final Path VENV_PY_UNIX = PROJECT_ROOT.resolve(Paths.get("llm", ".venv", "bin", "python"));
    private static final Path VENV_PY_WIN  = PROJECT_ROOT.resolve(Paths.get("llm", ".venv", "Scripts", "python.exe"));

    private static boolean isWindows() {
        String os = System.getProperty("os.name", "").toLowerCase(Locale.ROOT);
        return os.contains("win");
    }

    private static String resolvePythonExecutable() {
        if (Files.isExecutable(VENV_PY_UNIX)) {
            return VENV_PY_UNIX.toString();
        }
        if (Files.isExecutable(VENV_PY_WIN)) {
            return VENV_PY_WIN.toString();
        }
        return isWindows() ? "python" : "python3";
    }

    public static Map<String, String> getLLMExplanation(Map<String, String> cryslData, List<String> LANGUAGES, String backend) throws IOException {
        Gson gson = new Gson();
        String pythonScriptPath = backend.equalsIgnoreCase("openai") ? "llm/llm_writer.py" : "llm/llm_writer_ollama.py";
        Map<String, String> result = new HashMap<>();

        Path base = PROJECT_ROOT.resolve("llm");
        Path tempFolder = base.resolve("temp_rules");
        Path sanitizedFolder = base.resolve("sanitized_rules");
        Files.createDirectories(base);
        Files.createDirectories(tempFolder);
        Files.createDirectories(sanitizedFolder);

        Path cacheFolder = PROJECT_ROOT.resolve("Output").resolve("resources").resolve("llm_cache");
        Files.createDirectories(cacheFolder);

        String pythonPath = resolvePythonExecutable();

        for (String lang: LANGUAGES) {
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

            Path cacheFile = cacheFolder.resolve(classNameSafe + "_" + lang + ".txt");
            if (Files.exists(cacheFile)) {
                String cached = Files.readString(cacheFile, StandardCharsets.UTF_8);
                result.put(lang, cached.trim());
                continue; // skip Python process
            }

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

    public static String getLLMExample(Map<String, String> cryslData, String type) throws IOException {
        cryslData.put("exampleType", type);
        Gson gson = new Gson();
        String json = gson.toJson(cryslData);

        Path tempFile = PROJECT_ROOT.resolve("llm").resolve("temp_example_" + type + ".json");
        Files.createDirectories(tempFile.getParent());
        try (OutputStreamWriter writer = new OutputStreamWriter(Files.newOutputStream(tempFile), StandardCharsets.UTF_8)) {
            writer.write(json);
        }

        String pythonScriptPath = "llm/llm_code_writer_" + type + ".py";
        String pythonPath = resolvePythonExecutable();
        ProcessBuilder pb = new ProcessBuilder(pythonPath, pythonScriptPath, tempFile.toString());
        pb.directory(PROJECT_ROOT.toFile());
        pb.redirectErrorStream(true);

        Process process = pb.start();
        StringBuilder output = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                output.append(line).append('\n');
            }
        }

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

