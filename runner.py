import subprocess

def run_tests(path='.', cwd=None, timeout=10):
    try:
        result = subprocess.run(
            ["pytest", path], capture_output=True, text=True,
            cwd=cwd, timeout=timeout
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return 1, "Test timed out - likely infinite loop"
    except FileNotFoundError:
        return 1, ("pytest not found. Install it in the environment running "
                   "this tool: pip install pytest")
