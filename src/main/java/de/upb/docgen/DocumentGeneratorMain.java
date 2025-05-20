package de.upb.docgen;

import java.io.*;
import java.nio.file.Files;
import java.util.*;

import crypto.exceptions.CryptoAnalysisException;
import crypto.rules.CrySLPredicate;
import crypto.rules.CrySLRule;
import crypto.rules.CrySLRuleReader;
import de.upb.docgen.llm.CrySLToLLMGenerator;
import de.upb.docgen.utils.PredicateTreeGenerator;
import de.upb.docgen.utils.TreeNode;
import de.upb.docgen.utils.Utils;
import de.upb.docgen.writer.FreeMarkerWriter;
import freemarker.template.*;
import org.apache.commons.io.FileUtils;

import javax.print.Doc;

import static de.upb.docgen.llm.CrySLToLLMGenerator.cleanLLMCodeBlock;

/**
 * @author Ritika Singh
 * @author Sven Feldmann
 */

public class DocumentGeneratorMain {

	private static final CrySLRuleReader ruleReader = new CrySLRuleReader();

	public static void main(String[] args) throws IOException, TemplateException, CryptoAnalysisException {
		// create singleton to access parsed flags from other classes
		DocSettings docSettings = DocSettings.getInstance();
		System.out.println("Parsing CLI Flags");
		docSettings.parseSettingsFromCLI(args);

		// read CryslRules from absolutePath provided by the user
		System.out.println("Reading CrySL Rules");
		List<CrySLRule> rules = ruleReader.readFromDirectory(new File(docSettings.getRulesetPathDir()));

		System.out.println("Reading CrySL Rules Done");
		ClassEventForb cef = new ClassEventForb();
		ConstraintsVc valueconstraint = new ConstraintsVc();
		ConstraintsPred predicateconstraint = new ConstraintsPred();
		ConstraintsComparison comp = new ConstraintsComparison();
		ConstraintCrySLVC cryslvc = new ConstraintCrySLVC();
		ConstraintCryslnocallto nocall = new ConstraintCryslnocallto();
		ConstraintCrySLInstanceof instance = new ConstraintCrySLInstanceof();
		ConstraintCrySLandencmode enc = new ConstraintCrySLandencmode();
		Order or = new Order();
		Ensures en = new Ensures();
		EnsuresCaseTwo entwo = new EnsuresCaseTwo();
		Negates neg = new Negates();
		List<ComposedRule> composedRuleList = new ArrayList<>();
		Map<String, List<CrySLPredicate>> mapEnsures = new HashMap<>();
		Map<String, List<CrySLPredicate>> mapRequires = new HashMap<>();

		// generate 2 Maps with Ensures, Requires predicates
		for (CrySLRule ruleEntry : rules) {
			CrySLRule rule = ruleEntry;
			mapEnsures.put(rule.getClassName(), rule.getPredicates());
			mapRequires.put(rule.getClassName(), rule.getRequiredPredicates());
		}

		// iterate over every Crysl rule, create composedRule for every Rule
		List<CrySLRule> cryslRuleList = new ArrayList<>();
		for (CrySLRule ruleEntry : rules) {
			ComposedRule composedRule = new ComposedRule();
			CrySLRule rule = ruleEntry;
			// CrySL to .txt format
			String fullClassName = rule.getClassName(); // e.g. "javax.crypto.Cipher"
			String simpleName = fullClassName.substring(fullClassName.lastIndexOf('.') + 1);
			String relativePath = "src/main/resources/CrySLRules/" + simpleName + ".crysl";
			File cryslFile = new File(relativePath);

			if (cryslFile.exists()) {
				String ruleText = Files.readString(cryslFile.toPath());
				composedRule.setCryslRuleText("\n" + ruleText);
			} else {
				composedRule.setCryslRuleText("// CrySL file not found for: " + simpleName);
			}

			// Overview section
			String classname = rule.getClassName();
			// fully qualified name
			composedRule.setComposedClassName(classname);
			// Only rule name necessary for ftl Template
			composedRule.setOnlyRuleName(classname.substring(classname.lastIndexOf(".") + 1));
			// Set classname sentence
			composedRule.setComposedFullClass(cef.getFullClassName(rule));
			// Link to corresponding JavaDoc
			composedRule.setComposedLink(cef.getLink(rule));
			composedRule.setOnlyLink(cef.getLinkOnly(rule));
			composedRule.setNumberOfMethods(cef.getEventNumbers(rule));

			// Order section
			composedRule.setOrder(or.runOrder(rule));

			//
			composedRule.setValueConstraints(valueconstraint.getConstraintsVc(rule));
			// create necessary Data structure to link required predicates of current crysl
			// rule
			Map<String, List<Map<String, List<String>>>> singleRuleEnsuresMap = Utils.mapPredicates(mapEnsures,
					mapRequires);
			// Pairing Dependency only by class name
			Map<String, Set<String>> singleReqToEns = Utils.toOnlyClassNames(singleRuleEnsuresMap);
			Set<String> ensuresForThisRule = singleReqToEns.get(composedRule.getComposedClassName());
			composedRule.setConstrainedPredicates(
					predicateconstraint.getConstraintsPred(rule, ensuresForThisRule, singleRuleEnsuresMap));
			// ConstraintsSection
			composedRule.setComparsionConstraints(comp.getConstriantsComp(rule));
			composedRule.setConstrainedValueConstraints(cryslvc.getConCryslVC(rule));
			composedRule.setNoCallToConstraints(nocall.getnoCalltoConstraint(rule));
			composedRule.setInstanceOfConstraints(instance.getInstanceof(rule));
			composedRule.setConstraintAndEncConstraints(enc.getConCryslandenc(rule));
			composedRule.setForbiddenMethods(cef.getForb(rule));
			//
			List<String> allConstraints = new ArrayList<>(composedRule.getComparsionConstraints());
			allConstraints.addAll(composedRule.getValueConstraints());
			allConstraints.addAll(composedRule.getConstrainedPredicates());
			allConstraints.addAll(composedRule.getConstrainedValueConstraints());
			allConstraints.addAll(composedRule.getNoCallToConstraints());
			allConstraints.addAll(composedRule.getInstanceOfConstraints());
			allConstraints.addAll(composedRule.getConstraintAndEncConstraints());
			allConstraints.addAll(composedRule.getForbiddenMethods());
			composedRule.setAllConstraints(allConstraints);

			// Predicates Section
			composedRule
					.setEnsuresThisPredicates(en.getEnsuresThis(rule, Utils.mapPredicates(mapRequires, mapEnsures)));
			composedRule.setEnsuresPredicates(entwo.getEnsures(rule, Utils.mapPredicates(mapRequires, mapEnsures)));
			composedRule.setNegatesPredicates(neg.getNegates(rule));
			composedRuleList.add(composedRule);

			cryslRuleList.add(rule);
		}

		// LLM Call for Explanation

//		CrySLToLLMGenerator.generateExplanations(composedRuleList, cryslRuleList);

		File cacheDir = new File("Output/resources/llm_cache");
		if(!cacheDir.exists()) {
			cacheDir.mkdir();
		}

		for (int i=0; i<cryslRuleList.size(); i++) {
			CrySLRule rule = cryslRuleList.get(i);
			ComposedRule composedRule = composedRuleList.get(i);

			String ruleName = rule.getClassName();
			String fileSafeName = ruleName.replaceAll("[^a-zA-Z0-9.\\-]", "_");
			File cacheFile = new File(cacheDir, fileSafeName + ".txt");

			String explanation;

			if (cacheFile.exists()) {
				explanation = new String(Files.readAllBytes(cacheFile.toPath()));
				System.out.println(fileSafeName + ".txt exists.");
			}
			else {
				CrySLToLLMGenerator.generateExplanations(List.of(composedRule),List.of(rule));
				explanation = composedRule.getLlmExplanation();
				if (!cacheFile.getParentFile().exists()) {
					Files.createDirectories(cacheFile.getParentFile().toPath());
				}
				Files.writeString(cacheFile.toPath(), explanation);
				System.out.println(fileSafeName + ".txt created.");
			}
			composedRule.setLlmExplanation(explanation);
		}

		//LLM Call for Secure and Insecure Code Generation

		File codeCacheDir = new File("Output/resources/code_cache");
		codeCacheDir.mkdir();

		for(int i =0; i < cryslRuleList.size(); i++) {
			CrySLRule rule = cryslRuleList.get(i);
			ComposedRule composedRule = composedRuleList.get(i);
			String ruleName = rule.getClassName().replaceAll("[^a-zA-Z0-9.\\-]", "_");

			File secureFile = new File(codeCacheDir, ruleName + "_secure.txt");
			File insecureFile = new File(codeCacheDir, ruleName + "_insecure.txt");

			String secure;
			if (secureFile.exists()) {
				secure = Files.readString(secureFile.toPath());
				System.out.println(ruleName + "_secure.txt exists.");
			}
			else {
				CrySLToLLMGenerator.generateExample(List.of(composedRule), List.of(rule));
				secure = cleanLLMCodeBlock(composedRule.getSecureExample());
				Files.writeString(secureFile.toPath(), secure);
				System.out.println(ruleName + "_secure.txt created.");
			}

			String insecure;
			if (insecureFile.exists()) {
				insecure = Files.readString(insecureFile.toPath());
				System.out.println(ruleName + "_insecure.txt exists.");
			}
			else {
				insecure = cleanLLMCodeBlock(composedRule.getInsecureExample());
				Files.writeString(insecureFile.toPath(), insecure);
				System.out.println(ruleName + "_insecure.txt created.");
			}
			composedRule.setSecureExample(secure);
			composedRule.setInsecureExample(insecure);
		}

		// Necessary DataStructure to generate Requires and Ensures Tree
		Map<String, List<Map<String, List<String>>>> ensuresToRequiresMap = Utils.mapPredicates(mapRequires,
				mapEnsures);
		Map<String, List<Map<String, List<String>>>> requiresToEnsuresMap = Utils.mapPredicates(mapEnsures,
				mapRequires);

		Map<String, Set<String>> onlyClassnamesReqToEns = Utils.toOnlyClassNames(ensuresToRequiresMap);
		Map<String, Set<String>> onlyClassnamesEnsToReq = Utils.toOnlyClassNames(requiresToEnsuresMap);

		Map<String, TreeNode<String>> reqToEns = PredicateTreeGenerator.buildDependencyTreeMap(onlyClassnamesReqToEns);
		Map<String, TreeNode<String>> ensToReq = PredicateTreeGenerator.buildDependencyTreeMap(onlyClassnamesEnsToReq);

		// Freemarker Setup and create cognicryptdoc html pages
		System.out.println("Setup Freemarker");
		Configuration cfg = new Configuration(new Version(2, 3, 20));
		FreeMarkerWriter.setupFreeMarker(cfg);
		FreeMarkerWriter.createCogniCryptLayout(cfg);
		FreeMarkerWriter.createSidebar(composedRuleList, cfg);
		FreeMarkerWriter.createSinglePage(composedRuleList, cfg, ensToReq, reqToEns, docSettings.isBooleanA(),
				docSettings.isBooleanB(), docSettings.isBooleanC(), docSettings.isBooleanD(), docSettings.isBooleanE(),
				docSettings.isBooleanF(), cryslRuleList);
		// copy CryslRulesFolder into generated Cognicrypt folder
		// specifify this flag to distribute the documentation
		System.out.println("CogniCryptDOC generated to: " + DocSettings.getInstance().getReportDirectory());
		if (!docSettings.isBooleanF()) {
			File source = new File(docSettings.getRulesetPathDir());
			File dest = new File(docSettings.getReportDirectory() + File.separator + "rules");
			try {
				FileUtils.copyDirectory(source, dest);
			} catch (IOException e) {
				e.printStackTrace();
			}
		}

	}

}
