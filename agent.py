import os
from dotenv import load_dotenv
from google import genai
from runner import run_tests

MODEL_NAME = "gemini-3.6-flash"

load_dotenv(verbose=True)
googleapi_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=googleapi_key)

with open("prompt.txt") as f:
    instruction = f.read()


def fix_tests(project_root, source_path, test_path, attempts=3):
    file_path = os.path.join(project_root, source_path)

    code, output = run_tests(test_path, project_root)

    if code == 0:
        return True

    for attempt in range(attempts):
        with open(file_path) as f:
            code_text = f.read()

        contents = f"""{instruction}

Code =
{code_text}

Output =
{output}
"""

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
        )

        with open(file_path, "w") as f:
            f.write(response.text)

        code1, output1 = run_tests(test_path, project_root)

        if code1 == 0:
            return True
        else:
            output = output1

    return False

