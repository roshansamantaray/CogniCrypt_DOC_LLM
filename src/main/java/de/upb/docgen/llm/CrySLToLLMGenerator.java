package de.upb.docgen.llm;

import crypto.interfaces.ICrySLPredicateParameter;
import crypto.rules.CrySLRule;
import de.upb.docgen.ComposedRule;
import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import crypto.rules.CrySLPredicate;

/**
 * @author Roshan Samantaray
 **/

public class CrySLToLLMGenerator {

    private static final List<String> LANGUAGES = List.of("English", "Portuguese", "German", "French");

    public static void generateExplanations(List<ComposedRule> composedRuleList, List<CrySLRule> cryslRuleList) {
        for (int i = 0; i < composedRuleList.size(); i++) {
            ComposedRule composedRule = composedRuleList.get(i);
            CrySLRule cryslRule = cryslRuleList.get(i);

            Map<String, String> cryslData = new HashMap<>();

            // Class name from SPEC
            cryslData.put("className", composedRule.getComposedClassName());

            // OBJECTS

            List<Map.Entry<String, String>> objectEntries = cryslRule.getObjects();
            StringBuilder objectBuilder = new StringBuilder();

            for (Map.Entry<String, String> entry : objectEntries) {
                objectBuilder.append(entry.getValue())  // type
                        .append(" ")
                        .append(entry.getKey())    // variable name
                        .append(", ");
            }

            String objects = objectBuilder.toString().trim();
            if (objects.endsWith(",")) {
                objects = objects.substring(0, objects.length() - 1);
            }

            cryslData.put("objects", objects.isEmpty() ? "None" : objects);

            // EVENTS (approximate using number of methods)
            String events = composedRule.getNumberOfMethods();
            cryslData.put("events", events != null ? String.join(", ", events) : "N/A");

            // ORDER

            List<String> orderList = composedRule.getOrder();
            String order = "N/A";

            if (orderList != null && !orderList.isEmpty()) {
                StringBuilder orderBuilder = new StringBuilder();
                for (String part : orderList) {
                    orderBuilder.append(part).append(", ");
                }

                order = orderBuilder.toString().trim();

                if (order.endsWith(",")) {
                    order = order.substring(0, order.length() - 1);
                }
            }

            
            cryslData.put("order", order);

            // CONSTRAINTS
            List<String> constraints = composedRule.getAllConstraints();
            cryslData.put("constraints", constraints != null ? String.join(", ", constraints) : "N/A");

            // REQUIRES
            List<CrySLPredicate> requiredPredicates = cryslRule.getRequiredPredicates();
            StringBuilder requiresBuilder = new StringBuilder();

            for (CrySLPredicate pred : requiredPredicates) {
                String formatted = formatPredicate(pred);
                requiresBuilder.append(formatted).append(", ");
            }

            String requires = requiresBuilder.toString().trim();
            if (requires.endsWith(",")) {
                requires = requires.substring(0, requires.length() - 1);
            }

            cryslData.put("requires", requires.isEmpty() ? "None" : requires);

            // DEPENDENCY (list of class names this rule depends on, usually providers in leaf->root order excluding self)
            List<String> dependency = composedRule.getDependency();
            cryslData.put("dependency", dependency != null ? String.join(", ", dependency) : "N/A");

//            List<String> deps = composedRule.getDependency();
//            if (deps != null && !deps.isEmpty()) {
//                // Exclude self if present at end
//                cryslData.put("dependency", String.join(", ", deps));
//            } else {
//                cryslData.put("dependency", composedRule.getDependency().toString());
//            }

            // ENSURES
            List<String> ensures = composedRule.getEnsuresPredicates();
            List<String> ensuresThisPredicate = composedRule.getEnsuresThisPredicates();
            List<String> ensuresCombined = new java.util.ArrayList<>();
            if (ensuresThisPredicate != null) ensuresCombined.addAll(ensuresThisPredicate);
            if (ensures != null) ensuresCombined.addAll(ensures);
            cryslData.put("ensures", ensuresCombined.isEmpty() ? "N/A" : String.join(", ", ensuresCombined));

            // FORBIDDEN METHODS
            List<String> forbidden = composedRule.getForbiddenMethods();
            cryslData.put("forbidden", forbidden != null ? String.join(", ", forbidden) : "N/A");

            // Call LLMService
            try {
                Map<String, String> explanation = LLMService.getLLMExplanation(cryslData, LANGUAGES);
                composedRule.setLlmExplanation(explanation);
                Map<String, String> answer = composedRule.getLlmExplanation();
            } catch (IOException e) {
                System.err.println("LLM generation failed for " + cryslData.get("className"));
                e.printStackTrace();
            }
        }
    }

