package de.upb.docgen.utils;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * @author Sven Feldmann
 */


public class PredicateTreeGenerator {


    /**
     * Build a dependency tree per class name where each root is a rule/class and
     * children are the classes it depends on (directly or transitively).
     */
    public static Map<String, TreeNode<String>> buildDependencyTreeMap(Map<String, Set<String>> mappedClassnamePredicates) {
        Map<String, TreeNode<String>> chainMap = new HashMap<>();
        Set<String> visitedNodes = new HashSet<>();
        for (String classname : mappedClassnamePredicates.keySet()) {
            TreeNode<String> root = new TreeNode<>(classname);
            for (String nextInChain : mappedClassnamePredicates.get(classname)) {
                if (root.getData().equals(nextInChain)) continue;
                TreeNode<String> child = new TreeNode<>(nextInChain);
                // Recursive step to populate the child's subtree.
                populatePredicateTree(child, nextInChain, mappedClassnamePredicates, visitedNodes);
                root.addChild(child);
            }
            chainMap.put(classname, root);
        }
        return chainMap;
    }

    /**
     * Recursively expand a dependency subtree while avoiding cycles and duplicates.
     */
    private static TreeNode<String> populatePredicateTree(TreeNode<String> firstChild, String nextInChain, Map<String, Set<String>> mappedClassNamePredicates, Set<String> visitedNodes) {
        if (mappedClassNamePredicates.get(nextInChain).size() == 0) {
            // Leaf node: no further dependencies to expand.
            return firstChild;
        }

        // Track current path to detect circular dependencies.
        visitedNodes.add(nextInChain);

        for (String child : mappedClassNamePredicates.get(nextInChain)) {
            if (visitedNodes.contains(child)) {
                // Circular dependency detected; skip expanding this edge.
                continue;
            }
            if (firstChild.getData().equals(child)) {
                return firstChild;
            }
            for (TreeNode children : firstChild.getChildren()) {
                if (children.getData().equals(child)) {
                    // Avoid adding duplicate child nodes at this level.
                    return firstChild;
                }
            }
            TreeNode<String> childnode = new TreeNode<>(child);
            firstChild.addChild(childnode);
            populatePredicateTree(childnode, child, mappedClassNamePredicates, visitedNodes);
        }

        // Pop from current path when unwinding recursion.
        visitedNodes.remove(nextInChain);

        return firstChild;
    }

}