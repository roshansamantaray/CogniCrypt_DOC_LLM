package de.upb.docgen.crysl;

import crypto.cryslhandler.CrySLModelReader;
import crypto.exceptions.CryptoAnalysisException;
import crypto.rules.CrySLRule;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;

import java.net.JarURLConnection;
import java.net.MalformedURLException;
import java.net.URISyntaxException;
import java.net.URL;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;

import java.security.CodeSource;

import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import java.util.jar.JarEntry;
import java.util.jar.JarFile;


/**
 * @author Ritika Singh
 */

public class CrySLReader {
	// ---------------------------------------------------------
// Sven features (PR #11/#12): default-from-JAR support
// Implements your GitHub review comments:
// - exact matching (no broad "contains")
// - safe extraction (no Utils.extract / no writing into cwd)
// ---------------------------------------------------------

private static final String CRYSL_RULES_DIR = "CrySLRules";
private static final String FTL_TEMPLATES_DIR = "FTLTemplates";
private static final String SYMBOL_PROPERTIES_RESOURCE = "Templates/symbol.properties";

// reuse one temp dir for extracted resources
private static Path cachedTempDir = null;

/**
 * Read ALL CrySL rules bundled inside the JAR under /CrySLRules.
 * If running from IDE (resources on disk), read from filesystem folder instead.
 */
	public static List<CrySLRule> readRulesFromJar() throws IOException {
		CrySLModelReader reader = new CrySLModelReader();
		List<CrySLRule> out = new ArrayList<>();

		// IDE mode: resources available as real files
		URL dirUrl = CrySLReader.class.getClassLoader().getResource(CRYSL_RULES_DIR);
		if (dirUrl != null && "file".equalsIgnoreCase(dirUrl.getProtocol())) {
			try {
				File dir = Paths.get(dirUrl.toURI()).toFile();
				File[] files = dir.listFiles((d, name) -> name != null && name.endsWith(".crysl"));
				if (files != null) {
					for (File f : files) {
						try {
							out.add(reader.readRule(f));
						} catch (CryptoAnalysisException e) {
							System.err.println("Error processing rule file: " + f.getName() + " - " + e.getMessage());
						}
					}
				}
				return out;
			} catch (URISyntaxException e) {
				throw new IOException("Failed to resolve /CrySLRules resource directory", e);
			}
		}

		// JAR mode: enumerate entries
		try (JarFile jar = openOwningJar(dirUrl)) {
			Enumeration<JarEntry> entries = jar.entries();
			String prefix = CRYSL_RULES_DIR + "/";

			while (entries.hasMoreElements()) {
				JarEntry entry = entries.nextElement();
				String name = entry.getName();

				if (!entry.isDirectory() && name.startsWith(prefix) && name.endsWith(".crysl")) {
					File extracted = extractJarEntryToTempFile(jar, entry);
					try {
						out.add(reader.readRule(extracted));
					} catch (CryptoAnalysisException e) {
						System.err.println("Error processing rule: " + name + " - " + e.getMessage());
					}
				}
			}
		}

		return out;
	}

	/**
	 * Extract a SINGLE CrySL rule from resources:
	 * exact match: /CrySLRules/<ruleName>.crysl
	 *
	 * @param ruleName simple class name, e.g. "Cipher"
	 */
	public static File readRuleFromJarFile(String ruleName) throws IOException {
		if (ruleName == null || ruleName.trim().isEmpty()) {
			throw new IllegalArgumentException("ruleName cannot be null/empty");
		}
		ruleName = ruleName.trim();

		String resourcePath = CRYSL_RULES_DIR + "/" + ruleName + ".crysl";

		// IDE mode: file resource
		URL fileUrl = CrySLReader.class.getClassLoader().getResource(resourcePath);
		if (fileUrl != null && "file".equalsIgnoreCase(fileUrl.getProtocol())) {
			try {
				return Paths.get(fileUrl.toURI()).toFile();
			} catch (URISyntaxException e) {
				throw new IOException("Failed to resolve resource URI: " + fileUrl, e);
			}
		}

		// JAR mode: exact entry match (no broad "contains")
		try (JarFile jar = openOwningJar(fileUrl)) {
			JarEntry entry = jar.getJarEntry(resourcePath);
			if (entry == null) {
				// fallback: restricted endsWith match inside CrySLRules/
				entry = findJarEntryEndingWith(jar, "/" + ruleName + ".crysl", CRYSL_RULES_DIR + "/");
			}
			if (entry == null) return null;

			return extractJarEntryToTempFile(jar, entry);
		}
	}

	/**
	 * Extract Templates/symbol.properties (exact match).
	 */
	public static File readSymbolPropertiesFromJar() throws IOException {
		String resourcePath = SYMBOL_PROPERTIES_RESOURCE;

		URL fileUrl = CrySLReader.class.getClassLoader().getResource(resourcePath);
		if (fileUrl != null && "file".equalsIgnoreCase(fileUrl.getProtocol())) {
			try {
				return Paths.get(fileUrl.toURI()).toFile();
			} catch (URISyntaxException e) {
				throw new IOException("Failed to resolve resource URI: " + fileUrl, e);
			}
		}

		try (JarFile jar = openOwningJar(fileUrl)) {
			JarEntry entry = jar.getJarEntry(resourcePath);
			if (entry == null) {
				// fallback: restricted endsWith match inside Templates/
				entry = findJarEntryEndingWith(jar, "/symbol.properties", "Templates/");
			}
			if (entry == null) return null;

			return extractJarEntryToTempFile(jar, entry);
		}
	}

