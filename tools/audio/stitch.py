"""Join the per-line wavs into audio.wav, applying pace and pauses locally.

Pace and pauses are deterministic edits, not model settings: ffmpeg's `atempo`
changes speed without touching pitch, and silence is silence. Doing them here
means "slow" and "[pause: 800]" mean exactly the same thing on every line and
survive a single-line redo, which a re-prompted model would not guarantee.

Output matches the other audio modes' contract (`audio.wav` + metadata), so
`timestamps` and everything downstream stay mode-agnostic.
"""

import json
import math
import subprocess
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 48000
MAX_TEMPO = 1.15   # faster than this and the clone stops sounding human
MIN_PAUSE = 0.6    # pauses shrink to no less than this share


def _atempo_chain(pace: float) -> str:
    """atempo only accepts 0.5-2.0 per filter; chain for anything outside."""
    steps, remaining = [], max(0.25, min(4.0, pace or 1.0))
    while remaining < 0.5 or remaining > 2.0:
        step = 0.5 if remaining < 0.5 else 2.0
        steps.append(step)
        remaining /= step
    steps.append(remaining)
    return ",".join(f"atempo={s:.4f}" for s in steps)


def _seconds(wav: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)],
                       capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def fit(job: dict, lines_dir: Path, target: float) -> dict:
    """Shrink pauses (to x0.6), then raise tempo (to x1.15), just enough to land on `target` seconds, and write
    the result into the job's per-line pace and pauses (SPEC.md Part 12, F10). When even both limits fall
    short, report about how many words to cut. A voiceover already at or under the target is left alone."""
    lines = job["lines"]
    speech = sum(_seconds(lines_dir / f"line_{l['id']}.wav") / (l.get("pace") or 1.0) for l in lines)
    pauses = sum(int(l.get("pause_after_ms") or 0) for l in lines) / 1000
    excess = speech + pauses - target
    out = {"target": target, "before": round(speech + pauses, 2), "tempo": 1.0, "pause_scale": 1.0, "words_to_cut": 0}
    if excess <= 0:
        return out
    scale = max(MIN_PAUSE, (pauses - excess) / pauses) if pauses else 1.0
    left = excess - pauses * (1 - scale)
    tempo = min(MAX_TEMPO, speech / (speech - left)) if left > 0 else 1.0
    left -= speech - speech / tempo
    if left > 0.05:
        words = job.get("word_count") or sum(len(l["text"].split()) for l in lines)
        out["words_to_cut"] = math.ceil(left * words / (speech / tempo))
    for l in lines:
        if tempo > 1.0:
            l["pace"] = round((l.get("pace") or 1.0) * tempo, 4)
        if l.get("pause_after_ms"):
            l["pause_after_ms"] = int(round(l["pause_after_ms"] * scale))
    out.update(tempo=round(tempo, 4), pause_scale=round(scale, 3))
    return out


def stitch(session_dir: Path, target_seconds: float | None = None) -> dict:
    job_path = session_dir / "voice_script.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    lines_dir = session_dir / "voice_build" / "lines"
    fitted = None
    if target_seconds:
        fitted = fit(job, lines_dir, float(target_seconds))
        # Kept in the job, so a later --only redo stitches at the same pace and pauses.
        job_path.write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")

    inputs, filters, labels, missing = [], [], [], []
    for idx, line in enumerate(job["lines"]):
        wav = lines_dir / f"line_{line['id']}.wav"
        if not wav.exists():
            missing.append(line["id"])
            continue
        inputs += ["-i", str(wav)]
        chain = [f"aresample={SAMPLE_RATE}", "aformat=channel_layouts=mono"]
        if abs((line.get("pace") or 1.0) - 1.0) > 0.001:
            chain.append(_atempo_chain(line["pace"]))
        pause = int(line.get("pause_after_ms") or 0)
        if pause:
            chain.append(f"apad=pad_dur={pause / 1000:.3f}")
        filters.append(f"[{len(labels)}:a]{','.join(chain)}[a{idx}]")
        labels.append(f"[a{idx}]")

    if missing:
        raise RuntimeError("no audio for lines: " + ", ".join(missing))

    graph = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    out = session_dir / "audio.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs,
                    "-filter_complex", graph, "-map", "[out]",
                    "-ar", str(SAMPLE_RATE), "-ac", "1", str(out)], check=True)

    from tools.audio.validate import validate_wav
    info = validate_wav(out)
    meta = {
        "session_id": session_dir.name,
        "audio_file": str(out).replace("\\", "/"),
        "method": "indextts2",
        "duration_seconds": info["duration"],
        "duration_minutes": round(info["duration"] / 60, 2),
        "channels": info["channels"],
        "sample_rate": info["sample_rate"],
        "file_size_mb": info["size_mb"],
        "script_word_count": job["word_count"],
        "voice_sample": job["voice_sample"],
        "takes_recorded": None,
        "line_count": job["line_count"],
        "guide_lines": [l["id"] for l in job["lines"] if l.get("guide")],
        "timestamp": datetime.now().isoformat(),
    }
    (session_dir / "audio_metadata.json").write_text(json.dumps(meta, indent=2),
                                                     encoding="utf-8")
    res = {"ok": True, "output": str(out), "duration": info["duration"],
           "lines": len(labels), "warnings": info.get("warnings", [])}
    if fitted:
        res["fit"] = fitted
        if fitted["words_to_cut"]:
            res["warnings"].append(f"tempo x{MAX_TEMPO} and pauses x{MIN_PAUSE} are not enough for "
                                   f"{fitted['target']:.0f} s: cut about {fitted['words_to_cut']} words")
    return res


def cmd_stitch(args) -> None:
    print(json.dumps(stitch(Path(args.session), getattr(args, "target_seconds", None))))
