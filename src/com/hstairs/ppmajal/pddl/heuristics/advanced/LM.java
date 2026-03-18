package com.hstairs.ppmajal.pddl.heuristics.advanced;

import com.hstairs.ppmajal.PDDLProblem.PDDLProblem;
import com.hstairs.ppmajal.PDDLProblem.PDDLState;
import com.hstairs.ppmajal.conditions.AndCond;
import com.hstairs.ppmajal.conditions.BoolPredicate;
import com.hstairs.ppmajal.conditions.Comparison;
import com.hstairs.ppmajal.conditions.Condition;
import com.hstairs.ppmajal.conditions.OrCond;
import com.hstairs.ppmajal.conditions.Terminal;
import com.hstairs.ppmajal.expressions.NumFluent;
import com.hstairs.ppmajal.extraUtils.DAG;
import com.hstairs.ppmajal.pddl.heuristics.advanced.lpsolvers.CPLEX;
import com.hstairs.ppmajal.pddl.heuristics.advanced.lpsolvers.LPSolver;
import com.hstairs.ppmajal.problem.State;
import ilog.concert.IloLinearNumExpr;
import it.unimi.dsi.fastutil.ints.IntArrayList;
import it.unimi.dsi.fastutil.ints.IntArraySet;
import it.unimi.dsi.fastutil.ints.IntOpenHashSet;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.List;
import org.jgrapht.util.FibonacciHeap;

/**
 *
 * @author enrico
 */
public class LM extends H1 {

    private final boolean[] reachedConditions;
    private final boolean[] reachedActions;
    private final IntOpenHashSet[] lmC;
    private final IntOpenHashSet[] lmA;
    private final String mode;
    private final LPSolver lpSolver;

    protected IloLinearNumExpr objectiveFunction;

    public LM(PDDLProblem problem) {
        this(problem, "lmCount", "no", "cplex");
    }

    public LM(
        PDDLProblem problem,
        String mode,
        String redundantConstraints,
        String solver
    ) {
        super(
            problem,
            true,
            true,
            false,
            redundantConstraints,
            false,
            false,
            false,
            false,
            null,
            false,
            -1
        );
        reachedConditions = new boolean[totNumberOfTerms];
        reachedActions = new boolean[cp.numActions()];
        lmC = new IntOpenHashSet[totNumberOfTerms];
        lmA = new IntOpenHashSet[cp.numActions()];
        this.mode = mode;
        if ("cplex".equals(solver)) {
            lpSolver = new CPLEX(this);
        } else if ("none".equals(solver)) {
            lpSolver = null;
        } else {
            throw new RuntimeException(solver + " is not supported");
            //            lpSolver = new GUROBI(this);
        }
        allAchievers = new IntArraySet[totNumberOfTerms];
    }

    @Override
    public float computeEstimate(State s) {
        if ("lmCount".equals(mode)) {
            resetAndExpand(s);
            return countMissing();
        } else if ("lp".equals(mode)) {
            return lpSolver.solve(s, getLandmarks(s));
        } else if ("onld-local".equals(mode)) {
            return computeONLD(s, false);
        } else if ("onld-hadd".equals(mode)) {
            return computeONLD(s, true);
        }
        return 0f;
    }

    public IntOpenHashSet getLmC(int conditionId) {
        return lmC[conditionId];
    }

    private float computeONLD(State s, boolean useFullHadd) {
        resetAndExpand(s);
        IntOpenHashSet goalLandmarks = lmA[cp.goal()];
        if (goalLandmarks == null || goalLandmarks.isEmpty()) return 0f;

        List<Integer> ordered = buildAndSortLandmarkDAG(goalLandmarks);

        State synthetic = s.clone();
        float total = 0f;

        for (int lmId : ordered) {
            if (getConditionInit()[lmId]) continue;

            float stepCost;
            if (useFullHadd) {
                stepCost = hadd_singleGoal(synthetic, lmId);
            } else {
                stepCost = localCostEstimate(lmId, synthetic);
            }

            if (stepCost == Float.MAX_VALUE) return Float.MAX_VALUE;
            total += stepCost;

            applyLandmarkToState(lmId, synthetic);
        }

        return total;
    }

    private List<Integer> buildAndSortLandmarkDAG(
        IntOpenHashSet goalLandmarks
    ) {
        DAG dag = new DAG();

        for (int lmId : goalLandmarks) {
            dag.addVertex(String.valueOf(lmId));
        }

        for (int i : goalLandmarks) {
            IntOpenHashSet preds = getLmC(i);
            if (preds == null) continue;
            for (int j : preds) {
                if (goalLandmarks.contains(j)) {
                    try {
                        dag.addEdge(String.valueOf(j), String.valueOf(i));
                    } catch (RuntimeException e) {
                        // skip
                    }
                }
            }
        }

        List<String> sortedStrings = dag.topologicalSort();

        List<Integer> result = new ArrayList<>();
        for (String st : sortedStrings) {
            result.add(Integer.parseInt(st));
        }
        return result;
    }

    private void applyLandmarkToState(int lmId, State synthetic) {
        PDDLState s = (PDDLState) synthetic;
        Terminal t = Terminal.getTerminal(lmId);
        if (t instanceof Comparison) {
            Comparison comp = (Comparison) t;
            for (NumFluent nf : comp.getLeft().getInvolvedNumericFluents()) {
                double currentVal = nf.eval(synthetic);
                double threshold = comp.getLeft().eval(synthetic) * -1;
                s.setNumFluent(nf, currentVal + threshold + 0.001);
            }
        } else if (t instanceof BoolPredicate) {
            BoolPredicate bp = (BoolPredicate) t;
            s.setPropFluent(bp, true);
        }
    }

