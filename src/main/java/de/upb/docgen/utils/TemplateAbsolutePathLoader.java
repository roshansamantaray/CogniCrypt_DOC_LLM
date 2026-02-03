package de.upb.docgen.utils;

import freemarker.cache.TemplateLoader;

import java.io.*;

//https://stackoverflow.com/questions/1208220/using-an-absolute-path-with-freemarker
public class TemplateAbsolutePathLoader implements TemplateLoader {

    public Object findTemplateSource(String name) throws IOException {
        if (name == null) return null;
        if (name.startsWith("file:")) {
            try {
                File uriFile = new File(java.net.URI.create(name));
                return uriFile.isFile() ? uriFile : null;
            } catch (IllegalArgumentException e) {
                // fall back to raw name if URI parsing fails
            }
        }
        File source = new File(name);
        return source.isFile() ? source : null;
    }

    public long getLastModified(Object templateSource) {
        return ((File) templateSource).lastModified();
    }

    public Reader getReader(Object templateSource, String encoding)
            throws IOException {
        if (!(templateSource instanceof File)) {
            throw new IllegalArgumentException("templateSource is a: " + templateSource.getClass().getName());
        }
        return new InputStreamReader(new FileInputStream((File) templateSource), encoding);
    }

    public void closeTemplateSource(Object templateSource) throws IOException {
        // Do nothing.
    }

}
