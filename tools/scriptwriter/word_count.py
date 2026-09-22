"""Word count calculation for scripts.

Lifted verbatim from notebook Cell 8 — speaking rate 150 wpm, with
Hook ~12s and CTA ~12s targets, so Body = total - 60 words. These
constants are intentional. Downstream skills (audio, timestamps)
assume this exact math.
"""

import re


SPEAKING_RATE_WPM = 150
HOOK_WORDS = 30  # ~12 seconds at 150 wpm
CTA_WORDS = 30   # ~12 seconds at 150 wpm


def calculate_target_word_count(duration_range: str) -> dict:
    """Parse a duration string (e.g. '2-3 minutes', '30 seconds') and
    return the per-section word count targets.

    Returns a dict with keys: total, hook, body, cta, duration_minutes.
    """
    numbers = re.findall(r"\d+", duration_range)
    unit = "minutes" if "min" in duration_range.lower() else "seconds"

    if len(numbers) == 2:
        min_val, max_val = int(numbers[0]), int(numbers[1])
        avg_duration = (min_val + max_val) / 2
    else:
        avg_duration = int(numbers[0])

    if unit == "seconds":
        avg_duration = avg_duration / 60

    target_words = int(avg_duration * SPEAKING_RATE_WPM)
    body_words = target_words - HOOK_WORDS - CTA_WORDS

    return {
        "total": target_words,
        "hook": HOOK_WORDS,
        "body": body_words,
        "cta": CTA_WORDS,
        "duration_minutes": avg_duration,
    }
