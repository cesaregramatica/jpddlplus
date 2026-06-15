import glob
import itertools
import os
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as stats
import seaborn as sns

# Configure plot style
sns.set_theme(style="whitegrid")
plt.rcParams.update({"font.size": 12})

TIMEOUT_SEC = 300
TIMEOUT_MS = TIMEOUT_SEC * 1000


def load_and_consolidate_data(directory="."):
    """Loads all results*.csv files and keeps the latest run for each combination."""
    all_files = glob.glob(os.path.join(directory, "results_*.csv"))

    dataframes = []
    for file in all_files:
        try:
            # Extract timestamp from filename: results_YYYYMMDD_HHMMSS.csv
            filename = os.path.basename(file)
            timestamp_str = filename.replace("results_", "").replace(".csv", "")
            timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")

            df = pd.read_csv(file)
            # Only process files that have a Domain column to avoid legacy corrupt data
            if "Domain" not in df.columns:
                print(f"Skipping {file}: Missing 'Domain' column.")
                continue

            df["Timestamp"] = timestamp
            dataframes.append(df)
        except Exception as e:
            print(f"Error reading {file}: {e}")

    if not dataframes:
        print("No results*.csv files found with correct schema.")
        return None

    full_df = pd.concat(dataframes, ignore_index=True)

    # Drop rows where Domain is missing just in case
    full_df = full_df.dropna(subset=["Domain"])
    full_df = full_df[full_df["Domain"].astype(str).str.strip() != ""]

    # Sort by timestamp to ensure the latest is last
    full_df = full_df.sort_values(by="Timestamp")

    # Drop duplicates keeping the last (latest) entry
    consolidated_df = full_df.drop_duplicates(
        subset=["Domain", "Instance", "Heuristic"], keep="last"
    )

    # Remove the Timestamp column as it's no longer needed
    consolidated_df = consolidated_df.drop(columns=["Timestamp"])

    # Sort alphabetically by Domain, then Instance, then Heuristic
    consolidated_df = consolidated_df.sort_values(
        by=["Domain", "Instance", "Heuristic"]
    )

    return consolidated_df


