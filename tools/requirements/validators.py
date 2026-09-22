"""Validators for video requirements.

Lifted verbatim from notebook Cell 3 (REQUIREMENTS COLLECTION FORM).
The validation logic — filler-word stripping in duration, the five style
presets, the minimum-length rules — is intentional. Do not paraphrase.
"""

import re

STYLE_PRESETS = ["funny", "documentary", "serious", "graphic-heavy", "tutorial"]
FILLER_WORDS = ["like", "around", "about", "roughly", "maybe", "approximately"]


def validate_topic(topic: str) -> tuple[bool, str]:
    """Topic must be at least 5 characters after trimming."""
    topic = topic.strip()
    if len(topic) < 5:
        return False, "Topic must be at least 5 characters"
    return True, topic


def validate_style(style: str) -> tuple[bool, str]:
    """One of the 5 presets, or a custom string at least 3 chars long. Lowercased."""
    style = style.strip().lower()
    if style in STYLE_PRESETS:
        return True, style
    if len(style) >= 3:
        return True, style
    return False, "Style must be a preset or custom (min 3 characters)"


def validate_duration(duration: str) -> tuple[bool, str]:
    """Parse duration with filler-word tolerance.

    Accepts '30 seconds', '2 minutes', '2-3 minutes'.
    Strips 'like', 'around', 'about', 'roughly', 'maybe', 'approximately'.
    Returns the normalized form (e.g. '2-3 minutes').
    """
    cleaned = duration.lower()
    for filler in FILLER_WORDS:
        cleaned = cleaned.replace(filler, "").strip()

    pattern = r"(\d+(?:-\d+)?)\s*(minute|minutes|min|mins|second|seconds|sec|secs)"
    match = re.search(pattern, cleaned, re.IGNORECASE)
    if not match:
        return False, "Invalid format. Use: '3 minutes', '30 seconds', or '2-3 minutes'"

    number_part = match.group(1)
    unit_part = match.group(2).lower()

    if unit_part in ["minute", "minutes", "min", "mins"]:
        is_plural = "-" in number_part or int(number_part.split("-")[0]) > 1
        unit = "minutes" if is_plural else "minute"
    elif unit_part in ["second", "seconds", "sec", "secs"]:
        is_plural = "-" in number_part or int(number_part.split("-")[0]) > 1
        unit = "seconds" if is_plural else "second"
    else:
        return False, "Invalid time unit"

    return True, f"{number_part} {unit}"
