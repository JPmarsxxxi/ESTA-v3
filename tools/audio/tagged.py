"""The tagged voice script — markup in, per-line synthesis jobs out.

The user approves delivery *before* anything is generated, so the contract
between Claude and the engine is a human-readable file (`script.tagged.md`)
rather than a JSON blob:

    [HOOK]
    {sarcastic, amused} If you're still trying to do retail trading bruh,
    {flat, dismissive} that stuff does *not* work [pause] it's just gambling.

    [BODY]
    {bitter, scoffing | pace: slow} It *never* actually had any real edge.
    {guide: takes/foolery.wav} this absolute... foolery.

Four kinds of markup, all optional:

- `{...}` at the start of a line — directives, `|`-separated. A bare phrase is
  the **emotion** (fed to IndexTTS2 as `emo_text`); `pace:`, `pause:` and
  `guide:` are recognised keys.
- `*word*` — stress. Rendered to the engine as CAPS, which is the only lever
  that reliably moves IndexTTS2's emphasis, and stripped for subtitles.
- `[pause]` / `[pause: 800]` — splits the line into two synthesis units with
  silence between them. Pauses are cut locally in `stitch.py` rather than
  asked of the model, because inserted silence is exact and a model's pause is
  a suggestion.
- Pace is likewise applied locally (ffmpeg `atempo`, pitch-preserving), so
  "slow" means the same thing on every line and on every engine.

`[SECTION]` lines are structure, never spoken — same rule as xtts.py.
"""

import json
import re
from pathlib import Path

SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
DIRECTIVE_RE = re.compile(r"^\s*\{([^}]*)\}\s*")
PAUSE_RE = re.compile(r"\[pause(?:\s*:\s*(\d+))?\]", re.IGNORECASE)
STRESS_RE = re.compile(r"\*([^*\n]+)\*")

# Any square bracket that isn't [pause] is visual direction, not narration —
# "[degenerate crypto bro picture]", "[Machine gun meme]" in a draft written for
# the page. IndexTTS2 will read those aloud given half a chance, so they're
# stripped from the spoken text and kept per-line as shot hints for the plan.
DIRECTION_RE = re.compile(r"\[(?!\s*pause\b)[^\]\n]*\]", re.IGNORECASE)

# Pitch-preserving tempo multipliers. Deliberately gentle: past ~±20% the
# voice starts to sound processed rather than performed.
PACE = {
    "very slow": 0.82, "slow": 0.90, "slower": 0.90,
    "normal": 1.0, "natural": 1.0,
    "fast": 1.10, "faster": 1.10, "very fast": 1.20, "rushed": 1.20,
}
DEFAULT_PAUSE_MS = 450
EMO_ALPHA = 0.65  # IndexTTS2's recommended strength for text-described emotion

# IndexTTS2 scores a free-text emotion against exactly these eight, in this
# order, and anything it can't place lands on `calm` — "sarcastic, amused" came
# back calm=1.0 in testing. `{emo: angry 0.5, disgusted 0.3}` skips the
# classifier and sets the vector directly, for when the read matters.
EMOTIONS = ["happy", "angry", "sad", "afraid", "disgusted", "melancholic",
            "surprised", "calm"]


def _default_directives() -> dict:
    """The per-line delivery defaults.

    One factory, two callers: a `{...}` line parses into this shape, an untagged
    line takes it as-is. These were duplicated by hand once and drifted the
    moment `emo_vector` joined — every untagged line raised KeyError, which a
    fully-tagged test script can't catch.
    """
    return {"emotion": None, "emo_vector": None, "pace": 1.0,
            "pace_label": None, "pause_after_ms": 0, "guide": None, "voice": None}


def _parse_directives(blob: str) -> dict:
    """`{bitter, scoffing | pace: slow | pause: 700}` -> dict."""
    out = _default_directives()
    for part in blob.split("|"):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition(":")
        key, value = key.strip().lower(), value.strip()
        if sep and key == "pace":
            out["pace_label"] = value.lower()
            out["pace"] = PACE.get(value.lower(), _as_float(value, 1.0))
        elif sep and key == "pause":
            out["pause_after_ms"] = int(_as_float(value, DEFAULT_PAUSE_MS))
        elif sep and key == "guide":
            out["guide"] = value
        elif sep and key == "emo":
            out["emo_vector"] = _parse_emo_vector(value)
        elif sep and key == "voice":
            # A different speaker for this line only — a quoted passage, a second
            # character. IndexTTS2 takes the speaker prompt per inference call,
            # so this costs nothing but staging the extra sample.
            out["voice"] = value
        else:
            # Anything else is the emotion description, e.g. "bitter, scoffing".
            out["emotion"] = part if not out["emotion"] else out["emotion"] + ", " + part
    return out