    public static void generateExample (List<ComposedRule> composedRuleList, List<CrySLRule> crySLRuleList) {
        for (int i = 0; i < composedRuleList.size(); i++) {
            ComposedRule composedRule = composedRuleList.get(i);
            CrySLRule cryslRule = crySLRuleList.get(i);

            Map<String, String> cryslData = new HashMap<>();

            // Class name from SPEC
            cryslData.put("className", composedRule.getComposedClassName());

            // OBJECTS

            List<Map.Entry<String, String>> objectEntries = cryslRule.getObjects();
            StringBuilder objectBuilder = new StringBuilder();

            for (Map.Entry<String, String> entry : objectEntries) {
                objectBuilder.append(entry.getValue())  // type
                        .append(" ")
                        .append(entry.getKey())    // variable name
                        .append(", ");
            }

            String objects = objectBuilder.toString().trim();
            if (objects.endsWith(",")) {
                objects = objects.substring(0, objects.length() - 1);
            }

            cryslData.put("objects", objects.isEmpty() ? "None" : objects);

            // EVENTS (approximate using number of methods)
            String events = composedRule.getNumberOfMethods();
            cryslData.put("events", events != null ? String.join(", ", events) : "N/A");

            // ORDER

            List<String> orderList = composedRule.getOrder();
            String order = "N/A";

            if (orderList != null && !orderList.isEmpty()) {
                StringBuilder orderBuilder = new StringBuilder();
                for (String part : orderList) {
                    orderBuilder.append(part).append(", ");
                }

                order = orderBuilder.toString().trim();

                if (order.endsWith(",")) {
                    order = order.substring(0, order.length() - 1);
                }
            }

            cryslData.put("order", order);

            // CONSTRAINTS
            List<String> constraints = composedRule.getAllConstraints();
            cryslData.put("constraints", constraints != null ? String.join(", ", constraints) : "N/A");

            // REQUIRES
            List<CrySLPredicate> requiredPredicates = cryslRule.getRequiredPredicates();
            StringBuilder requiresBuilder = new StringBuilder();

            for (CrySLPredicate pred : requiredPredicates) {
                String formatted = formatPredicate(pred);
                requiresBuilder.append(formatted).append(", ");
            }

            String requires = requiresBuilder.toString().trim();
            if (requires.endsWith(",")) {
                requires = requires.substring(0, requires.length() - 1);
            }

            cryslData.put("requires", requires.isEmpty() ? "None" : requires);

            // ENSURES
            List<String> ensures = composedRule.getEnsuresPredicates();
            cryslData.put("ensures", ensures != null ? String.join(", ", ensures) : "N/A");

            // FORBIDDEN METHODS
            List<String> forbidden = composedRule.getForbiddenMethods();
            cryslData.put("forbidden", forbidden != null ? String.join(", ", forbidden) : "N/A");

            try {
                String secure = LLMService.getLLMExample(new HashMap<>(cryslData), "secure");
                String insecure = LLMService.getLLMExample(new HashMap<>(cryslData), "insecure");

                composedRule.setSecureExample(secure);
                composedRule.setInsecureExample(insecure);

            } catch (IOException e) {
                System.err.println("LLM Code generation failed for " + cryslData.get("className"));
                e.printStackTrace();
            }
        }
    }

    public static String cleanLLMCodeBlock(String rawOutput) {
        if (rawOutput == null) return "";

        return rawOutput
                .replaceAll("(?i)```\\s*java", "")  // remove ```java
                .replaceAll("(?i)```", "")          // remove any remaining ```
                .replaceAll("(?m)^\\s+", "")
                .trim();
    }


    private static String formatPredicate(CrySLPredicate pred) {
        String name = pred.getPredName(); // correct method name
        StringBuilder paramsBuilder = new StringBuilder();

        for (ICrySLPredicateParameter param : pred.getParameters()) {
            paramsBuilder.append(param.toString()).append(", ");
        }

        String params = paramsBuilder.toString().trim();
        if (params.endsWith(",")) {
            params = params.substring(0, params.length() - 1);
        }

        return name + "[" + params + "]";
    }


}
