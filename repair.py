"""
repair.py - the developer-facing entry point for the Agentic Test-Repair System.

Point it at a project with failing tests. It runs the suite, repairs the source
for each failing test, verifies by re-running, and writes a report.

Usage
-----
Convention mode (default) - discovers test files and infers the source file
from the standard naming convention (test_foo.py -> foo.py):

    python3 repair.py /path/to/project

Explicit mode - name the pair yourself when the convention does not apply:

    python3 repair.py /path/to/project --source src/foo.py --test tests/test_foo.py

Options
-------
    --attempts N     repair attempts per test (default 3)
    --dry-run        report what would be repaired, change nothing
    --no-dashboard   skip generating dashboard.html

Output
------
Live progress in the console, plus results.json and dashboard.html in the
current directory. Open dashboard.html in a browser - no server required.
"""

import os
import sys
import time
import json
import argparse
import datetime

from agent import fix_tests
from runner import run_tests
from dashboard_template import DASHBOARD_TEMPLATE

RESULTS_JSON = "results.json"
DASHBOARD_HTML = "dashboard.html"

# Directories that are never worth scanning for tests.
IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
    "node_modules", ".tox", "build", "dist", ".mypy_cache", ".idea",
}

# Directories that hold reference / known-good copies of code. The agent must
# never edit these: they are the answer key, not the code under repair.
# (QuixBugs ships correct_python_programs/ next to python_programs/, and many
# repos keep golden or expected copies the same way.)
REFERENCE_DIR_PREFIXES = (
    "correct_", "reference", "expected", "golden", "baseline", "fixtures",
    "snapshots", "testdata",
)


