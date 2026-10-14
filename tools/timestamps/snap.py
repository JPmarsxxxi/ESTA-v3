"""Snap whisper's words in timestamps.json to the script's own words, keeping whisper's timing (SPEC.md Part 12, F8).

Whisper writes what it hears ("seal test", "back test", "0 .53"); the subtitles and the idea alignment need the
script's words. difflib aligns the two token streams: matched runs keep their times, a replaced run spreads the
script words over the run's span by character length, extra whisper words (fillers) are dropped, and missing
script words are squeezed into the gap they fall in. The untouched transcript is kept as
timestamps.original-asr.json.

Only a synthesised voiceover is snapped (voice_script.json, or an XTTS read of script.md): the voice says the
script and nothing else. A self-recorded take may ad-lib, and its words stay as heard. A transcript that agrees
with the script on under half its letters is left alone too: the script is not what was read.
"""

import difflib
import json
import re
from pathlib import Path

SECTION = re.compile(r"^\s*\[[^\]]+\]\s*$")
DIRECTION = re.compile(r"\[[^\]\n]*\]|\{[^}\n]*\}")
MIN_AGREEMENT = 0.5


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def script_tokens(session: Path) -> list[str] | None:
    vs = session / "voice_script.json"
    if vs.exists():
        lines = [line["text"] for line in json.loads(vs.read_text(encoding="utf-8")).get("lines", [])]
    else:
        meta = session / "audio_metadata.json"
        method = json.loads(meta.read_text(encoding="utf-8")).get("method", "") if meta.exists() else ""
        if "xtts" not in str(method).lower() or not (session / "script.md").exists():
            return None
        lines = [line for line in (session / "script.md").read_text(encoding="utf-8").splitlines() if not SECTION.match(line)]
    text = DIRECTION.sub(" ", " ".join(lines)).replace("*", "")
    return [w for w in text.split() if norm(w)]


def spread(tokens: list[str], a: float, b: float, prob: float = 0.5) -> list[dict]:
    total = sum(max(1, len(t)) for t in tokens)
    out, t = [], a
    for tok in tokens:
        d = (b - a) * max(1, len(tok)) / total
        out.append({"word": tok, "start": round(t, 3), "end": round(t + d, 3), "duration": round(d, 3), "probability": prob})
        t += d
    return out


def snap_words(segments: list[dict], script: list[str]) -> tuple[list[dict], float]:
    """(segments with the script's words, how closely whisper's letters agree with the script's, 0-1)."""
    asr = [(i, w) for i, s in enumerate(segments) for w in s.get("words", [])]
    sa, sb = [norm(w["word"]) for _, w in asr], [norm(w) for w in script]
    matcher = difflib.SequenceMatcher(None, sa, sb, autojunk=False)
    out: list[tuple[int, dict]] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                seg, w = asr[i1 + k]
                out.append((seg, {**w, "word": script[j1 + k]}))
        elif op == "replace":
            seg = asr[i1][0]
            out += [(seg, w) for w in spread(script[j1:j2], asr[i1][1]["start"], asr[i2 - 1][1]["end"])]
        elif op == "insert":
            prev = out[-1][1]["end"] if out else 0.0
            nxt = asr[i1][1]["start"] if i1 < len(asr) else prev + 0.3 * (j2 - j1)
            seg = out[-1][0] if out else 0
            need = 0.08 * (j2 - j1)
            a = prev if nxt - prev >= need else max(0.0, prev - need)
            out += [(seg, w) for w in spread(script[j1:j2], a, max(nxt, a + need))]
        # "delete": a word whisper heard that the script doesn't have (a filler) is dropped
    # Compared as letters, so "back test" against "backtest" counts as agreeing.
    agreement = difflib.SequenceMatcher(None, "".join(sa), "".join(sb), autojunk=False).ratio()
    snapped = []
    for i, s in enumerate(segments):
        words = [w for k, w in out if k == i]
        if words:
            snapped.append({**s, "words": words, "text": " ".join(w["word"] for w in words)})
    return snapped, agreement


def snap(session: Path) -> dict:
    session = Path(session)
    ts_path = session / "timestamps.json"
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    if (ts.get("metadata") or {}).get("snapped_to_script"):
        return {"ok": True, "snapped": False, "why": "already snapped"}
    script = script_tokens(session)
    if not script:
        return {"ok": True, "snapped": False, "why": "no synthesised script to snap to"}
    segments, agreement = snap_words(ts.get("segments", []), script)
    if agreement < MIN_AGREEMENT:
        return {"ok": True, "snapped": False, "why": f"transcript agrees with the script on only {agreement:.0%}"}
    # Written on every snap: an unsnapped timestamps.json is always a fresh transcript.
    (session / "timestamps.original-asr.json").write_text(json.dumps(ts, indent=2, ensure_ascii=False), encoding="utf-8")
    heard = sum(len(s.get("words", [])) for s in ts.get("segments", []))
    ts["segments"] = segments
    ts["full_text"] = " ".join(s["text"] for s in segments)
    ts["num_segments"] = len(segments)
    ts["num_words"] = sum(len(s["words"]) for s in segments)
    ts.setdefault("metadata", {})["snapped_to_script"] = True
    ts_path.write_text(json.dumps(ts, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "snapped": True, "asr_words": heard, "script_words": ts["num_words"],
            "agreement": round(agreement, 3)}
