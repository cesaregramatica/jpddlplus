/*
 * Click nbfs://nbhost/SystemFileSystem/Templates/Licenses/license-default.txt to change this license
 * Click nbfs://nbhost/SystemFileSystem/Templates/Classes/Class.java to edit this template
 */
package com.hstairs.ppmajal.extraUtils;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.List;
import java.util.Map;
import java.util.Queue;
import java.util.Set;

/**
 *
 * @author enrico
 */
public class DAG {

    Set<String> vertexes;
    HashMap<String, Set<String>> edges;
    HashMap<String, Set<String>> edgesReversed;
    String root;

    public DAG() {
        vertexes = new HashSet();
        edges = new HashMap();
        edgesReversed = new HashMap();
        root = null;
    }

    public void addVertex(String a) {
        if (root == null) {
            root = a;
        }
        vertexes.add(a);
        if (edges.get(a) == null) edges.put(a, new HashSet());
        if (edgesReversed.get(a) == null) edgesReversed.put(a, new HashSet());
    }

    public void addEdge(String a, String b) {
        Set get = edges.get(a);
        get.add(b);
        Set<String> get1 = edgesReversed.get(b);
        get1.add(a);

        //check
        HashSet<String> closed = new HashSet<>();
        Queue<String> queue = new LinkedList<>();
        queue.add(b);
        while (!queue.isEmpty()) {
            String element = queue.poll();
            if (element.equals(a)) {
                get.remove(b);
                get1.remove(a);
                throw new RuntimeException("There is a cycle in the graph");
            }
            if (closed.add(element)) {
                for (String e : edges.get(element)) {
                    queue.add(e);
                }
            }
        }
    }

    public Set<String> getAncestors(String a) {
        HashSet ret = new HashSet();

        Queue<String> queue = new LinkedList();
        for (var v : edgesReversed.get(a)) {
            queue.add(v);
        }

        while (!queue.isEmpty()) {
            String poll = queue.poll();
            ret.add(poll);
            for (var v : edgesReversed.get(poll)) {
                queue.add(v);
            }
        }
        return ret;
    }

    public List<String> topologicalSort() {
        // Sorting algoritm based on Kahn's algorithm

        Map<String, Integer> inDegree = new HashMap<>();
        for (String v : vertexes) {
            inDegree.put(v, 0);
        }
        for (String v : vertexes) {
            for (String succ : edges.get(v)) {
                inDegree.put(succ, inDegree.get(succ) + 1);
            }
        }

        Queue<String> queue = new LinkedList<>();
        for (String v : vertexes) {
            if (inDegree.get(v) == 0) {
                queue.add(v);
            }
        }

        List<String> sorted = new ArrayList<>();
        while (!queue.isEmpty()) {
            String current = queue.poll();
            sorted.add(current);
            for (String succ : edges.get(current)) {
                inDegree.put(succ, inDegree.get(succ) - 1);
                if (inDegree.get(succ) == 0) {
                    queue.add(succ);
                }
            }
        }

        if (sorted.size() != vertexes.size()) {
            throw new RuntimeException(
                "Cycle detected in DAG during topological sort"
            );
        }

        return sorted;
    }

    public void print() {
        System.out.println(vertexes);
        System.out.println(edges);
        System.out.println(edgesReversed);
    }
}
