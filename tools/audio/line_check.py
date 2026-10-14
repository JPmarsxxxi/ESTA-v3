"""Catch TTS lines that say something other than the script (SPEC.md Part 12, F9).

IndexTTS2 sometimes drops or flips a word, and a flipped negation ("can't" read as "can") reverses the line's
meaning without sounding wrong. After an expressive voiceover, each line wav is transcribed with faster-whisper
(medium, CPU) and compared with its script text. A line is flagged when its word error rate is over 0.2, or when
the number of negations differs. Flagged lines are redone with `expressive --only <ids>`.

    conda run -n esta python tools/audio/run.py line-check --session sessions/<id> [--only L04,L07]

Writes voice_check.json: {"flagged": [ids], "lines": [{id, text, heard, wer, negation, flag}]}.
"""

import json
import re
from pathlib import Path

WER_MAX = 0.2
NEGATIONS = {"not", "no", "never", "nothing", "none", "nobody", "nowhere", "neither", "nor", "cannot",
             # the same contractions when a transcript drops the apostrophe
             "cant", "dont", "wont", "isnt", "arent", "wasnt", "werent", "doesnt", "didnt", "shouldnt", "wouldnt",
             "couldnt", "havent", "hasnt", "hadnt", "aint", "mustnt", "neednt"}


def tokens(text: str) -> list[str]:
    text = re.sub(r"\[[^\]]*\]|\{[^}]*\}|\*", " ", text.lower().replace("’", "'"))
    return [w for w in (re.sub(r"[^a-z0-9']", "", t).strip("'") for t in text.split()) if w]


def negations(words: list[str]) -> int:
    return sum(1 for w in words if w in NEGATIONS or w.endswith("n't"))


def wer(ref: list[str], hyp: list[str]) -> float:
    """Word error rate: edits to turn ref into hyp, over the length of ref. Apostrophes are ignored, so a
    transcriber's "dont" matches "don't"; a negation flip is caught separately."""
    ref = [w.replace("'", "") for w in ref]
    hyp = [w.replace("'", "") for w in hyp]
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def compare(text: str, heard: str) -> dict:
    ref, hyp = tokens(text), tokens(heard)
    w = round(wer(ref, hyp), 3)
    neg = negations(ref) != negations(hyp)
    why = [f"WER {w:.2f}"] if w > WER_MAX else []
    if neg:
        why.append(f"negation: script has {negations(ref)}, heard {negations(hyp)}")
    return {"wer": w, "negation": neg, "flag": bool(why), "why": "; ".join(why)}


def check(session: Path, only: list[str] | None = None, model_size: str = "medium", transcribe=None) -> dict:
    session = Path(session)
    job = json.loads((session / "voice_script.json").read_text(encoding="utf-8"))
    lines_dir = session / "voice_build" / "lines"
    if transcribe is None:
        from tools.audio.analyze_pool import _load_model
        model = _load_model(model_size)

        def transcribe(path: Path) -> str:
            segs, _ = model.transcribe(str(path), language="en", beam_size=5)
            return " ".join(s.text.strip() for s in segs)

    out_path = session / "voice_check.json"
    prev = {r["id"]: r for r in json.loads(out_path.read_text(encoding="utf-8")).get("lines", [])} if out_path.exists() else {}
    rows = dict(prev)
    for line in job["lines"]:
        if only and line["id"] not in only:
            continue
        wav = lines_dir / f"line_{line['id']}.wav"
        if not wav.exists():
            continue
        heard = transcribe(wav)
        rows[line["id"]] = {"id": line["id"], "text": line["text"], "heard": heard, **compare(line["text"], heard)}
    order = [line["id"] for line in job["lines"]]
    lines = [rows[i] for i in order if i in rows]
    out = {"flagged": [r["id"] for r in lines if r["flag"]], "lines": lines}
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def cmd_line_check(args) -> None:
    only = [x.strip() for x in args.only.split(",")] if getattr(args, "only", None) else None
    out = check(Path(args.session), only, args.model)
    print(json.dumps({"ok": True, "flagged": out["flagged"],
                      "why": {r["id"]: r["why"] for r in out["lines"] if r["flag"]}}))
