package de.upb.docgen.utils;

import com.google.gson.*;
import crypto.interfaces.ICrySLPredicateParameter;
import crypto.rules.CrySLCondPredicate;
import crypto.rules.CrySLPredicate;
import crypto.rules.StateNode;
import crypto.rules.TransitionEdge;
import de.upb.docgen.ComposedRule;
import de.upb.docgen.DocSettings;

import java.io.*;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Utils {

    private static final class Frame {
        final String node;
        final boolean expanded;
        Frame(String node, boolean expanded) { this.node = node; this.expanded = expanded; }
    }

    private static final int MAX_BYTES = 2_000_000; // 2MB guard
    private static final Pattern TAG_PATTERN = Pattern.compile("(?s)<[^>]+>");
    private static final Pattern CONTROL_PATTERN = Pattern.compile("[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]");
    // Pattern to capture tooltip spans: outer label + inner tooltip text
    private static final Pattern TOOLTIP_PATTERN = Pattern.compile(
            "(?is)<span\\s+class=\"tooltip\">(.*?)<span\\s+class=\"tooltiptext\">(.*?)</span>\\s*</span>"
    );

    private static final Gson GSON = new GsonBuilder().disableHtmlEscaping().setPrettyPrinting().create();
    private static final Set<String> ALLOWED_KEYS = Set.of(
            "className","objects","ensures","constraints","requires","order","events","forbidden","explanationLanguage","dependency"
    );

    /**
     * Secure sanitizer entry.
     * @param input path to noisy JSON
     * @param output path to cleaned JSON
     * @param baseDir base directory to confine IO (e.g. Paths.get("llm"))
     * @return cleaned JSON string
     * @throws IOException on IO errors
     */
    public static String sanitizeRuleFileSecure(Path input, Path output, Path baseDir) throws IOException {
        Objects.requireNonNull(input, "input");
        Objects.requireNonNull(output, "output");
        Objects.requireNonNull(baseDir, "baseDir");
        enforceUnderBase(input, baseDir);
        enforceUnderBase(output, baseDir);

        byte[] rawBytes = Files.readAllBytes(input);
        if (rawBytes.length > MAX_BYTES) {
            throw new IOException("Input exceeds limit: " + rawBytes.length);
        }
        String raw = new String(rawBytes, StandardCharsets.UTF_8);

        // Pre-clean
        String cleaned = preClean(raw);

        JsonObject source = parseLenient(cleaned);

        // Build normalized object
        JsonObject out = new JsonObject();
        out.addProperty("className", cleanScalar(optString(source, "className")));
        out.add("objects", toJsonArray(splitList(optString(source, "objects"))));
        out.add("ensures", toJsonArray(splitSentences(cleanScalar(optString(source, "ensures")))));
        out.add("constraints", toJsonArray(splitSentences(cleanScalar(optString(source, "constraints")))));
        out.add("requires", toJsonArray(autoListOrSentences(cleanScalar(optString(source, "requires")))));
        out.addProperty("order", cleanScalar(optString(source, "order")));
        out.addProperty("events", cleanScalar(optString(source, "events")));
        out.add("forbidden", toJsonArray(autoListOrSentences(cleanScalar(optString(source, "forbidden")))));
        // New: preserve explanationLanguage if present
        out.addProperty("explanationLanguage", cleanScalar(optString(source, "explanationLanguage")));
        // New: dependencies list (optional)
        out.add("dependency", toJsonArray(splitList(optString(source, "dependency"))));

        // De-duplicate arrays
        dedupeArray(out, "objects");
        dedupeArray(out, "ensures");
        dedupeArray(out, "constraints");
        dedupeArray(out, "requires");
        dedupeArray(out, "forbidden");
        dedupeArray(out, "dependency");

        String json = GSON.toJson(out);
        if (output.getParent() != null) Files.createDirectories(output.getParent());
        Files.writeString(output, json, StandardCharsets.UTF_8,
                StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
        return json;
    }

    private static void enforceUnderBase(Path path, Path base) throws IOException {
        Path normBase = base.toRealPath();
        Path norm = path.toAbsolutePath().normalize();
        if (!norm.startsWith(normBase)) {
            throw new IOException("Path escapes base: " + path);
        }
    }

    private static String preClean(String s) {
        // Remove null bytes & control chars
        s = s.replace("\u0000", "");
        s = CONTROL_PATTERN.matcher(s).replaceAll("");
        return s;
    }

    private static JsonObject parseLenient(String s) {
        try {
            JsonElement el = JsonParser.parseString(s);
            if (el.isJsonObject()) return el.getAsJsonObject();
        } catch (Exception ignored) {}
        // Fallback: attempt to wrap as single field if raw text
        JsonObject obj = new JsonObject();
        obj.addProperty("ensures", s);
        return obj;
    }

    private static String optString(JsonObject o, String key) {
        if (o == null || !o.has(key) || o.get(key).isJsonNull()) return "";
        if (o.get(key).isJsonPrimitive()) return o.get(key).getAsString();
        return o.get(key).toString();
    }

    private static String stripHtml(String in) {
        if (in == null || in.isEmpty()) return "";
        return TAG_PATTERN.matcher(in).replaceAll(" ");
    }

    private static String unescapeBasicEntities(String s) {
        if (s == null) return "";
        return s.replace("&lt;","<")
                .replace("&gt;",">")
                .replace("&amp;","&")
                .replace("&quot;","\"")
                .replace("&#39;","'")
                .replace("&apos;","'");
    }

    private static String normalizeWs(String s) {
        return s == null ? "" : s.replaceAll("\\s+", " ").trim();
    }

    // Expand tooltip HTML to: Label {Tooltip text}
    private static String expandTooltips(String s) {
        if (s == null || s.isEmpty()) return "";
        Matcher m = TOOLTIP_PATTERN.matcher(s);
        StringBuffer sb = new StringBuffer();
        while (m.find()) {
            String label = normalizeWs(stripHtml(m.group(1)));
            String tip = normalizeWs(stripHtml(m.group(2)));
            String replacement = label + " {" + tip + "}";
            m.appendReplacement(sb, Matcher.quoteReplacement(replacement));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    private static String cleanScalar(String s) {
        s = expandTooltips(s); // convert tooltips before stripping remaining HTML
        return normalizeWs(unescapeBasicEntities(stripHtml(s)));
    }

    private static List<String> splitList(String s) {
        List<String> out = new ArrayList<>();
        if (s == null || s.isBlank()) return out;
        for (String part : s.split("[,;]")) {
            String c = normalizeWs(part);
            if (!c.isEmpty()) out.add(c);
        }
        return out;
    }

    private static List<String> splitSentences(String s) {
        List<String> out = new ArrayList<>();
        if (s == null || s.isBlank()) return out;
        // Conservative sentence split: period followed by space or end
        String[] parts = s.split("(?<=[^.])\\.(?=\\s|$)");
        for (String p : parts) {
            String c = normalizeWs(p);
            if (!c.isEmpty()) {
                if (!c.endsWith(".")) c += ".";
                out.add(c);
            }
        }
        return out;
    }

    private static List<String> autoListOrSentences(String s) {
        if (s == null || s.isBlank()) return Collections.emptyList();
        int commas = s.length() - s.replace(",","").length();
        int periods = s.length() - s.replace(".","").length();
        if (commas > 0 && periods <= commas) return splitList(s);
        return splitSentences(s);
    }

    private static JsonArray toJsonArray(List<String> items) {
        JsonArray arr = new JsonArray();
        for (String i : items) {
            if (i != null && !i.isBlank()) arr.add(i);
        }
        return arr;
    }

    private static void dedupeArray(JsonObject o, String key) {
        if (!o.has(key) || !o.get(key).isJsonArray()) return;
        JsonArray arr = o.getAsJsonArray(key);
        LinkedHashSet<String> seen = new LinkedHashSet<>();
        for (JsonElement e : arr) if (e.isJsonPrimitive()) seen.add(e.getAsString());
        JsonArray rebuilt = new JsonArray();
        for (String v : seen) rebuilt.add(v);
        o.add(key, rebuilt);
    }

//    /* =================== Convenience runner =================== */
//    public static void mainSanitizerSecure(String[] args) throws Exception {
//        Path base = Paths.get("llm");
//        Path in = base.resolve("temp_rule_English.json");
//        Path out = base.resolve("clean_keypair_rule.json");
//        String result = sanitizeRuleFileSecure(in, out, base);
//        System.out.println("Secure sanitized JSON written: " + out + " (" + result.length() + " chars)");
//    }

    public static File getFileFromResources(String fileName) {
        URL resource = Utils.class.getResource(fileName);
        if (resource == null) {
            throw new IllegalArgumentException("File could not be found!");
        } else {
            return new File(resource.getFile());
        }
    }

	public static String replaceLast(String string, String toReplace, String replacement) {
		int pos = string.lastIndexOf(toReplace);
		if (pos > -1) {
			return string.substring(0, pos)
					+ replacement
					+ string.substring(pos + toReplace.length());
		} else {
			return string;
		}
	}

	public static List<TransitionEdge> getOutgoingEdges(Collection<TransitionEdge> collection, final StateNode curNode, final StateNode notTo) {
		final List<TransitionEdge> outgoingEdges = new ArrayList<>();
		for (final TransitionEdge comp : collection) {
			if (comp.getLeft().equals(curNode) && !(comp.getRight().equals(curNode) || comp.getRight().equals(notTo))) {
				outgoingEdges.add(comp);
			}
		}
		return outgoingEdges;
	}

	/**
	 * This method extracts and maps the corresponding predicates by classname
	 * @param mappedPredicates
	 * @return Map(k: className, v: Set(Corresponding classnames)
	 */
	public static Map<String, Set<String>> toOnlyClassNames(Map<String, List<Map<String, List<String>>>> mappedPredicates) {
		Map<String, Set<String>> onlyClassNamesMap = new HashMap<>();
		for (String classname : mappedPredicates.keySet()) {
			Set<String> setToRemoveDuplicates = new HashSet<>();
			for (Map<String, List<String>> stringListMap : mappedPredicates.get(classname)) {
				List<String> temp = new ArrayList<>();
				for (String predicate : stringListMap.keySet()) {
					List<String> dependingClassNames = new ArrayList<>();
					for (String classnameToAdd : stringListMap.get(predicate)) {
						dependingClassNames.add(classnameToAdd);
					}
					temp.addAll(dependingClassNames);
				}
				setToRemoveDuplicates.addAll(temp);
			}
			onlyClassNamesMap.putIfAbsent(classname,setToRemoveDuplicates);
		}
		return onlyClassNamesMap;
	}

	public static Map<String, Set<String>> getConstraintPredicateAndVarnameMap(List<ComposedRule> composedRuleList, Map<String, List<CrySLPredicate>> mapEnsures) {
		Map<String, Set<String>> RuleMappedToEnsures = new HashMap<>();
		for (ComposedRule rule : composedRuleList) {
			List<String> requiredPredicates = rule.getConstrainedPredicates();
			Set<String> valuesToAdd = new HashSet<>();
			String temp ="";
			for (String rp : requiredPredicates) {
				String predicateName = rp.substring(rp.lastIndexOf(' ') + 1).trim();
				String predicated = predicateName.substring(0, predicateName.length()-1);
				temp = predicated;
				for (Map.Entry<String, List<CrySLPredicate>> entry : mapEnsures.entrySet()) {
					List<CrySLPredicate> rulePredicate = entry.getValue();
					for (CrySLPredicate singlePredicate : rulePredicate) {
						if (singlePredicate.getPredName().contains(predicated) && !Objects.equals(rule.getComposedClassName(), entry.getKey())) {
							valuesToAdd.add(entry.getKey()   + "-" + temp);
						}
					}
				}
			}
			RuleMappedToEnsures.put(rule.getComposedClassName(),valuesToAdd);
		}
		return RuleMappedToEnsures;
	}


	/**
	 * This methods constructs a Map, out of the given 2 CryslPredicate Maps.
	 * @param keyMap
	 * @param dependingMap
	 * @return Map(String, Map(List(String, List(String))))
	 */
	public static Map<String, List<Map<String, List<String>>>> mapPredicates(Map<String, List<CrySLPredicate>> dependingMap, Map<String, List<CrySLPredicate>> keyMap) {
		Map<String, List<Map<String,List<String>>>> dependingPredicatesMap = new HashMap<>();
		for (String className : keyMap.keySet()) {
			List<Map<String,List<String>>> predicateList = new ArrayList<>();
			for (CrySLPredicate predicate : keyMap.get(className)) {
				if (predicate.isNegated()) continue;
				String predicateName = predicate.getPredName();
				List<ICrySLPredicateParameter> predicateParameters = predicate.getParameters();
				Map<String,List<String>> keyToDependingMap = new HashMap<>();
				for (String dependingClassName: dependingMap.keySet() ) {
					Set<String> dependingClasses = new LinkedHashSet<>();

					for (CrySLPredicate dependingPredicates :  dependingMap.get(dependingClassName)) {
						if (dependingPredicates.getPredName().equals(predicateName) && !(dependingPredicates.isNegated() && !(dependingPredicates instanceof CrySLCondPredicate))) {
							if (dependingPredicates.getParameters().size() == predicateParameters.size()) {
								dependingClasses.add(dependingClassName);

							}
						}
					}

					if (dependingClasses.size() != 0 ) {
						if (keyToDependingMap.containsKey(predicateName)) {
							keyToDependingMap.get(predicateName).addAll(dependingClasses);
						} else {
							List<String> dc = new ArrayList<>(dependingClasses);
							keyToDependingMap.put(predicateName, dc);
						}
					}
				}
				predicateList.add(keyToDependingMap);
			}
			dependingPredicatesMap.put(className,predicateList);
		}
		return dependingPredicatesMap;
	}


	public static char[] getTemplatesText(String templateName) throws IOException {
		File file = new File(DocSettings.getInstance().getLangTemplatesPath()+"\\"+templateName);
		StringBuilder stringBuffer = new StringBuilder();
		Reader reader = new InputStreamReader(new FileInputStream(file), StandardCharsets.UTF_8);
		char[] buff = new char[500];
		for (int charsRead; (charsRead = reader.read(buff)) != -1;) {
			stringBuffer.append(buff, 0, charsRead);
		}
		reader.close();
		return buff;

	}

	public static String getTemplatesTextString(String templateName) throws IOException {
		File file = new File(DocSettings.getInstance().getLangTemplatesPath()+"\\"+templateName);
		BufferedReader br = new BufferedReader(new FileReader(file));
		String strLine = "";
		String strD = "";

		while ((strLine = br.readLine()) != null) {
			strD += strLine;
			strLine = br.readLine();
		}
		br.close();
		return strD + "\n";
	}

	public static String pathForTemplates(String path) {
		return path.replaceAll("\\\\","/");
	}

    public static List<String> leafToRootOrderTopo(String start, Map<String, Set<String>> adj) {
        // 1) Collect reachable nodes from `start` (following adj: class -> providers)
        Deque<String> stack = new ArrayDeque<>();
        Set<String> reachable = new HashSet<>();
        stack.push(start);
        while (!stack.isEmpty()) {
            String u = stack.pop();
            if (!reachable.add(u)) continue;
            for (String v : adj.getOrDefault(u, Collections.emptySet())) {
                if (!v.equals(u)) stack.push(v); // ignore self-edge
            }
        }

        // 2) Build reversed graph: provider -> consumers (only within reachable set)
        Map<String, Set<String>> provToConsumers = new HashMap<>();
        Map<String, Integer> indeg = new HashMap<>();  // indegree = number of providers (deps)
        for (String u : reachable) indeg.put(u, 0);

        for (String u : reachable) {
            for (String p : adj.getOrDefault(u, Collections.emptySet())) {
                if (p.equals(u) || !reachable.contains(p)) continue;
                provToConsumers.computeIfAbsent(p, k -> new HashSet<>()).add(u);
                indeg.put(u, indeg.get(u) + 1);   // u depends on p
            }
        }

        // 3) Kahn’s queue seeded with leaves (indegree 0 => no deps)
        //    Use PriorityQueue for deterministic alphabetical order
        Queue<String> q = new PriorityQueue<>();
        for (Map.Entry<String,Integer> e : indeg.entrySet())
            if (e.getValue() == 0) q.add(e.getKey());

        List<String> order = new ArrayList<>(reachable.size());
        while (!q.isEmpty()) {
            String leaf = q.remove();
            order.add(leaf);  // providers before consumers (leaf -> root)

            for (String consumer : provToConsumers.getOrDefault(leaf, Collections.emptySet())) {
                int d = indeg.computeIfPresent(consumer, (k,v) -> v-1);
                if (d == 0) q.add(consumer);
            }
        }

        // 4) Cycle check (rare, but possible in big specs)
        if (order.size() != reachable.size()) {
            // nodes with indegree > 0 are in cycles; log and append them deterministically
            List<String> stuck = new ArrayList<>();
            for (Map.Entry<String,Integer> e : indeg.entrySet())
                if (e.getValue() > 0) stuck.add(e.getKey());
            Collections.sort(stuck);
            System.err.println("WARNING: cycle(s) detected among: " + stuck);
            // Break ties by appending; generation will still proceed.
            order.addAll(stuck);
        }

        return order; // leaf → … → root (start will be last if the graph is acyclic)
    }
}