def calculate_advanced_metrics(df):
    """Calculates coverage, speedup, IPC scores, plan quality, PAR10, and Overhead."""
    df_numeric = df.copy()

    # Gracefully add missing new columns for older results files
    for col in ["h_initial", "States_Evaluated", "Heuristic_Time_ms"]:
        if col not in df_numeric.columns:
            df_numeric[col] = np.nan

    numeric_cols = [
        "Plan_Length",
        "Search_Time_ms",
        "Expanded_Nodes",
        "Max_RAM_MB",
        "h_initial",
        "States_Evaluated",
        "Heuristic_Time_ms",
    ]
    for col in numeric_cols:
        df_numeric[col] = pd.to_numeric(
            df_numeric[col].replace("T/O", np.nan), errors="coerce"
        )

    df_numeric["Solved"] = df_numeric["Search_Time_ms"].notna() & (
        df_numeric["Search_Time_ms"] < TIMEOUT_MS
    )

    # Derived Metrics
    df_numeric["Heuristic_Accuracy_Ratio"] = np.where(
        (df_numeric["Solved"]) & (df_numeric["Plan_Length"] > 0),
        df_numeric["h_initial"] / df_numeric["Plan_Length"],
        np.nan,
    )

    df_numeric["True_Heuristic_Overhead_ms"] = np.where(
        (df_numeric["Solved"]) & (df_numeric["States_Evaluated"] > 0),
        df_numeric["Heuristic_Time_ms"] / df_numeric["States_Evaluated"],
        np.nan,
    )

    df_numeric["Branching_Factor_Indicator"] = np.where(
        (df_numeric["Solved"]) & (df_numeric["Expanded_Nodes"] > 0),
        df_numeric["States_Evaluated"] / df_numeric["Expanded_Nodes"],
        np.nan,
    )

    # Coverage
    coverage = (
        df_numeric.groupby(["Domain", "Heuristic"])["Solved"]
        .agg(["sum", "count"])
        .reset_index()
    )
    coverage.rename(
        columns={"sum": "Solved_Instances", "count": "Total_Instances"}, inplace=True
    )
    coverage["Coverage_%"] = (
        coverage["Solved_Instances"] / coverage["Total_Instances"]
    ) * 100

    solved_df = df_numeric[df_numeric["Solved"]].copy()

    # Heuristic Overhead (Time per Node)
    df_numeric["Time_per_Node_ms"] = np.where(
        (df_numeric["Solved"]) & (df_numeric["Expanded_Nodes"] > 0),
        df_numeric["Search_Time_ms"] / df_numeric["Expanded_Nodes"],
        np.nan,
    )

    # IPC Time Score
    min_time_per_instance = (
        solved_df.groupby("Instance")["Search_Time_ms"].min().reset_index()
    )
    min_time_per_instance.rename(
        columns={"Search_Time_ms": "Min_Search_Time_ms"}, inplace=True
    )
    merged_for_ipc = pd.merge(
        df_numeric, min_time_per_instance, on="Instance", how="left"
    )

    def calc_time_score(row):
        if (
            not row["Solved"]
            or pd.isna(row["Search_Time_ms"])
            or row["Search_Time_ms"] == 0
        ):
            return 0
        return row["Min_Search_Time_ms"] / row["Search_Time_ms"]

    merged_for_ipc["IPC_Time_Score"] = merged_for_ipc.apply(calc_time_score, axis=1)

    # IPC Quality Score
    min_length_per_instance = (
        solved_df.groupby("Instance")["Plan_Length"].min().reset_index()
    )
    min_length_per_instance.rename(
        columns={"Plan_Length": "Min_Plan_Length"}, inplace=True
    )
    merged_for_ipc = pd.merge(
        merged_for_ipc, min_length_per_instance, on="Instance", how="left"
    )

    def calc_quality_score(row):
        if not row["Solved"] or pd.isna(row["Plan_Length"]) or row["Plan_Length"] == 0:
            return 0
        return row["Min_Plan_Length"] / row["Plan_Length"]

    merged_for_ipc["IPC_Quality_Score"] = merged_for_ipc.apply(
        calc_quality_score, axis=1
    )

    ipc_scores = (
        merged_for_ipc.groupby("Heuristic")[["IPC_Time_Score", "IPC_Quality_Score"]]
        .sum()
        .reset_index()
    )

    # PAR10 Score
    def calc_par10(row):
        if row["Solved"]:
            return row["Search_Time_ms"]
        else:
            return TIMEOUT_MS * 10

    df_numeric["PAR10_Score"] = df_numeric.apply(calc_par10, axis=1)
    par10_scores = df_numeric.groupby("Heuristic")["PAR10_Score"].mean().reset_index()

    # Relative Pivot Tables
    pivot_time = solved_df.pivot_table(
        index="Instance", columns="Heuristic", values="Search_Time_ms"
    ).reset_index()
    pivot_length = solved_df.pivot_table(
        index="Instance", columns="Heuristic", values="Plan_Length"
    ).reset_index()
    pivot_nodes = solved_df.pivot_table(
        index="Instance", columns="Heuristic", values="Expanded_Nodes"
    ).reset_index()
    pivot_ram = solved_df.pivot_table(
        index="Instance", columns="Heuristic", values="Max_RAM_MB"
    ).reset_index()

    return (
        df_numeric,
        coverage,
        ipc_scores,
        par10_scores,
        pivot_time,
        pivot_length,
        pivot_nodes,
        pivot_ram,
    )


def run_statistical_tests(pivot_time, pivot_nodes, output_dir="output_graphs"):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    report_path = os.path.join(output_dir, "statistical_significance_report.txt")

    with open(report_path, "w") as f:
        f.write("=== Wilcoxon Signed-Rank Test Results ===\n\n")
        f.write(
            "Testing ONLD variants against baselines on commonly solved instances.\n"
        )
        f.write(
            "Null Hypothesis (H0): There is no significant difference between the two heuristics.\n"
        )
        f.write(
            "Alternative Hypothesis (H1): There is a significant difference (p < 0.05 indicates significance).\n\n"
        )

        heuristics = pivot_time.columns.tolist()
        heuristics.remove("Instance")
        onld_hs = [h for h in heuristics if "onld" in h]
        baselines = [
            h for h in heuristics if h in ["hlm-count", "hlm-count-filtered"]
        ]  # Focus tests on main baselines

        metrics = [("Search Time (ms)", pivot_time), ("Expanded Nodes", pivot_nodes)]

        for onld in onld_hs:
            for base in baselines:
                for metric_name, pivot_df in metrics:
                    f.write(f"--- {onld} vs {base} | {metric_name} ---\n")
                    common = pivot_df.dropna(subset=[onld, base])
                    n_samples = len(common)
                    f.write(f"Commonly solved instances (N): {n_samples}\n")

                    if n_samples < 5:
                        f.write(
                            "Result: Not enough samples for a reliable Wilcoxon test (N < 5).\n\n"
                        )
                        continue

                    try:
                        # wilcoxon test (two-sided by default)
                        stat, p_value = stats.wilcoxon(common[onld], common[base])
                        f.write(f"Statistic: {stat:.4f}\n")
                        f.write(f"P-value: {p_value:.4e}\n")
                        if p_value < 0.05:
                            winner = (
                                onld
                                if common[onld].median() < common[base].median()
                                else base
                            )
                            f.write(
                                f"Conclusion: SIGNIFICANT difference (p < 0.05). Median favors: {winner}\n\n"
                            )
                        else:
                            f.write(
                                "Conclusion: NO significant difference (p >= 0.05).\n\n"
                            )
                    except Exception as e:
                        f.write(f"Error computing Wilcoxon test: {e}\n\n")


