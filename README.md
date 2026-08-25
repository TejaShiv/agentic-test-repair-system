# Agentic Test-Repair System

An autonomous agent that fixes failing tests. Point it at a project with a
failing test suite; it runs the tests, sends the failing code and the error to
an LLM, applies the returned fix, re-runs the suite to verify, and retries up to
a limit before giving up.

It is a small, focused tool built to be understood end to end — not a wrapper
around a chat interface. The difference from pasting code into ChatGPT is the
**closed loop**: the agent runs the real test suite, localizes the failure,
applies a change to the file, and *verifies* by re-running — with no human
shuttling code back and forth.

**Benchmark result:** 39/40 on QuixBugs (pass@1). The single incomplete case was
blocked by a free-tier API rate limit, not a repair failure. Fixes were spot-checked
against the benchmark's reference solutions to confirm they were genuine repairs.

---

## How it works

```
run tests ──▶ tests pass? ──yes──▶ done
                  │
                  no
                  ▼
        read the source file
                  ▼
    send (error output + source) to the LLM
                  ▼
        write the returned fix to the file
                  ▼
           re-run the tests
                  │
        pass? ──yes──▶ done
          │
          no ──▶ feed the new error back, retry (up to N attempts)
                  │
             out of attempts ──▶ report unfixed
```

The core loop is deliberately simple. The engineering is in the parts around it:
capturing test output reliably, timing out on infinite-loop bugs, constraining the
model to return only code, running against an arbitrary target directory, and
recording results.

## Repository layout

| File | Purpose |
|------|---------|
| `repair.py` | **The developer entry point.** Point it at a project; it discovers failing tests, repairs them, and writes the report. |
| `agent.py` | The repair agent: builds the prompt, calls the model, applies the fix, drives the retry loop (`fix_tests`). |
| `runner.py` | Runs a test suite in a target directory via `pytest` and returns pass/fail + output, with a timeout for hanging tests (`run_tests`). |
| `quixbugs_runner.py` | Benchmark harness: runs the agent across the QuixBugs suite to produce the published result. |
| `dashboard_template.py` | The self-contained HTML report template. |
| `prompt.txt` | The instruction sent to the model (constrains it to return only corrected code, no hardcoding). |
| `results.json` | Machine-readable results from the last run. |
| `dashboard.html` | Generated visual report — open it in a browser, no server needed. |

## Running it

Requirements: Python 3, `pytest`, and a Gemini API key.

```bash
pip install -r requirements.txt
echo "GEMINI_API_KEY=your_key_here" > .env
```

### Repair your own project

```bash
python3 repair.py /path/to/your/project
```

It walks the project, finds test files (`test_*.py` / `*_test.py`), infers the
source file each one exercises from the naming convention, and repairs the ones
that fail. Progress prints live to the console, then it writes `results.json`
and `dashboard.html`.

When the convention doesn't apply, name the pair explicitly:

```bash
python3 repair.py /path/to/project --source src/foo.py --test tests/test_foo.py
```

Other options:

| Flag | Effect |
|------|--------|
| `--attempts N` | Repair attempts per test (default 3) |
| `--dry-run` | Report what would be repaired, change nothing |
| `--no-dashboard` | Skip generating `dashboard.html` |

Start with `--dry-run` on an unfamiliar project: it shows which tests fail and
which files would be edited, without touching anything.

### Reproduce the benchmark

```bash
python3 quixbugs_runner.py
```

Expects the QuixBugs repo cloned locally; set the path at the top of the file.

## Benchmark and methodology

The agent is evaluated on **QuixBugs** — 40 classic algorithms, each with a
single-line bug and a test suite that the buggy version fails. QuixBugs is a
standard academic program-repair benchmark, which makes the result comparable to
published work rather than to hand-picked toy cases.

- **pass@1**: each program gets a single repair attempt, matching how repair
  results are reported in the literature.
- **Verification**: a fix "passes" only if it makes the program's full,
  multi-input test suite pass — not a single weak assertion.
- **Validation**: passing fixes were spot-checked against QuixBugs' reference
  solutions to confirm they are genuine repairs, not the model gaming a weak test.

## Honest limitations

These are real and worth stating plainly — they are also the most interesting part
of the project.

- **The objective can be gamed.** The agent's goal is "make the failing test
  pass." When a test is *wrong* or impossible, the model will satisfy it by
  corrupting correct code (e.g. hardcoding a return value). Prompt rules reduce the
  obvious cheats but cannot eliminate them, because the incentive to pass the test
  at any cost remains. This is a fundamental limitation of test-driven repair, not
  a bug in the implementation.
- **It assumes the test is correct.** When a test fails, either the code or the
  test is wrong, and the failure alone doesn't say which. This tool assumes the
  test defines correct behavior and repairs the code. That assumption is stated,
  not hidden.
- **Single-file scope.** It repairs one source file per failing test. Multi-file
  bugs (as in project-scale benchmarks like Defects4J) are out of scope.
- **QuixBugs is easy for modern LLMs.** Single-line algorithmic bugs, and a
  benchmark old enough to plausibly be in training data, mean a near-perfect score
  should be read as an upper bound — not evidence the approach handles hard, novel
  bugs.

## Possible next steps

- Localize the source file from the failure automatically (rather than being told).
- Run as a CI check that proposes fixes on a pull request instead of on demand.
- Evaluate on a harder, less-memorized benchmark to find the real breaking point.
- A toggle so it can watch a project and repair on demand, staying out of the way
  while the developer is intentionally mid-change.
