"""UserPromptSubmit hook: warns when colab-proxy-mcp appears disconnected.

Reads JSON from stdin (user_prompt field), only acts when the prompt is
colab/style-analysis related, checks if uvx (the colab-mcp process) is
running, and outputs a systemMessage warning if not.
"""
import json
import subprocess
import sys


COLAB_KEYWORDS = ["style anal", "style-anal", "gemma", "colab", "ollama"]


def main() -> None:
    try:
        data = json.load(sys.stdin)
        prompt = data.get("user_prompt", "").lower()
    except Exception:
        return

    if not any(k in prompt for k in COLAB_KEYWORDS):
        return

    try:
        result = subprocess.run(
            ["tasklist"],
            capture_output=True, text=True, timeout=5,
        )
        if "uvx" in result.stdout.lower():
            return
    except Exception:
        return

    print(json.dumps({
        "systemMessage": (
            "WARNING: colab-proxy-mcp is disconnected - "
            "run /mcp to restart it before invoking style-analysis."
        )
    }))


if __name__ == "__main__":
    main()