def plot_scatter(h1, h2, metric, pivot_df, output_path, title):
    if h1 in pivot_df.columns and h2 in pivot_df.columns:
        common = pivot_df.dropna(subset=[h1, h2])
        if not common.empty:
            plt.figure(figsize=(8, 8))
            plt.scatter(common[h1], common[h2], alpha=0.7)
            min_val = min(common[h1].min(), common[h2].min())
            max_val = max(common[h1].max(), common[h2].max())
            if min_val > 0:
                min_val *= 0.8
            if max_val > 0:
                max_val *= 1.2
            plt.plot(
                [min_val, max_val], [min_val, max_val], "r--", label="Equal Performance"
            )
            plt.xscale("log")
            plt.yscale("log")
            plt.xlabel(f"{h1} {metric}")
            plt.ylabel(f"{h2} {metric}")
            plt.title(title)
            plt.legend()
            plt.grid(True, which="both", ls="--", alpha=0.5)
            plt.tight_layout()
            plt.savefig(output_path)
            plt.close()


def generate_graphs(
    df_numeric, pivot_time, pivot_nodes, pivot_ram, output_dir="output_graphs"
):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    solved_df = df_numeric[df_numeric["Solved"]].copy()
    heuristics = sorted(df_numeric["Heuristic"].unique())

    # Cactus Plots
    plt.figure(figsize=(10, 6))
    for h in heuristics:
        h_data = (
            solved_df[solved_df["Heuristic"] == h]["Search_Time_ms"]
            .sort_values()
            .values
        )
        y_vals = np.arange(1, len(h_data) + 1)
        plt.plot(h_data, y_vals, marker=".", linestyle="-", label=h)

    plt.xscale("log")
    plt.xlabel("Search Time (ms)")
    plt.ylabel("Number of Solved Instances")
    plt.title("Cactus Plot: Cumulative Coverage vs Time")
    plt.legend()
    plt.grid(True, which="both", ls="--", alpha=0.5)
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "cactus_plot_time.png"))
    plt.close()

    # Bar Charts
    coverage_data = (
        df_numeric.groupby(["Domain", "Heuristic"])["Solved"]
        .sum()
        .unstack(fill_value=0)
    )
    coverage_data.index = [
        d.split("/")[-2] if len(d.split("/")) > 1 else d for d in coverage_data.index
    ]
    coverage_data.plot(kind="bar", figsize=(14, 7), width=0.8)
    plt.title("Instances Solved per Domain by Heuristic")
    plt.xlabel("Domain")
    plt.ylabel("Number of Solved Instances")
    plt.xticks(rotation=45, ha="right")
    plt.legend(title="Heuristic", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, "domain_coverage_bar.png"))
    plt.close()

    # Scatter Plots (Time, Nodes, RAM)
    onld_hs = [h for h in heuristics if "onld" in h]
    baselines = [h for h in heuristics if "onld" not in h]

    for target in onld_hs:
        for base in baselines:
            plot_scatter(
                base,
                target,
                "Time (ms)",
                pivot_time,
                os.path.join(output_dir, f"scatter_time_{target}_vs_{base}.png"),
                f"Head-to-Head Search Time: {target} vs {base}",
            )
            plot_scatter(
                base,
                target,
                "Expanded Nodes",
                pivot_nodes,
                os.path.join(output_dir, f"scatter_nodes_{target}_vs_{base}.png"),
                f"Head-to-Head Expanded Nodes: {target} vs {base}",
            )
            plot_scatter(
                base,
                target,
                "Max RAM (MB)",
                pivot_ram,
                os.path.join(output_dir, f"scatter_ram_{target}_vs_{base}.png"),
                f"Head-to-Head Max RAM: {target} vs {base}",
            )

    for h1, h2 in itertools.combinations(onld_hs, 2):
        plot_scatter(
            h1,
            h2,
            "Time (ms)",
            pivot_time,
            os.path.join(output_dir, f"scatter_time_{h2}_vs_{h1}.png"),
            f"Head-to-Head Search Time: {h2} vs {h1}",
        )
        plot_scatter(
            h1,
            h2,
            "Expanded Nodes",
            pivot_nodes,
            os.path.join(output_dir, f"scatter_nodes_{h2}_vs_{h1}.png"),
            f"Head-to-Head Expanded Nodes: {h2} vs {h1}",
        )
        plot_scatter(
            h1,
            h2,
            "Max RAM (MB)",
            pivot_ram,
            os.path.join(output_dir, f"scatter_ram_{h2}_vs_{h1}.png"),
            f"Head-to-Head Max RAM: {h2} vs {h1}",
        )

    # Best 4 Comparisons
    best_4 = ["hlm-count", "hlm-count-filtered", "onld-local", "onld-hadd"]
    best_4_present = [h for h in best_4 if h in heuristics]

    if len(best_4_present) > 1:
        best_4_df = solved_df[solved_df["Heuristic"].isin(best_4_present)]

        # Overhead Boxplot (Time per Node)
        plt.figure(figsize=(10, 6))
        sns.boxplot(
            data=best_4_df.dropna(subset=["Time_per_Node_ms"]),
            x="Heuristic",
            y="Time_per_Node_ms",
            order=best_4_present,
        )
        plt.yscale("log")
        plt.title("Heuristic Overhead: Time per Expanded Node (Best 4)")
        plt.ylabel("Time per Node (ms)")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "boxplot_overhead_best_4.png"))
        plt.close()

        # RAM Boxplot
        plt.figure(figsize=(10, 6))
        sns.boxplot(data=best_4_df, x="Heuristic", y="Max_RAM_MB", order=best_4_present)
        plt.yscale("log")
        plt.title("Space Complexity: Max RAM Usage (Best 4)")
        plt.ylabel("Max RAM (MB)")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "boxplot_ram_best_4.png"))
        plt.close()

        # True Heuristic Overhead Boxplot
        plt.figure(figsize=(10, 6))
        sns.boxplot(
            data=best_4_df.dropna(subset=["True_Heuristic_Overhead_ms"]),
            x="Heuristic",
            y="True_Heuristic_Overhead_ms",
            order=best_4_present,
        )
        plt.yscale("log")
        plt.title("True Heuristic Overhead: Time per State Evaluated (Best 4)")
        plt.ylabel("Time per State Evaluated (ms)")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "boxplot_true_overhead_best_4.png"))
        plt.close()

        # Heuristic Accuracy Ratio Boxplot
        plt.figure(figsize=(10, 6))
        sns.boxplot(
            data=best_4_df.dropna(subset=["Heuristic_Accuracy_Ratio"]),
            x="Heuristic",
            y="Heuristic_Accuracy_Ratio",
            order=best_4_present,
        )
        plt.title("Heuristic Accuracy Ratio: h(I) / Plan Length (Best 4)")
        plt.ylabel("h(I) / Plan Length")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "boxplot_accuracy_ratio_best_4.png"))
        plt.close()

        # Branching Factor Indicator Boxplot
        plt.figure(figsize=(10, 6))
        sns.boxplot(
            data=best_4_df.dropna(subset=["Branching_Factor_Indicator"]),
            x="Heuristic",
            y="Branching_Factor_Indicator",
            order=best_4_present,
        )
        plt.title(
            "Branching Factor Indicator: States Evaluated / Expanded Nodes (Best 4)"
        )
        plt.ylabel("States Evaluated / Expanded Nodes")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "boxplot_branching_factor_best_4.png"))
        plt.close()


