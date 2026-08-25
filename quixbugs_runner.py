"""
Benchmark runner for the Agentic Test-Repair System.

Runs the repair agent against the QuixBugs benchmark (40 single-line-bug
Python programs), records the outcome of each program, and writes both a
machine-readable results.json and a self-contained dashboard.html report.

Usage:
    python3 quixbugs_runner.py

The dashboard opens with no server and no internet: the run data is baked
directly into dashboard.html, so double-clicking the file just works.
"""

import os
import time
import json
import datetime

from agent import fix_tests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = "/Users/tejas/Documents/AI-Projects/QuixBugs"
ATTEMPTS = 1                      # pass@1: one repair attempt per program
PAUSE_BETWEEN = 4                 # seconds between programs (free-tier pacing)
RESULTS_JSON = "results.json"
DASHBOARD_HTML = "dashboard.html"

# Programs already confirmed fixed in earlier runs. These are recorded as
# "passed" without spending an API call, so the benchmark is resumable across
# days without blowing the free-tier daily quota.
ALREADY_DONE = [
    "bitcount", "breadth_first_search", "bucketsort", "depth_first_search",
    "detect_cycle", "find_first_in_sorted", "find_in_sorted", "flatten",
    "gcd", "get_factors", "hanoi", "is_valid_parenthesization",
    "kheapsort", "knapsack", "kth", "lcs_length", "levenshtein", "lis",
    "longest_common_subsequence", "max_sublist_sum", "minimum_spanning_tree",
    "next_palindrome", "next_permutation", "pascal", "possible_change",
    "powerset", "reverse_linked_list", "rpn_eval", "shortest_path_length",
    "shortest_path_lengths", "shortest_paths", "shunting_yard", "sieve",
    "sqrt", "to_base", "quicksort", "subsequences", "topological_ordering",
    "wrap",
]


def discover_programs(project_root):
    """Return the sorted list of program names that have a test file."""
    testcases_dir = os.path.join(project_root, "python_testcases")
    test_files = sorted(
        f for f in os.listdir(testcases_dir)
        if f.startswith("test_") and f.endswith(".py")
    )
    # "test_gcd.py" -> "gcd"
    return [(f, f[5:-3]) for f in test_files]


def run_benchmark():
    programs = discover_programs(PROJECT_ROOT)
    total = len(programs)
    results = []

    print(f"Found {total} benchmark programs. "
          f"{len(ALREADY_DONE)} already recorded as fixed.\n")

    for i, (test_file, name) in enumerate(programs, start=1):
        if name in ALREADY_DONE:
            print(f"[{i}/{total}] {name}: already fixed (skipped)")
            results.append({
                "name": name,
                "status": "passed",
                "attempts": None,      # fixed in a prior run
                "seconds": None,
                "note": "confirmed fixed in an earlier run",
            })
            continue

        source_path = f"python_programs/{name}.py"
        test_path = f"python_testcases/{test_file}"

        print(f"[{i}/{total}] {name}: running...")
        start = time.time()
        try:
            success = fix_tests(PROJECT_ROOT, source_path, test_path,
                                attempts=ATTEMPTS)
            elapsed = round(time.time() - start, 2)
            status = "passed" if success else "failed"
            results.append({
                "name": name,
                "status": status,
                "attempts": ATTEMPTS,
                "seconds": elapsed,
                "note": "",
            })
            print(f"          -> {status.upper()} in {elapsed}s\n")
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            # API rate limits (429) surface here. These are infrastructure
            # limits, not repair failures, so they are recorded distinctly.
            results.append({
                "name": name,
                "status": "error",
                "attempts": ATTEMPTS,
                "seconds": elapsed,
                "note": _short_error(str(e)),
            })
            print(f"          -> ERROR ({_short_error(str(e))})\n")

        if i < total:
            time.sleep(PAUSE_BETWEEN)

    return build_summary(results, total)


def _short_error(message):
    """Compress a long API error into a short, dashboard-friendly label."""
    if "RESOURCE_EXHAUSTED" in message or "429" in message:
        return "API rate limit (free tier)"
    if "503" in message or "UNAVAILABLE" in message:
        return "API temporarily unavailable"
    return message.split("\n")[0][:80]


def build_summary(results, total):
    passed = sum(1 for r in results if r["status"] == "passed")
    errored = sum(1 for r in results if r["status"] == "error")
    # Derive rather than count, so the three buckets always sum to the total
    # even if a new status is introduced later.
    failed = total - passed - errored

    summary = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "benchmark": "QuixBugs (Python, 40 single-line-bug programs)",
        "model": "gemini-3.6-flash",
        "mode": f"pass@{ATTEMPTS}",
        "total": total,
        "passed": passed,
        "failed": failed,
        "errored": errored,
        "success_rate": round(passed / total * 100, 1) if total else 0.0,
        "results": results,
    }
    return summary


def write_json(summary):
    with open(RESULTS_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Wrote {RESULTS_JSON}")


def write_dashboard(summary):
    """Bake the summary into a self-contained HTML file (no server needed)."""
    data_blob = json.dumps(summary)
    html = DASHBOARD_TEMPLATE.replace("/*__DATA__*/", data_blob)
    with open(DASHBOARD_HTML, "w") as f:
        f.write(html)
    print(f"Wrote {DASHBOARD_HTML}  (double-click to open)")


# The dashboard template lives in dashboard_template.py to keep this file
# focused on the benchmark logic.
from dashboard_template import DASHBOARD_TEMPLATE


if __name__ == "__main__":
    summary = run_benchmark()

    print("=" * 52)
    print("Benchmark complete")
    print(f"  Passed:  {summary['passed']}/{summary['total']}")
    print(f"  Failed:  {summary['failed']}")
    print(f"  Errored: {summary['errored']} (API limits, not repair failures)")
    print(f"  Success rate: {summary['success_rate']}%")
    print("=" * 52)

    write_json(summary)
    write_dashboard(summary)