def is_reference_path(rel_path):
    """True if any directory in the path looks like reference/known-good code."""
    parts = os.path.normpath(rel_path).split(os.sep)[:-1]  # dirs only
    return any(
        p.lower().startswith(REFERENCE_DIR_PREFIXES) for p in parts
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def find_test_files(project_root):
    """
    Walk the project and return test file paths relative to the root.

    Test files inside reference/known-good directories are ignored, and if two
    test files target the same source (some repos ship both test_foo.py and
    foo_test.py), only the first is kept so the agent does not repair the same
    file twice.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            if name.startswith("test_") or name.endswith("_test.py"):
                abs_path = os.path.join(dirpath, name)
                rel = os.path.relpath(abs_path, project_root)
                if is_reference_path(rel):
                    continue
                found.append(rel)

    # Prefer the conventional test_*.py form when a source has two test files,
    # then shallower paths, then alphabetical - so the primary suite wins over
    # a stray duplicate sitting next to the source.
    found.sort(key=lambda p: (
        0 if os.path.basename(p).startswith("test_") else 1,
        len(os.path.normpath(p).split(os.sep)),
        p,
    ))

    # De-duplicate by the source file each test targets.
    seen = set()
    unique = []
    for rel in found:
        key = source_name_for(rel)
        if key in seen:
            continue
        seen.add(key)
        unique.append(rel)
    return unique


def source_name_for(test_filename):
    """test_foo.py -> foo.py   |   foo_test.py -> foo.py"""
    base = os.path.basename(test_filename)
    if base.startswith("test_"):
        return base[len("test_"):]
    if base.endswith("_test.py"):
        return base[:-len("_test.py")] + ".py"
    return base


def guess_source_path(project_root, test_path):
    """
    Infer the source file a test exercises, using the naming convention.

    Reference/known-good directories are never returned - the agent must not
    edit the answer key. When a filename appears in several places, the
    shallowest non-reference match wins; if that is still ambiguous, return
    None so the caller can ask for an explicit --source/--test pair.
    """
    wanted = source_name_for(test_path)

    # 1. Same directory as the test (unless that directory is a reference copy).
    sibling = os.path.join(os.path.dirname(test_path), wanted)
    if (os.path.isfile(os.path.join(project_root, sibling))
            and not is_reference_path(sibling)):
        return sibling

    # 2. Search the project, skipping reference directories entirely.
    matches = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        if wanted not in filenames:
            continue
        rel = os.path.relpath(os.path.join(dirpath, wanted), project_root)
        if is_reference_path(rel):
            continue
        if os.path.basename(rel).startswith("test_"):
            continue
        matches.append(rel)

    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Several real candidates: prefer the shallowest path, which is almost
    # always the primary source rather than a copy nested deeper.
    matches.sort(key=lambda p: (len(os.path.normpath(p).split(os.sep)), p))
    if (len(os.path.normpath(matches[0]).split(os.sep))
            < len(os.path.normpath(matches[1]).split(os.sep))):
        return matches[0]

    # Genuinely ambiguous - make the developer choose.
    return None


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------
def repair_one(project_root, source_path, test_path, attempts, dry_run):
    """Repair a single (source, test) pair. Returns a result record."""
    label = os.path.basename(test_path)
    print(f"  {label}: ", end="", flush=True)

    code, _ = run_tests(test_path, project_root)
    if code == 0:
        print("already passing")
        return {"name": label, "source": source_path, "status": "passing",
                "attempts": 0, "seconds": 0.0, "note": "no repair needed"}

    if dry_run:
        print(f"failing -> would repair {source_path}")
        return {"name": label, "source": source_path, "status": "would-repair",
                "attempts": 0, "seconds": 0.0, "note": "dry run"}

    start = time.time()
    try:
        fixed = fix_tests(project_root, source_path, test_path, attempts=attempts)
        elapsed = round(time.time() - start, 2)
        status = "repaired" if fixed else "unfixed"
        print(f"{'repaired' if fixed else 'could not repair'} ({elapsed}s)")
        return {"name": label, "source": source_path, "status": status,
                "attempts": attempts, "seconds": elapsed, "note": ""}
    except Exception as e:
        elapsed = round(time.time() - start, 2)
        note = short_error(str(e))
        print(f"error - {note}")
        return {"name": label, "source": source_path, "status": "error",
                "attempts": attempts, "seconds": elapsed, "note": note}


def short_error(message):
    if "RESOURCE_EXHAUSTED" in message or "429" in message:
        return "API rate limit"
    if "503" in message or "UNAVAILABLE" in message:
        return "API unavailable"
    return message.split("\n")[0][:80]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def build_summary(project_root, results, mode, attempts):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    total = len(results)
    # "Green" means the suite ends up passing: already passing, or repaired.
    green = counts.get("repaired", 0) + counts.get("passing", 0)
    errored = counts.get("error", 0)
    # Everything else is a test that is still failing: either the agent could
    # not repair it ("unfixed"), or this was a dry run and no repair was
    # attempted ("would-repair"). Deriving this rather than counting specific
    # statuses guarantees the three buckets always sum to the total.
    still_failing = total - green - errored

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "benchmark": f"Project: {os.path.basename(os.path.abspath(project_root))}",
        "model": os.environ.get("REPAIR_MODEL", "gemini-3.6-flash"),
        "mode": f"{mode}, up to {attempts} attempt(s) per test",
        "total": total,
        "passed": green,
        "failed": still_failing,
        "errored": errored,
        "success_rate": round(green / total * 100, 1) if total else 0.0,
        "results": [
            {
                "name": r["name"],
                # map tool statuses onto the dashboard's visual vocabulary
                "status": ("passed" if r["status"] in ("repaired", "passing")
                           else "error" if r["status"] == "error"
                           else "failed"),
                "attempts": r["attempts"],
                "seconds": r["seconds"] or None,
                "note": r["note"] or (r["source"] if r["status"] != "error" else r["note"]),
            }
            for r in results
        ],
    }


def write_reports(summary, make_dashboard=True):
    with open(RESULTS_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nWrote {RESULTS_JSON}")

    if make_dashboard:
        html = DASHBOARD_TEMPLATE.replace("/*__DATA__*/", json.dumps(summary))
        with open(DASHBOARD_HTML, "w") as f:
            f.write(html)
        print(f"Wrote {DASHBOARD_HTML} - open it in a browser")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Repair failing tests in a project using an LLM agent.")
    parser.add_argument("project", help="path to the project to repair")
    parser.add_argument("--source", help="source file to fix (relative to project)")
    parser.add_argument("--test", help="test file to run (relative to project)")
    parser.add_argument("--attempts", type=int, default=3,
                        help="repair attempts per test (default 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be repaired without changing files")
    parser.add_argument("--no-dashboard", action="store_true",
                        help="skip generating dashboard.html")
    args = parser.parse_args()

    project_root = os.path.abspath(args.project)
    if not os.path.isdir(project_root):
        sys.exit(f"Not a directory: {project_root}")

    if bool(args.source) != bool(args.test):
        sys.exit("--source and --test must be used together.")

    print(f"Project: {project_root}")
    if args.dry_run:
        print("Dry run - no files will be changed.")

    results = []

    # ---- explicit mode ----
    if args.source:
        mode = "explicit pair"
        print(f"Mode: explicit ({args.source} <- {args.test})\n")
        if not os.path.isfile(os.path.join(project_root, args.source)):
            sys.exit(f"Source file not found: {args.source}")
        if not os.path.isfile(os.path.join(project_root, args.test)):
            sys.exit(f"Test file not found: {args.test}")
        results.append(repair_one(project_root, args.source, args.test,
                                  args.attempts, args.dry_run))

    # ---- convention mode ----
    else:
        mode = "convention discovery"
        test_files = find_test_files(project_root)
        if not test_files:
            sys.exit("No test files found (looked for test_*.py and *_test.py).")

        print(f"Mode: convention - found {len(test_files)} test file(s)\n")

        for test_path in test_files:
            source_path = guess_source_path(project_root, test_path)
            if source_path is None:
                label = os.path.basename(test_path)
                print(f"  {label}: skipped - could not infer source file")
                results.append({
                    "name": label, "source": "", "status": "error",
                    "attempts": 0, "seconds": 0.0,
                    "note": "source not found; pass --source and --test",
                })
                continue
            results.append(repair_one(project_root, source_path, test_path,
                                      args.attempts, args.dry_run))

    summary = build_summary(project_root, results, mode, args.attempts)

    print("\n" + "=" * 52)
    print("Repair complete")
    print(f"  Green:   {summary['passed']}/{summary['total']}")
    print(f"  Unfixed: {summary['failed']}")
    print(f"  Errors:  {summary['errored']}")
    print("=" * 52)

    write_reports(summary, make_dashboard=not args.no_dashboard)


if __name__ == "__main__":
    main()
