"""Parse [HOOK] / [BODY] / [CTA] tagged scripts.

Lifted from notebook Cell 8. The strict tag format is intentional — it
gives downstream skills (audio, timestamps, brainbox) a deterministic
way to find section boundaries without re-parsing prose.
"""

import re
from typing import TypedDict


class ParsedScript(TypedDict):
    hook: str
    body: str
    cta: str
    full: str
    hook_words: int
    body_words: int
    cta_words: int
    total_words: int


def parse_script(raw: str) -> ParsedScript:
    """Extract HOOK / BODY / CTA sections from a tagged script.

    Tolerates LLM output wrapped in ```...``` code fences. If a tag is
    missing, that section is returned as an empty string.
    """
    raw = raw.strip()

    # Strip optional markdown code fences
    if raw.startswith("```"):
        parts = raw.split("```", 2)
        raw = parts[-1] if len(parts) >= 2 else raw
        if raw.startswith("\n"):
            raw = raw[1:]
    if raw.endswith("```"):
        raw = raw[: raw.rfind("```")]

    hook_match = re.search(r"\[HOOK\](.*?)\[BODY\]", raw, re.DOTALL)
    body_match = re.search(r"\[BODY\](.*?)\[CTA\]", raw, re.DOTALL)
    cta_match = re.search(r"\[CTA\](.*?)$", raw, re.DOTALL)

    hook = hook_match.group(1).strip() if hook_match else ""
    body = body_match.group(1).strip() if body_match else ""
    cta = cta_match.group(1).strip() if cta_match else ""

    full = f"{hook}\n\n{body}\n\n{cta}".strip()

    return {
        "hook": hook,
        "body": body,
        "cta": cta,
        "full": full,
        "hook_words": len(hook.split()),
        "body_words": len(body.split()),
        "cta_words": len(cta.split()),
        "total_words": len(full.split()),
    }
