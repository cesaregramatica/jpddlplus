import argparse
import csv
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import psutil

timeout_sec = 300


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


def run_experiment(domain_file, instance_file, h, jvm_xmx="20g"):
    java_bin = (
        "java"
        if shutil.which("java")
        else "/usr/lib/jvm/java-21-amazon-corretto/bin/java"
    )
    cmd = [
        java_bin,
        f"-Xmx{jvm_xmx}",
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
    h_initial, states_eval, heuristic_time = "T/O", "T/O", "T/O"
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
        m_h_init = re.search(r"h\(I\):(\S+)", out)
        m_states_eval = re.search(r"States Evaluated:(\d+)", out)
        m_h_time = re.search(r"Heuristic Time \(msec\): (\d+)", out)

        if m_len:
            plan_length = m_len.group(1)
        if m_time:
            time_ms = m_time.group(1)
        if m_exp:
            exp_nodes = m_exp.group(1)
        if m_h_init:
            h_initial = m_h_init.group(1)
        if m_states_eval:
            states_eval = m_states_eval.group(1)
        if m_h_time:
            heuristic_time = m_h_time.group(1)

        if "Problem Solved" not in out:
            if "OutOfMemoryError" in err or "OutOfMemoryError" in out:
                plan_length, time_ms, exp_nodes, max_ram_mb = (
                    "OOM",
                    "OOM",
                    "OOM",
                    max_ram_mb,
                )
                h_initial, states_eval, heuristic_time = "OOM", "OOM", "OOM"
            elif plan_length == "T/O":
                pass
            else:
                plan_length, time_ms, exp_nodes = "Fail", "Fail", "Fail"
                h_initial, states_eval, heuristic_time = "Fail", "Fail", "Fail"
    except Exception as e:
        plan_length, time_ms, exp_nodes, max_ram_mb = "Error", "Error", "Error", "Error"
        h_initial, states_eval, heuristic_time = "Error", "Error", "Error"

    return {
        "Domain": domain_file,
        "Instance": instance_file,
        "Heuristic": h,
        "Plan_Length": plan_length,
        "Search_Time_ms": time_ms,
        "Expanded_Nodes": exp_nodes,
        "Max_RAM_MB": max_ram_mb,
        "h_initial": h_initial,
        "States_Evaluated": states_eval,
        "Heuristic_Time_ms": heuristic_time,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ENHSP planning experiments")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output CSV filename (if not provided, timestamp will be added to 'results.csv')",
    )
    parser.add_argument(
        "-j",
        "--parallel",
        type=int,
        default=1,
        help="Number of concurrent experiments to run (default: 1)",
    )
    parser.add_argument(
        "--jvm-xmx",
        type=str,
        default="20g",
        help="Maximum memory allocation pool for JVM (e.g. 6g, 20g; default: 20g)",
    )
    parser.add_argument(
        "--heuristics",
        type=str,
        nargs="+",
        default=[
            "onld-local",
            "onld-hadd",
            "hlm-count",
            "hlm-count-filtered",
            "hadd",
            "hmax",
        ],
        help="Heuristics to evaluate",
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
        f"Running experiments (parallel={args.parallel}, jvm_xmx={args.jvm_xmx})... "
        f"Results will be saved incrementally to: {output_filename}"
    )

    problems = find_problems("examples/pddl2_1")
    total_runs = len(problems) * len(args.heuristics)
    print(f"Found {len(problems)} instances. Total runs to execute: {total_runs}")

    fieldnames = [
        "Domain",
        "Instance",
        "Heuristic",
        "Plan_Length",
        "Search_Time_ms",
        "Expanded_Nodes",
        "Max_RAM_MB",
        "h_initial",
        "States_Evaluated",
        "Heuristic_Time_ms",
    ]

    # Initialize CSV file with header
    with open(output_filename, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

    completed_runs = 0
    progress_lock = threading.Lock()
    csv_lock = threading.Lock()

    def worker(task):
        global completed_runs
        domain_file, instance_file, h = task

        with progress_lock:
            print(f"Starting {instance_file} with {h}...", flush=True)

        result = run_experiment(domain_file, instance_file, h, jvm_xmx=args.jvm_xmx)

        with progress_lock:
            completed_runs += 1
            status = (
                "Solved"
                if result["Plan_Length"] not in ["T/O", "OOM", "Fail", "Error"]
                else result["Plan_Length"]
            )
            print(
                f"[{completed_runs}/{total_runs}] Finished {instance_file} with {h} ({status}). "
                f"Time: {result['Search_Time_ms']} ms, RAM: {result['Max_RAM_MB']} MB, "
                f"h(I): {result['h_initial']}, States: {result['States_Evaluated']}, H_Time: {result['Heuristic_Time_ms']} ms",
                flush=True,
            )

        with csv_lock:
            with open(output_filename, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writerow(result)

    tasks = []
    for domain_file, instance_file in problems:
        for h in args.heuristics:
            tasks.append((domain_file, instance_file, h))

    if args.parallel > 1:
        with ThreadPoolExecutor(max_workers=args.parallel) as executor:
            executor.map(worker, tasks)
    else:
        for task in tasks:
            worker(task)

    print(f"All experiments finished. Results saved to: {output_filename}")