	/**
	 * Extract a bundled FreeMarker template from:
	 * exact match: /FTLTemplates/<ftlName>
	 */
	public static File readFTLFromJar(String ftlName) throws IOException {
		if (ftlName == null || ftlName.trim().isEmpty()) {
			throw new IllegalArgumentException("ftlName cannot be null/empty");
		}
		ftlName = ftlName.trim();

		String resourcePath = FTL_TEMPLATES_DIR + "/" + ftlName;

		URL fileUrl = CrySLReader.class.getClassLoader().getResource(resourcePath);
		if (fileUrl != null && "file".equalsIgnoreCase(fileUrl.getProtocol())) {
			try {
				return Paths.get(fileUrl.toURI()).toFile();
			} catch (URISyntaxException e) {
				throw new IOException("Failed to resolve resource URI: " + fileUrl, e);
			}
		}

		try (JarFile jar = openOwningJar(fileUrl)) {
			JarEntry entry = jar.getJarEntry(resourcePath);
			if (entry == null) {
				// fallback: restricted endsWith match inside FTLTemplates/
				entry = findJarEntryEndingWith(jar, "/" + ftlName, FTL_TEMPLATES_DIR + "/");
			}
			if (entry == null) return null;

			return extractJarEntryToTempFile(jar, entry);
		}
	}

	// ----------------- helpers -----------------

	private static JarFile openOwningJar(URL anyResourceUrl) throws IOException {
		// Best-case: jar:<...>!/path
		if (anyResourceUrl != null && "jar".equalsIgnoreCase(anyResourceUrl.getProtocol())) {
			JarURLConnection conn = (JarURLConnection) anyResourceUrl.openConnection();
			return conn.getJarFile();
		}

		// Fallback: resolve the jar from CodeSource (works when running packaged)
		CodeSource codeSource = CrySLReader.class.getProtectionDomain().getCodeSource();
		if (codeSource == null) {
			throw new IOException("Cannot locate CodeSource for CrySLReader");
		}
		try {
			Path p = Paths.get(codeSource.getLocation().toURI());
			File jarFile = p.toFile();
			if (!jarFile.isFile()) {
				throw new IOException("CodeSource is not a JAR file: " + jarFile);
			}
			return new JarFile(jarFile);
		} catch (URISyntaxException e) {
			throw new IOException("Failed to resolve CodeSource URI", e);
		}
	}

	private static JarEntry findJarEntryEndingWith(JarFile jar, String endsWith, String requiredPrefix) {
		Enumeration<JarEntry> entries = jar.entries();
		while (entries.hasMoreElements()) {
			JarEntry e = entries.nextElement();
			String name = e.getName();
			if (!e.isDirectory() && name.startsWith(requiredPrefix) && name.endsWith(endsWith)) {
				return e;
			}
		}
		return null;
	}

	private static File extractJarEntryToTempFile(JarFile jar, JarEntry entry) throws IOException {
		String resourcePath = entry.getName();
		Path tmpDir = getOrCreateTempDir();
		String safeName = resourcePath.replace('/', '_').replace('\\', '_');
		Path out = tmpDir.resolve(safeName);

		if (Files.exists(out)) {
			return out.toFile();
		}

		try (InputStream in = jar.getInputStream(entry)) {
			if (in == null) {
				throw new IOException("Resource stream was null for: " + resourcePath);
			}
			Files.copy(in, out, StandardCopyOption.REPLACE_EXISTING);
		}

		out.toFile().deleteOnExit();
		return out.toFile();
	}

	private static Path getOrCreateTempDir() throws IOException {
		if (cachedTempDir != null) return cachedTempDir;

		Path base = Paths.get(System.getProperty("java.io.tmpdir"));
		Path dir = base.resolve("cognicryptdoc_resources");
		Files.createDirectories(dir);
		dir.toFile().deleteOnExit();

		cachedTempDir = dir;
		return cachedTempDir;
	}


	public static List<CrySLRule> readRulesFromSourceFilesWithoutFiles(final String folderPath) throws CryptoAnalysisException, MalformedURLException {
		return new ArrayList<>(readRulesFromSourceFiles(folderPath).values());
	}

	public static Map<File, CrySLRule> readRulesFromSourceFiles(final String folderPath) throws CryptoAnalysisException, MalformedURLException {
		if (folderPath == null || folderPath.isEmpty()) {
			throw new IllegalArgumentException("Folder path cannot be null or empty");
		}

		CrySLModelReader cryslModelReader = new CrySLModelReader();
		Map<File, CrySLRule> rules = new HashMap<>();

		try {
			File folder = new File(folderPath);
			if (!folder.isDirectory()) {
				throw new IllegalArgumentException("Invalid folder path: " + folderPath);
			}

			File[] files = folder.listFiles();
			if (files == null) {
				return rules;
			}
			for (File file : files) {
				if (file != null && file.getName().endsWith(".crysl")) {
					rules.put(file, cryslModelReader.readRule(file));
				}
			}

		} catch (CryptoAnalysisException e) {
			// Handle CryptoAnalysisException
			throw e;
		}

		return rules;
	}

}