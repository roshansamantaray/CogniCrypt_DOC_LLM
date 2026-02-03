package de.upb.docgen.writer;

import crypto.rules.CrySLRule;
import de.upb.docgen.*;
import de.upb.docgen.graphviz.StateMachineToGraphviz;
import de.upb.docgen.utils.TemplateAbsolutePathLoader;
import de.upb.docgen.utils.TreeNode;
import de.upb.docgen.utils.Utils;
import freemarker.template.*;

import java.io.*;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;

import de.upb.docgen.crysl.CrySLReader;

/**
 * @author Sven Feldmann
 */


public class FreeMarkerWriter {

    /**
     * Creates Sidebar for CogniCryptDOC
     * @param composedRuleList the fully qualified name is used from this list later from freemarker
     * @param cfg necessary for freemarker
     * @throws IOException
     * @throws TemplateException
     */
    public static void createSidebar(List<ComposedRule> composedRuleList, Configuration cfg ) throws IOException, TemplateException {
        Map<String, Object> input = new HashMap<String, Object>();
        input.put("title", "Sidebar");
        Collections.sort(composedRuleList, new Comparator<ComposedRule>() {
            @Override
            public int compare(ComposedRule o1, ComposedRule o2) {
                return o1.getComposedFullClass().compareTo(o2.getComposedFullClass());
            }
        });
        input.put("rules", composedRuleList);
        Template template;
        String ftlDir = DocSettings.getInstance().getFtlTemplatesPath();

        if (ftlDir != null && !ftlDir.trim().isEmpty()) {
            template = cfg.getTemplate(Utils.pathForTemplates(new File(ftlDir, "sidebar.ftl").toURI().toString()));
        } else {
            File file = CrySLReader.readFTLFromJar("sidebar.ftl");
            template = cfg.getTemplate(Utils.pathForTemplates(file.toURI().toString()));
        }

        // 2.3. Generate the output
        File out = new File(new File(DocSettings.getInstance().getReportDirectory()), "navbar.html");

        try (Writer fileWriter = new FileWriter(out)) {
            template.process(input, fileWriter);
        }
    }

    /**
     * Creates the single page of all rules
     * @param composedRuleList
     * @param cfg
     * @param reqToEns
     * @param ensToReq
     * @param a
     * @param b
     * @param c
     * @param f
     * @throws IOException
     * @throws TemplateException
     */
    public static void createSinglePage(List<ComposedRule> composedRuleList, Configuration cfg, Map<String, TreeNode<String>> reqToEns, Map<String, TreeNode<String>> ensToReq, boolean a, boolean b, boolean c, boolean d, boolean e, boolean f, List<CrySLRule> crySLRules, List<String> LANGUAGES) throws IOException, TemplateException {
        File reportDir = new File(DocSettings.getInstance().getReportDirectory());
        File composedRulesDir = new File(reportDir, "composedRules");
        Files.createDirectories(composedRulesDir.toPath());

        for (int i = 0; i < composedRuleList.size(); i++) {
            ComposedRule rule = composedRuleList.get(i);
            Map<String, Object> input = new HashMap<String, Object>();
            input.put("title", "class");
            input.put("rule", rule);
//            Map<String, String> llmExplanation = rule.getLlmExplanation();
            input.put("englishExplanation",rule.getLlmExplanation().get("English"));
            input.put("frenchExplanation",rule.getLlmExplanation().get("French"));
            input.put("portugueseExplanation",rule.getLlmExplanation().get("Portuguese"));
            input.put("germanExplanation",rule.getLlmExplanation().get("German"));

            input.put("secureExample", rule.getSecureExample());
            input.put("insecureExample", rule.getInsecureExample());
            TreeNode<String> rootReq = reqToEns.get(rule.getComposedClassName());
            input.put("requires", rootReq); // requires tree parsed by the template
            TreeNode<String> rootEns = ensToReq.get(rule.getComposedClassName());
            input.put("ensures", rootEns); // ensures tree parsed by the template

            // necessary input for the template to load absolute path from crysl rule which can be displayed
            String rulesDir = DocSettings.getInstance().getRulesetPathDir();
            if (rulesDir != null && !rulesDir.trim().isEmpty()) {
                File rulesDirFile = new File(rulesDir);
                input.put("pathToRules", Utils.pathForTemplates(rulesDirFile.toURI().toString()));
            } else {
                // In default-from-JAR mode, templates should rely on rule.getCryslRuleText()
                // If your template still reads files from pathToRules, we need a temp extracted rules dir instead.
                input.put("pathToRules", "");
            }
            // Set flags
            input.put("booleanA", a); // To show StateMachineGraph
            input.put("booleanB", b); // To show Help Button
            input.put("booleanC", c);
            input.put("booleanD", d);
            input.put("booleanE", e);
            input.put("booleanF", f);

            input.put("stateMachine", StateMachineToGraphviz.toGraphviz(crySLRules.get(i).getUsagePattern()));

            // 2.2. Get the template
            Template template;
            String ftlDir = DocSettings.getInstance().getFtlTemplatesPath();

            if (ftlDir != null && !ftlDir.trim().isEmpty()) {
                template = cfg.getTemplate(Utils.pathForTemplates(new File(ftlDir, "singleclass.ftl").toURI().toString()));
            } else {
                File file = CrySLReader.readFTLFromJar("singleclass.ftl");
                template = cfg.getTemplate(Utils.pathForTemplates(file.toURI().toString()));

            }


            // create composedRules directory where single pages are stored
            // create the page
            File outFile = new File(composedRulesDir, rule.getComposedClassName() + ".html");
            try (Writer fileWriter = new FileWriter(outFile)) {
                template.process(input, fileWriter);
            }
        }
    }


