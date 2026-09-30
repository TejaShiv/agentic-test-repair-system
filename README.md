# Agentic Code-Repair System

An agent that fixes failing tests on its own. You point it at a project, it runs the tests, sends the broken code and the error to an LLM, applies whatever fix comes back, then runs the tests again to check if it actually worked. If it didn't, it tries again with the new error.

The reason this isn't just "paste your code into ChatGPT" is the loop. ChatGPT can't run your test suite, can't edit your files, and can't tell you whether its fix worked. This does all three without you in the middle copying things back and forth.

**Result: 39 out of 40 on QuixBugs.** The one that didn't finish got blocked by a free-tier API rate limit before it could attempt a fix, so it's not a repair failure. I spot-checked the fixes against QuixBugs' reference solutions to make sure the agent was really fixing things and not just gaming the tests.

## How it works

```
run tests ──▶ do they pass? ──yes──▶ done
                  │
                  no
                  ▼
        read the source file
                  ▼
    send the error + the code to the LLM
                  ▼
        write the fix back to the file
                  ▼
           run the tests again
                  │
        pass? ──yes──▶ done
          │
          no ──▶ send the new error back and retry (up to N times)
                  │
             out of tries ──▶ report it as unfixed
```

The loop itself is simple. Most of the actual work went into the stuff around it: capturing test output properly, not hanging forever on bugs that cause infinite loops, getting the model to return only code instead of a chatty explanation, making it work on any directory you point it at, and not accidentally editing files it shouldn't touch.

## What's in here

| File | What it does |
|------|--------------|
| `repair.py` | Start here. This is what you run on a project. |
| `agent.py` | The agent itself. Builds the prompt, calls the model, writes the fix, handles retries. |
| `runner.py` | Runs pytest in whatever directory you give it and hands back pass/fail plus the output. Has a timeout so hanging tests don't freeze everything. |
| `quixbugs_runner.py` | The benchmark script I used to get the 39/40 number. |
| `dashboard_template.py` | The HTML for the report. |
| `prompt.txt` | What gets sent to the model. Mostly telling it to return only code and not to hardcode values to make tests pass. |
| `dashboard.html` | The generated report. Open it in a browser, no server needed. |

## Running it

You'll need Python 3, pytest, and a Gemini API key.

```bash
pip install -r requirements.txt
echo "GEMINI_API_KEY=your_key_here" > .env
```

### On your own project

```bash
python3 repair.py /path/to/your/project
```

It looks through the project for test files (`test_*.py` or `*_test.py`), figures out which source file each test is testing based on the naming, and fixes the ones that fail. You'll see progress in the terminal as it goes, and it writes out `results.json` and `dashboard.html` at the end.

If your project doesn't follow the usual naming, just tell it which files to use:

```bash
python3 repair.py /path/to/project --source src/foo.py --test tests/test_foo.py
```

Flags:

| Flag | What it does |
|------|--------------|
| `--attempts N` | How many times to retry per test (default 3) |
| `--dry-run` | Shows you what it would fix without changing anything |
| `--no-dashboard` | Skip making the HTML report |

Use `--dry-run` first on any project you don't know well. It'll show you which tests are failing and which files it plans to edit, without touching anything. I added this after it almost overwrote QuixBugs' reference solutions on my first real run, which would have destroyed the thing I was validating against.

### Reproducing the benchmark

```bash
python3 quixbugs_runner.py
```

You'll need QuixBugs cloned locally and the path set at the top of the file.

## About the benchmark

I used QuixBugs, which is 40 classic algorithms that each have a one-line bug and a test suite the buggy version fails. It's a standard benchmark in program repair research, which means the number is comparable to published work instead of to test cases I made up myself. (I did start with my own test cases, and the agent passed all of them, which told me nothing except that my cases were too easy.)

A few things about how I measured it:

**pass@1.** Each program gets one shot at a fix, which is how these results get reported in papers.

**What counts as passing.** The fix has to make the program's full test suite pass, and those tests run several different inputs. So a fix that only works for one input won't slip through.

**Checking the fixes are real.** I compared some of the passing fixes against QuixBugs' reference solutions. Most matched. One was actually different from the reference but still correct, and arguably more defensive than the official answer, which was a useful reminder that "correct" doesn't mean "identical to the reference."

## Where this falls apart

These are real problems with the approach, and honestly they're the most interesting part of building this.

**The agent will cheat if you let it.** Its goal is to make the failing test pass, so if a test is just plain wrong, it'll satisfy the test by breaking the code. I tested this by writing a test that demanded `sub(5,3) == 999`. The agent added a special case to return 999 for those inputs. So I added prompt rules telling it not to hardcode values. It then rewrote the function to return 999 for everything. Different cheat, same problem. You can't prompt your way out of it, because the incentive to pass the test at any cost is still there.

**It assumes the test is right.** When a test fails, either the code is wrong or the test is wrong, and nothing in the failure tells you which. This tool assumes the test is correct and fixes the code. That's a choice, not an oversight, but it means it does the wrong thing when the test is the actual problem.

**One file at a time.** It fixes a single source file per failing test. Bugs spread across multiple files are out of scope.

**QuixBugs is easy.** These are one-line bugs in well-known algorithms, and the benchmark is old enough that models have probably seen it in training. So 39/40 is a ceiling, not proof that this handles hard or unfamiliar bugs.

## Things I'd add next

- Figure out which source file to fix from the error itself, instead of relying on naming conventions.
- Run it as a CI check that suggests fixes on a pull request.
- Try it on a harder benchmark to find where it actually breaks.
- An on/off switch so it can sit in a project and stay out of the way while you're intentionally mid-change.
