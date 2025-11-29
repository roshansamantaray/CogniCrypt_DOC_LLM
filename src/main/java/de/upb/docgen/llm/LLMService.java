//package de.upb.docgen.llm;
//
//import java.io.*;
//import java.nio.charset.StandardCharsets;
//import java.nio.file.Files;
//import java.nio.file.Path;
//import java.nio.file.Paths;
//import java.util.*;
//import com.google.gson.Gson;
//import de.upb.docgen.utils.Utils;
//
///**
// * @author Roshan Samantaray
// **/
//
//public class LLMService {
//
//    private static final String pythonPath = "llm/.venv/Scripts/python.exe";
//
//    public static Map<String, String> getLLMExplanation(Map<String, String> cryslData, List<String> LANGUAGES) throws IOException {
//        Gson gson = new Gson();
//        String pythonScriptPath = "llm/llm_writer.py";
//        Map<String, String> result = new HashMap<>();
//
//        Path base = Paths.get("llm");
//        Path tempFolder = base.resolve("temp_rules");
//        Path sanitizedFolder = base.resolve("sanitized_rules");
//        Files.createDirectories(base);
//        Files.createDirectories(tempFolder);
//        Files.createDirectories(sanitizedFolder);
//
//        Path cacheFolder = Paths.get("C:\\Users\\rosha\\Documents\\CogniCrypt_DOC_LLM\\CogniCrypt_DOC_LLM\\Output\\resources\\llm_cache");
//        Files.createDirectories(cacheFolder);
//
//        for (String lang: LANGUAGES) {
//            cryslData.put("explanationLanguage", lang);
//
//            String className = cryslData.get("className");
//            String classNameSafe = className.replaceAll("[^a-zA-Z0-9.\\-]", "_");
//            String json = gson.toJson(cryslData);
//            Path tempIn = tempFolder.resolve("temp_rule_" + classNameSafe + "_" + lang + ".json");
//            if (!Files.exists(tempIn)) {
//                try (OutputStreamWriter writer = new OutputStreamWriter(Files.newOutputStream(tempIn), StandardCharsets.UTF_8)) {
//                    writer.write(json);
//                }
//            }
//            Path sanitizedOut = sanitizedFolder.resolve("sanitized_rule_" + className + "_" + lang + ".json");
//            if (!Files.exists(sanitizedOut)) {
//                Utils.sanitizeRuleFileSecure(tempIn, sanitizedOut, base);
//            }
//
//            Path cacheFile = cacheFolder.resolve(className + "_" + lang + ".txt");
//            if (Files.exists(cacheFile)) {
//                String cached = Files.readString(cacheFile, StandardCharsets.UTF_8);
//                result.put(lang, cached.trim());
//                continue; // skip Python process
//            }
//
//            ProcessBuilder pb = new ProcessBuilder(
//                    pythonPath,
//                    pythonScriptPath,
//                    className,
//                    lang
//            );
//            File projectRoot = new File("C:\\Users\\rosha\\Documents\\CogniCrypt_DOC_LLM\\CogniCrypt_DOC_LLM");
//            pb.directory(projectRoot);
//            pb.redirectErrorStream(true);
//
//            Process process = pb.start();
//            try (BufferedReader reader =
//                         new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
//                StringBuilder output = new StringBuilder();
//                String line;
//                while ((line = reader.readLine()) != null) {
//                    output.append(line).append('\n');
//                }
//                result.put(lang, output.toString().trim());
//            }
//        }
//        return result;
//    }
//
//    public static String getLLMExample(Map<String, String> cryslData, String type) throws IOException {
//        cryslData.put("exampleType", type);
//        Gson gson = new Gson();
//        String json = gson.toJson(cryslData);
//
//        String tempFilePath = "llm/temp_example_" + type +".json";
//        try (FileWriter writer = new FileWriter(tempFilePath)) {
//            writer.write(json);
//        }
//
//        String pythonScriptPath = "llm/llm_code_writer_"+ type + ".py";
//        ProcessBuilder pb = new ProcessBuilder(pythonPath, pythonScriptPath, tempFilePath);
//        pb.redirectErrorStream(true);
//
//        Process process = pb.start();
//
//        BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
//        StringBuilder output = new StringBuilder();
//        String line;
//        while ((line = reader.readLine()) != null) {
//            output.append(line).append("\n");
//        }
//        return output.toString().trim();
//    }
//
//}

// java
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
    private static final Path DEFAULT_PYTHON = Paths.get("llm", ".venv", "Scripts", "python.exe");

    private static String resolvePythonExecutable() {
        if (Files.exists(DEFAULT_PYTHON)) {
            return DEFAULT_PYTHON.toString();
        }
        return "python";
    }

    public static Map<String, String> getLLMExplanation(Map<String, String> cryslData, List<String> LANGUAGES) throws IOException {
        Gson gson = new Gson();
        String pythonScriptPath = "llm/llm_writer.py";
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

