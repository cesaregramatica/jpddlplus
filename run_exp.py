import argparse
import csv
import os
import re
import signal
import subprocess
import threading
import time
from datetime import datetime

import psutil

heuristics = ["onld-local", "onld-hadd", "hlm-count-filtered"]
timeout_sec = 600


def find_problems(base_dir):
    problems = []
    for root, dirs, files in os.walk(base_dir):
        if "domain.pddl" in files:
            domain_path = os.path.join(root, "domain.pddl")
            # Find instances in the same directory
            for f in files:
                if f.endswith(".pddl") and f != "domain.pddl":
                    problems.append((domain_path, os.path.join(root, f)))

            # Also check immediate subdirectories for instances (like sailing/small_instances)
            for d in dirs:
                sub_dir = os.path.join(root, d)
                for sub_root, _, sub_files in os.walk(sub_dir):
                    if "domain.pddl" not in sub_files:
                        for f in sub_files:
                            if f.endswith(".pddl"):
                                problems.append(
                                    (domain_path, os.path.join(sub_root, f))
                                )
    return sorted(problems)


def run_experiment(domain_file, instance_file, h):
    cmd = [
        "java",
        "-Xmx20g",
        "-jar",
        "enhsp25.jar",
        "-o",
        domain_file,
        "-f",
        instance_file,
        "-h",
        h,
        "-timeout",
        str(timeout_sec),
    ]
    plan_length, time_ms, exp_nodes, max_ram_mb = "T/O", "T/O", "T/O", "T/O"
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )

        # Track RAM usage in a separate thread
        max_ram_bytes = [0]
        stop_monitoring = threading.Event()

        def monitor_ram():
            try:
                p = psutil.Process(proc.pid)
                while not stop_monitoring.is_set():
                    try:
                        # Get memory usage including child processes
                        mem = p.memory_info().rss
                        for child in p.children(recursive=True):
                            try:
                                mem += child.memory_info().rss
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                pass
                        max_ram_bytes[0] = max(max_ram_bytes[0], mem)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        break
                    time.sleep(0.1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        monitor_thread = threading.Thread(target=monitor_ram, daemon=True)
        monitor_thread.start()

        try:
            out, err = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            out, err = proc.communicate()
        finally:
            stop_monitoring.set()
            monitor_thread.join(timeout=1)

        # Convert bytes to MB
        max_ram_mb = (
            round(max_ram_bytes[0] / (1024 * 1024), 2) if max_ram_bytes[0] > 0 else 0
        )

        m_len = re.search(r"Plan-Length:(\d+)", out)
        m_time = re.search(r"Search Time \(msec\): (\d+)", out)
        m_exp = re.search(r"Expanded Nodes:(\d+)", out)
        if m_len:
            plan_length = m_len.group(1)
        if m_time:
            time_ms = m_time.group(1)
        if m_exp:
            exp_nodes = m_exp.group(1)
        if "Problem Solved" not in out and plan_length == "T/O":
            if "OutOfMemoryError" in err or "OutOfMemoryError" in out:
                plan_length, time_ms, exp_nodes, max_ram_mb = (
                    "OOM",
                    "OOM",
                    "OOM",
                    max_ram_mb,
                )
            elif plan_length == "T/O":
                pass
            else:
                plan_length, time_ms, exp_nodes = "Fail", "Fail", "Fail"
    except Exception as e:
        plan_length, time_ms, exp_nodes, max_ram_mb = "Error", "Error", "Error", "Error"

    return {
        "Domain": domain_file,
        "Instance": instance_file,
        "Heuristic": h,
        "Plan_Length": plan_length,
        "Search_Time_ms": time_ms,
        "Expanded_Nodes": exp_nodes,
        "Max_RAM_MB": max_ram_mb,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ENHSP planning experiments")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output CSV filename (if not provided, timestamp will be added to 'results.csv')",
    )
    args = parser.parse_args()

    if args.output:
        output_filename = args.output
        if not output_filename.endswith(".csv"):
            output_filename += ".csv"
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"results_{timestamp}.csv"

    print(
        f"Running experiments... Results will be saved incrementally to: {output_filename}"
    )

    problems = find_problems("examples/pddl2_1")
    total_runs = len(problems) * len(heuristics)
    print(f"Found {len(problems)} instances. Total runs to execute: {total_runs}")

    fieldnames = [
        "Domain",
        "Instance",
        "Heuristic",
        "Plan_Length",
        "Search_Time_ms",
        "Expanded_Nodes",
        "Max_RAM_MB",
    ]

    # Initialize CSV file with header
    with open(output_filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

    current_run = 0
    for domain_file, instance_file in problems:
        for h in heuristics:
            current_run += 1
            print(
                f"[{current_run}/{total_runs}] Running {instance_file} with {h}...",
                flush=True,
            )

            result = run_experiment(domain_file, instance_file, h)

            # Write incrementally
            with open(output_filename, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(result)

    print(f"All experiments finished. Results saved to: {output_filename}")