        /**
         * sets freemarker settings
         * @param cfg
         */
    public static void setupFreeMarker(Configuration cfg) {
        // setup freemarker to load absolute paths
        cfg.setTemplateLoader(new TemplateAbsolutePathLoader());
        // Some other recommended settings:
        cfg.setDefaultEncoding("UTF-8");
        cfg.setLocale(Locale.ENGLISH);
        cfg.setLocalizedLookup(false);
        cfg.setTemplateExceptionHandler(TemplateExceptionHandler.RETHROW_HANDLER);
    }

    /**
     * creates core layout pages of cognicrypt doc
     * @param cfg
     * @throws IOException
     * @throws TemplateException
     */
    public static void createCogniCryptLayout(Configuration cfg) throws IOException, TemplateException {
        Map<String, Object> input = new HashMap<>();

        // OS-agnostic: create output directory (and parents) if missing
        Files.createDirectories(new File(DocSettings.getInstance().getReportDirectory()).toPath());

        // Template source selection MUST depend on --ftlTemplatesPath (not --rulesDir)
        String ftlDir = DocSettings.getInstance().getFtlTemplatesPath();

        Template frontpageTemplate;
        Template rootpageTemplate;
        Template cryslTemplate;

        if (ftlDir != null && !ftlDir.trim().isEmpty()) {
            frontpageTemplate = cfg.getTemplate(
                    Utils.pathForTemplates(new File(ftlDir, "frontpage.ftl").toURI().toString())
            );
            rootpageTemplate = cfg.getTemplate(
                    Utils.pathForTemplates(new File(ftlDir, "rootpage.ftl").toURI().toString())
            );
            cryslTemplate = cfg.getTemplate(
                    Utils.pathForTemplates(new File(ftlDir, "crysl.ftl").toURI().toString())
            );
        } else {
            File front = CrySLReader.readFTLFromJar("frontpage.ftl");
            File root  = CrySLReader.readFTLFromJar("rootpage.ftl");
            File crysl = CrySLReader.readFTLFromJar("crysl.ftl");

            frontpageTemplate = cfg.getTemplate(Utils.pathForTemplates(front.toURI().toString()));
            rootpageTemplate  = cfg.getTemplate(Utils.pathForTemplates(root.toURI().toString()));
            cryslTemplate     = cfg.getTemplate(Utils.pathForTemplates(crysl.toURI().toString()));
        }

        try (Writer fileWriter = new FileWriter(new File(
                DocSettings.getInstance().getReportDirectory() + File.separator + "frontpage.html"
        ))) {
            frontpageTemplate.process(input, fileWriter);
        }

        try (Writer fileWriter = new FileWriter(new File(
                DocSettings.getInstance().getReportDirectory() + File.separator + "rootpage.html"
        ))) {
            rootpageTemplate.process(input, fileWriter);
        }

        try (Writer fileWriter = new FileWriter(new File(
                DocSettings.getInstance().getReportDirectory() + File.separator + "crysl.html"
        ))) {
            cryslTemplate.process(input, fileWriter);
        }
    }

}