def _parse_emo_vector(value: str) -> list[float]:
    """`angry 0.5, disgusted 0.3` -> the 8-slot vector IndexTTS2 wants."""
    vector = [0.0] * len(EMOTIONS)
    for term in value.split(","):
        bits = term.strip().split()
        if not bits:
            continue
        name = bits[0].strip().lower()
        if name in EMOTIONS:
            vector[EMOTIONS.index(name)] = _as_float(bits[1], 0.5) if len(bits) > 1 else 0.5
    return vector


def _as_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except ValueError:
        return fallback


def _squeeze(text: str) -> str:
    """Collapse the double spaces that removing a marker leaves behind."""
    return re.sub(r"\s{2,}", " ", text).strip()


def extract_directions(text: str) -> list[str]:
    """The bracketed visual notes on a line, brackets stripped."""
    return [d.strip("[]").strip() for d in DIRECTION_RE.findall(text)]


def to_model_text(text: str) -> str:
    """Stress markers -> CAPS (what IndexTTS2 responds to); direction dropped."""
    spoken = DIRECTION_RE.sub(" ", text)
    return _squeeze(STRESS_RE.sub(lambda m: m.group(1).upper(), spoken))


def to_plain_text(text: str) -> str:
    """Strip every marker — what the line *says*, for script.md and subtitles."""
    spoken = DIRECTION_RE.sub(" ", PAUSE_RE.sub(" ", text))
    return _squeeze(STRESS_RE.sub(r"\1", spoken))


def parse_tagged(markup: str) -> list[dict]:
    """Tagged script -> ordered synthesis units.

    One unit per line, or per `[pause]`-separated fragment within a line. The
    directives on a line apply to every fragment it produces; only the last
    fragment keeps the line's own trailing pause.
    """
    units: list[dict] = []
    section = ""
    for raw in markup.splitlines():
        if not raw.strip():
            continue
        if m := SECTION_RE.match(raw):
            section = m.group(1).strip().upper()
            continue

        body = raw
        directives = _default_directives()
        if m := DIRECTIVE_RE.match(raw):
            directives = _parse_directives(m.group(1))
            body = raw[m.end():]

        fragments = PAUSE_RE.split(body)
        # re.split with one capture group yields [text, pause_ms|None, text, ...]
        pieces = [(fragments[i], fragments[i + 1] if i + 1 < len(fragments) else None)
                  for i in range(0, len(fragments), 2)]
        for idx, (frag, pause_ms) in enumerate(pieces):
            if not frag.strip():
                continue
            last = idx == len(pieces) - 1
            units.append({
                "id": f"L{len(units) + 1:02d}",
                "section": section,
                "text": to_plain_text(frag),
                "model_text": to_model_text(frag),
                "directions": extract_directions(frag),
                "emotion": directives["emotion"],
                "emo_vector": directives["emo_vector"],
                "emo_alpha": EMO_ALPHA if directives["emotion"] else None,
                "pace": directives["pace"],
                "pace_label": directives["pace_label"],
                "pause_after_ms": (directives["pause_after_ms"] if last
                                   else int(pause_ms or DEFAULT_PAUSE_MS)),
                "guide": directives["guide"],
                "voice": directives["voice"],
                "engine": "seedvc" if directives["guide"] else "indextts2",
            })
    return units


def build_voice_script(session_dir: Path, voice_sample: str) -> dict:
    """Parse `script.tagged.md` into the `voice_script.json` job list."""
    markup = (session_dir / "script.tagged.md").read_text(encoding="utf-8")
    units = parse_tagged(markup)
    return {
        "voice_sample": voice_sample,
        "line_count": len(units),
        "word_count": sum(len(u["text"].split()) for u in units),
        "lines": units,
    }


def cmd_tag_check(args) -> None:
    """Parse + report without generating — the pre-approval preview."""
    session_dir = Path(args.session)
    data = build_voice_script(session_dir, args.sample or "")
    missing = [u["id"] for u in data["lines"]
               if u["guide"] and not (session_dir / u["guide"]).exists()
               and not Path(u["guide"]).exists()]
    (session_dir / "voice_script.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": not missing,
        "lines": data["line_count"],
        "words": data["word_count"],
        "tagged": sum(1 for u in data["lines"] if u["emotion"] or u["emo_vector"]),
        "guides": sum(1 for u in data["lines"] if u["guide"]),
        "directions": sum(len(u["directions"]) for u in data["lines"]),
        "alt_voices": sorted({u["voice"] for u in data["lines"] if u["voice"]}),
        "missing_guides": missing,
        "estimated_seconds": round(data["word_count"] / 150 * 60, 1),
    }))