    private float localCostEstimate(int lmId, State synthetic) {
        Terminal t = Terminal.getTerminal(lmId);

        if (t instanceof Comparison) {
            Comparison comp = (Comparison) t;
            double gap = -1.0 * comp.getLeft().eval(synthetic);
            if (gap <= 0) return 0f;

            float bestCost = Float.MAX_VALUE;

            for (int a : getReachableAchievers()[lmId]) {
                double contribution = getNumericContribution(a, lmId);
                if (contribution <= 0) continue;

                float rep = (float) Math.ceil(gap / contribution);
                float cost = rep * cp.actionCost()[a];
                bestCost = Math.min(bestCost, cost);
            }
            return bestCost;
        } else if (t instanceof BoolPredicate) {
            float bestCost = Float.MAX_VALUE;
            for (int a : getReachableAchievers()[lmId]) {
                bestCost = Math.min(bestCost, cp.actionCost()[a]);
            }
            return bestCost;
        }

        return 0f;
    }

    private float hadd_singleGoal(State synthetic, int lmId) {
        FibonacciHeap h = this.smallSetup(synthetic);

        while (!h.isEmpty()) {
            int actionId = (int) h.removeMin().getData();
            if (actionId == cp.goal()) break;
            closed[actionId] = true;
            if (actionId != cp.goal()) {
                expand(actionId, h, synthetic);
            }
            if (getConditionCost()[lmId] < Float.MAX_VALUE) break;
        }

        return getConditionCost()[lmId];
    }

    public IntOpenHashSet getLandmarks(State s) {
        resetAndExpand(s);
        return lmA[cp.goal()];
    }

    void resetAndExpand(State s) {
        final IntArrayList q = quickReset(s);

        while (!q.isEmpty()) {
            final int a = q.popInt();
            if (a != cp.goal()) {
                expand(a, q);
            }
        }
    }

    boolean checkReached(final Condition c) {
        if (c instanceof AndCond) {
            final AndCond and = (AndCond) c;
            if (and.sons == null) {
                return true;
            }
            for (final var son : and.sons) {
                if (!checkReached((Condition) son)) {
                    return false;
                }
            }
            return true;
        } else if (c instanceof OrCond) {
            final OrCond and = (OrCond) c;
            if (and.sons == null) {
                return true;
            }
            for (final var son : and.sons) {
                if (checkReached((Condition) son)) {
                    return true;
                }
            }
            return false;
        } else if (c instanceof Terminal) {
            final Terminal t = (Terminal) c;
            return reachedConditions[t.getId()];
        } else {
            return true;
        }
    }

    private void updateActions(int i, IntArrayList q, int a) {
        final IntArraySet actions = getConditionToAction()[i];
        for (final int a1 : actions) {
            if (a == a1) {
                continue;
            }
            final Condition name = cp.preconditionFunction()[a1];
            if (reachedActions[a1] || checkReached(name)) {
                reachedActions[a1] = true;
                lmA[a1] = new IntOpenHashSet();
                if (name instanceof AndCond) {
                    for (final Object t : ((AndCond) name).sons) {
                        if (t instanceof Terminal) {
                            lmA[a1].addAll(lmC[((Terminal) t).getId()]);
                            if (!getConditionInit()[((Terminal) t).getId()]) {
                                lmA[a1].add(((Terminal) t).getId());
                            }
                        }
                    }
                } else {
                    throw new UnsupportedOperationException(
                        "Only And Condition supported"
                    );
                }
                q.add(a1);
            }
        }
    }

    private boolean updateCondition(int p, int a) {
        if (!reachedConditions[p]) {
            reachedConditions[p] = true;
            lmC[p] = new IntOpenHashSet(lmA[a]);
            return true;
        } else {
            boolean changed = false;
            final IntOpenHashSet newSet = new IntOpenHashSet();
            for (final int sg : lmC[p]) {
                if (!lmA[a].contains(sg)) {
                    changed = true;
                } else {
                    newSet.add(sg);
                }
            }
            if (changed) {
                lmC[p] = newSet;
            }
            return changed;
        }
    }

    private void expand(int a, IntArrayList q) {
        final Collection<Integer> conditions = getConditionsAchievableById(a);
        for (final int p : conditions) {
            if (!getConditionInit()[p]) {
                getReachableAchievers()[p].add(a);
                final boolean changed = updateCondition(p, a);
                if (changed) {
                    updateActions(p, q, a);
                }
            }
        }
    }

    private void printLandmarks() {
        AndCond goal = (AndCond) getProblem().getGoals();
        System.out.println("Landmarks");
        for (int sg : lmA[cp.goal()]) {
            System.out.println(Terminal.getTerminal(sg));
        }
    }

    private IntArrayList quickReset(State s) {
        final IntArrayList q = new IntArrayList();
        Arrays.fill(getConditionInit(), false);
        Arrays.fill(reachedConditions, false);
        Arrays.fill(reachedActions, false);

        for (final int i : getAllConditions()) {
            allAchievers[i] = new IntArraySet();
            if (s.satisfy(Terminal.getTerminal(i))) {
                getConditionInit()[i] = true;
                reachedConditions[i] = true;
                lmC[i] = new IntOpenHashSet();
                updateActions(i, q, -1);
            }
        }
        for (final int a : freePreconditionActions) {
            q.add(a);
            lmA[a] = new IntOpenHashSet();
        }
        return q;
    }

    private int countMissing() {
        int lmCount = 0;
        for (int lm : lmA[cp.goal()]) {
            if (!getConditionInit()[lm]) {
                lmCount++;
            }
        }
        return lmCount;
    }
}
