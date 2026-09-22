"""Scriptwriter prompt templates.

Lifted from notebook Cell 8 with one intentional deviation per user
direction (2026-05-11): `example_scripts` are injected into BOTH the
talking-points prompt AND the full-script prompt — not just the script
prompt as in the notebook. This ensures the talking points themselves
are shaped by the user's voice from the start, not retrofitted in the
script step.

These templates are used by tools/llm/router.py when an external LLM
provider is configured (Gemini, OpenAI). When provider is `claude`,
the SKILL.md describes the same instructions for Claude to follow in
conversation directly — keep the two in sync.
"""


def build_example_scripts_section(example_scripts) -> str:
    """Render the example scripts block injected into both prompts.

    Accepts either a list of {text, length, source} dicts (when the user
    provided samples in requirements.json) or the sentinel string
    "ASSET_COLLECTOR_PLACEHOLDER" (no samples provided).
    """
    if isinstance(example_scripts, list) and example_scripts:
        section = "\n\nEXAMPLE SCRIPTS TO MATCH STYLE:\n"
        for i, ex in enumerate(example_scripts, 1):
            section += f"\n--- Example {i} ---\n{ex['text']}\n"
        section += (
            "\nIMPORTANT: MATCH the tone, pacing, language, sentence "
            "structure, and energy of these examples!\n"
        )
        return section

    return "\n\n(No example scripts provided — infer voice from style + comments.)\n"


def build_variety_instruction(attempt: int) -> str:
    """Variety nudge injected on regen attempts (attempt 2+)."""
    if attempt < 2:
        return ""
    return (
        f"\n\nIMPORTANT: This is attempt {attempt}. Generate something "
        f"DIFFERENT from previous attempts. Try a fresh angle, varied "
        f"language, different hooks while keeping the same talking points."
    )


TALKING_POINTS_PROMPT_TEMPLATE = """You are a professional scriptwriter. Generate 3-5 concise talking points for a video script.

REQUIREMENTS:
- Topic: {topic}
- Style: {style}
- Duration: {duration_range} (~{total_words} words)
- Additional notes: {comments}

RESEARCH DATA:
{research_summary}
{example_scripts_section}
{variety_instruction}

INSTRUCTIONS:
1. Generate 3-5 main talking points that cover the topic comprehensively.
2. Each point should be a single clear statement (1-2 sentences max).
3. Points should build on each other logically.
4. Use the research data to ensure accuracy and relevance.
5. Consider the "{style}" style AND the voice from example scripts (if provided) when selecting points — the points themselves should already feel like they'd be made by this voice, not just neutral facts to be styled later.

OUTPUT FORMAT:
Return ONLY a JSON array of talking points, like:
["Point 1", "Point 2", "Point 3"]

No markdown, no explanations, just the JSON array.
"""


SCRIPT_PROMPT_TEMPLATE = """You are an expert video scriptwriter. Write a complete, engaging script.

REQUIREMENTS:
- Topic: {topic}
- Style: {style}
- Target length: {total_words} words ({duration_minutes:.1f} minutes)
- Additional notes: {comments}

TALKING POINTS TO COVER:
{talking_points_json}
{example_scripts_section}
{variety_instruction}

STRUCTURE:
1. HOOK ({hook_words} words, ~12 seconds)
   - Grab attention immediately.
   - Bold statement, provocative question, or surprising fact.
   - Make viewer want to keep watching.

2. BODY ({body_words} words)
   - Cover all talking points in order.
   - Match the {style} style throughout.
   - Natural flow and smooth transitions.
   - Conversational and engaging tone.

3. CALL TO ACTION ({cta_words} words, ~12 seconds)
   - Clear next step for viewer.
   - Engaging outro that reinforces main message.

STYLE GUIDELINES FOR "{style}":
- Match the tone, energy, and pacing from example scripts (if provided).
- Use similar sentence structures and vocabulary.
- Maintain consistent voice and personality throughout.
- Write as if speaking directly to camera — natural and conversational.

OUTPUT FORMAT:
Return the script in this EXACT format (no markdown, no code blocks):

[HOOK]
(Hook text here — write naturally, as if speaking)

[BODY]
(Body text here — cover all talking points)

[CTA]
(CTA text here — engaging outro)

CRITICAL: Hit the target word count of {total_words} words as closely as possible. Write naturally and engagingly.
"""
