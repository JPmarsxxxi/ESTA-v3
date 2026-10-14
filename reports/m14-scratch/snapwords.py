"""Snap whisper's words in timestamps.json to the script's own words, keeping whisper's timing.

Whisper writes what it hears ("seal test", "back test", "0 .53", "111"); the subtitles and the idea alignment need
the script's words. difflib aligns the two token streams; matched runs keep their times, a replaced run spreads the
script words over the run's span by character length, extra whisper words (fillers) are dropped and missing script
words are squeezed into the gap they fall in. Keeps timestamps.original-asr.json.

    python D:/esta-perf/m14t/snapwords.py <session-id>
"""
import difflib
import json
import re
import sys
from pathlib import Path

S = Path("C:/Users/User/ESTA-v3/sessions") / sys.argv[1]


def norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def spread(tokens, a, b, prob=0.5):
    total = sum(max(1, len(t)) for t in tokens)
    out, t = [], a
    for tok in tokens:
        d = (b - a) * max(1, len(tok)) / total
        out.append({"word": tok, "start": round(t, 3), "end": round(t + d, 3), "duration": round(d, 3), "probability": prob})
        t += d
    return out


def main():
    ts = json.loads((S / "timestamps.json").read_text(encoding="utf-8"))
    bak = S / "timestamps.original-asr.json"
    if not bak.exists():
        bak.write_text(json.dumps(ts, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = json.loads((S / "voice_script.json").read_text(encoding="utf-8"))["lines"]
    script = [w for l in lines for w in re.sub(r"[*]", "", l["text"]).split() if norm(w)]
    segs = ts["segments"]
    asr = [(i, w) for i, s in enumerate(segs) for w in s["words"]]
    sa, sb = [norm(w["word"]) for _, w in asr], [norm(w) for w in script]
    out = []  # (segment index, word)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                seg, w = asr[i1 + k]
                out.append((seg, {**w, "word": script[j1 + k]}))
        elif op == "replace":
            seg = asr[i1][0]
            a, b = asr[i1][1]["start"], asr[i2 - 1][1]["end"]
            out += [(seg, w) for w in spread(script[j1:j2], a, b)]
        elif op == "insert":
            prev = out[-1][1]["end"] if out else 0.0
            nxt = asr[i1][1]["start"] if i1 < len(asr) else prev + 0.3 * (j2 - j1)
            seg = out[-1][0] if out else 0
            a = prev if nxt - prev >= 0.08 * (j2 - j1) else max(0.0, prev - 0.08 * (j2 - j1))
            out += [(seg, w) for w in spread(script[j1:j2], a, max(nxt, a + 0.08 * (j2 - j1)))]
        # "delete": a word whisper heard that the script doesn't have (a filler) is dropped
    for i, s in enumerate(segs):
        s["words"] = [w for k, w in out if k == i]
        s["text"] = " ".join(w["word"] for w in s["words"])
    ts["segments"] = [s for s in segs if s["words"]]
    ts["full_text"] = " ".join(s["text"] for s in ts["segments"])
    ts["num_words"] = len(out)
    ts.setdefault("metadata", {})["snapped_to_script"] = True
    (S / "timestamps.json").write_text(json.dumps(ts, indent=1, ensure_ascii=False), encoding="utf-8")
    changed = sum(1 for (_, w) in out if True) - sum(1 for op in [] if op)
    print(f"{S.name}: {len(asr)} asr words -> {len(out)} script words ({len(script)} in script)")


main()
