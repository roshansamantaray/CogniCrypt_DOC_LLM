package de.upb.docgen.llm;

import java.io.*;
import java.util.*;
import com.google.gson.Gson;

/**
 * @author Roshan Samantaray
 **/

public class LLMService {

    private static final String pythonPath = "C:\\Users\\rosha\\anaconda3\\envs\\cognicrypt_doc_llm-env\\python.exe";

    public static String getLLMExplanation(Map<String, String> cryslData) throws IOException {
        Gson gson = new Gson();
        String json = gson.toJson(cryslData);

        // Write JSON to a temporary file
        String tempFilePath = "llm/temp_rule.json";
        try (FileWriter writer = new FileWriter(tempFilePath)) {
            writer.write(json);
        }

        String pythonScriptPath = "llm/llm_writer.py";



        ProcessBuilder pb = new ProcessBuilder(pythonPath, pythonScriptPath, tempFilePath);
        pb.redirectErrorStream(true);

        Process process = pb.start();

        BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
        StringBuilder output = new StringBuilder();
        String line;
        while((line = reader.readLine()) != null) {
            output.append(line).append("\n");
        }
        return output.toString().trim();
    }

    public static String getLLMExample(Map<String, String> cryslData, String type) throws IOException {
        cryslData.put("exampleType", type);
        Gson gson = new Gson();
        String json = gson.toJson(cryslData);

        String tempFilePath = "llm/temp_example_" + type +".json";
        try (FileWriter writer = new FileWriter(tempFilePath)) {
            writer.write(json);
        }

        String pythonScriptPath = "llm/llm_code_writer_"+ type + ".py";
        ProcessBuilder pb = new ProcessBuilder(pythonPath, pythonScriptPath, tempFilePath);
        pb.redirectErrorStream(true);

        Process process = pb.start();

        BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
        StringBuilder output = new StringBuilder();
        String line;
        while ((line = reader.readLine()) != null) {
            output.append(line).append("\n");
        }
        return output.toString().trim();
    }

}