if __name__ == "__main__":
    print("Loading and consolidating data...")
    df_consolidated = load_and_consolidate_data()

    if df_consolidated is not None:
        df_consolidated.to_csv("latest_results_consolidated.csv", index=False)
        print("Saved latest_results_consolidated.csv")

        print("Calculating advanced scientific metrics...")
        (
            df_numeric,
            coverage,
            ipc_scores,
            par10_scores,
            pivot_time,
            pivot_length,
            pivot_nodes,
            pivot_ram,
        ) = calculate_advanced_metrics(df_consolidated)

        coverage.to_csv("advanced_metrics_coverage.csv", index=False)
        ipc_scores.to_csv("advanced_metrics_ipc.csv", index=False)
        par10_scores.to_csv("advanced_metrics_par10.csv", index=False)

        # Aggregate the new metrics by Heuristic
        df_numeric["h_initial"] = np.where(
            df_numeric["Solved"], df_numeric["h_initial"], np.nan
        )
        heuristic_summary = (
            df_numeric.groupby("Heuristic")[
                [
                    "h_initial",
                    "Heuristic_Accuracy_Ratio",
                    "True_Heuristic_Overhead_ms",
                    "Branching_Factor_Indicator",
                ]
            ]
            .mean()
            .reset_index()
        )
        heuristic_summary.to_csv("advanced_metrics_heuristics.csv", index=False)
        print("Saved advanced_metrics_heuristics.csv")

        print("Running statistical significance tests...")
        run_statistical_tests(pivot_time, pivot_nodes, output_dir="output_graphs")
        print("Saved statistical_significance_report.txt")

        print("Generating scientific info-graphs...")
        generate_graphs(df_numeric, pivot_time, pivot_nodes, pivot_ram)
        print("Graphs saved to output_graphs/ directory.")
        print("Done.")
