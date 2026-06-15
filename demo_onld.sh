#!/bin/bash

# Determine java executable
if command -v java >/dev/null 2>&1; then
  JAVA_CMD="java"
else
  JAVA_CMD="/usr/lib/jvm/java-21-amazon-corretto/bin/java"
fi

echo "=========================================================="
echo "Starting ONLD Demo for ENHSP Planner"
echo "=========================================================="

echo ""
echo "[INFO] Step 1: Compiling the planner using compile.sh..."
bash compile.sh

if [ ! -f "enhsp25.jar" ]; then
    echo "[ERROR] enhsp25.jar not found! Compilation might have failed."
    exit 1
fi
echo "[SUCCESS] Planner compiled successfully."

DOMAIN="examples/pddl2_1/counters/domain.pddl"
PROBLEMS=("examples/pddl2_1/counters/instance_2.pddl" "examples/pddl2_1/counters/instance_4.pddl" "examples/pddl2_1/counters/instance_8.pddl")
HEURISTICS=("onld-local" "onld-hadd")

echo ""
echo "[INFO] Step 2: Running planner on selected instances..."

for problem in "${PROBLEMS[@]}"; do
    for h in "${HEURISTICS[@]}"; do
        echo ""
        echo "----------------------------------------------------------"
        echo "Testing Instance: $(basename $problem)"
        echo "Heuristic:        $h"
        echo "----------------------------------------------------------"
        $JAVA_CMD -jar enhsp25.jar -o "$DOMAIN" -f "$problem" -h "$h"
    done
done

echo ""
echo "=========================================================="
echo "Demo Completed Successfully"
echo "=========================================================="
