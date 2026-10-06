"""Mapped-plan skeleton: slots.json, with slots over SPLIT_OVER seconds split near even pieces of ~PIECE s,
preferring sentence ends within the middle half of each piece's window. Each piece keeps the slot's ref and an
equal share of its target (plan skill, mapped mode). Writes skeleton.json and prints it compactly."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.match.slots import boundaries, load_words  # noqa: E402

S = Path(__file__).parent
SPLIT_OVER, PIECE = 6.0, 3.5

slots = json.loads((S / "slots.json").read_text(encoding="utf-8"))
refs = slots["refs"]
words = load_words(json.loads((S / "timestamps.json").read_text(encoding="utf-8")))
cuts = boundaries(words)   # cuts[i] is the boundary between words[i] and words[i+1]


def text(a, b):
    return " ".join(w["word"] for w in words if a - 1e-6 <= (w["start"] + w["end"]) / 2 < b)


shots = []
for sl in slots["slots"]:
    a, b = sl["start"], sl["end"]
    dur = b - a
    n = max(1, round(dur / PIECE)) if dur > SPLIT_OVER else 1
    points = [a]
    for k in range(1, n):
        ideal = a + dur * k / n
        lo, hi = ideal - dur / n / 4, ideal + dur / n / 4
        inside = [(i, c) for i, c in enumerate(cuts) if points[-1] + 0.5 < c < b - 0.5]
        if not inside:
            break
        sentence = [(i, c) for i, c in inside if lo <= c <= hi and words[i]["word"].rstrip()[-1:] in ".?!,"]
        i, c = min(sentence or inside, key=lambda ic: abs(ic[1] - ideal))
        points.append(round(c, 3))
    points.append(b)
    pieces = len(points) - 1
    for k in range(pieces):
        sid = f"{sl['slot']}" if pieces == 1 else f"{sl['slot']}.{k + 1}"
        shots.append({"id": sid, "slot": sl["slot"], "start": points[k], "end": points[k + 1],
                      "words": text(points[k], points[k + 1]), "ref_shot": sl["ref_shot"],
                      "target": round(sl["target_dur"] / pieces, 3), "alts": sl["alts"]})

(S / "skeleton.json").write_text(json.dumps(shots, indent=1, ensure_ascii=False), encoding="utf-8")
lo, hi = (int(x) for x in (sys.argv[1:3] if len(sys.argv) > 2 else (1, 10 ** 6)))
for i, s in enumerate(shots, 1):
    if not lo <= s["slot"] <= hi:
        continue
    r = refs[s["ref_shot"]]
    flags = ("T" if r.get("text_extra") else "") + ("O" if r.get("overlay_extra") else "")
    print(f"{s['id']}|{s['end'] - s['start']:.1f}|{r['kind'][0]}/{r['content'][:6]}|{flags}|{s['words']}|| {r['description'][:60]}")
if len(sys.argv) <= 2:
    print(len(shots), "shots")
