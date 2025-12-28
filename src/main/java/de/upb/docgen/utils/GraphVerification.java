package de.upb.docgen.utils;

import java.util.*;

public final class GraphVerification {

    private GraphVerification() {}

    public static void verifyOrdering(String param, Map<String, Set<String>> sanitizedAdj) {
        String start = param;
        List<String> order = Utils.leafToRootOrderTopo(start, sanitizedAdj);
        System.out.println("Order size=" + order.size());
        System.out.println("Last element = " + order.get(order.size() - 1));
        if (!order.get(order.size() - 1).equals(start)) {
            throw new IllegalStateException(start + " is not last; ordering still off.");
        }

        Map<String, Set<String>> g = sanitizedAdj;
        Set<String> nodes = new HashSet<>();
        Deque<String> stack = new ArrayDeque<>();
        stack.push(start);
        while (!stack.isEmpty()) {
            String u = stack.pop();
            if (!nodes.add(u)) continue;
            for (String v : g.getOrDefault(u, Set.of())) {
                if (!v.equals(u)) stack.push(v);
            }
        }

        List<Set<String>> sccs = new ArrayList<>();
        Map<String, Integer> idx = new HashMap<>();
        Map<String, Integer> low = new HashMap<>();
        Deque<String> tarjanStack = new ArrayDeque<>();
        Set<String> onStack = new HashSet<>();
        int[] id = {0};

        for (String v : nodes) {
            if (!idx.containsKey(v)) {
                tarjan(v, g, idx, low, tarjanStack, onStack, id, sccs);
            }
        }

        for (Set<String> comp : sccs) {
            if (comp.contains(start)) {
                if (comp.size() == 1) {
                    System.out.println(start + " in singleton SCC (good).");
                } else {
                    System.out.println(start + " still in cyclic SCC: " + comp);
                }
            }
        }
    }

    private static void tarjan(String v,
                               Map<String, Set<String>> g,
                               Map<String, Integer> idx,
                               Map<String, Integer> low,
                               Deque<String> stack,
                               Set<String> on,
                               int[] id,
                               List<Set<String>> sccs) {
        idx.put(v, id[0]);
        low.put(v, id[0]);
        id[0]++;
        stack.push(v);
        on.add(v);
        for (String w : g.getOrDefault(v, Set.of())) {
            if (!idx.containsKey(w)) {
                tarjan(w, g, idx, low, stack, on, id, sccs);
                low.put(v, Math.min(low.get(v), low.get(w)));
            } else if (on.contains(w)) {
                low.put(v, Math.min(low.get(v), idx.get(w)));
            }
        }
        if (Objects.equals(low.get(v), idx.get(v))) {
            Set<String> comp = new TreeSet<>();
            String x;
            do {
                x = stack.pop();
                on.remove(x);
                comp.add(x);
            } while (!x.equals(v));
            sccs.add(comp);
        }
    }
}
