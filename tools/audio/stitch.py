"""Join the per-line wavs into audio.wav, applying pace and pauses locally.

Pace and pauses are deterministic edits, not model settings: ffmpeg's `atempo`
changes speed without touching pitch, and silence is silence. Doing them here
means "slow" and "[pause: 800]" mean exactly the same thing on every line and
survive a single-line redo, which a re-prompted model would not guarantee.

Output matches the other audio modes' contract (`audio.wav` + metadata), so
`timestamps` and everything downstream stay mode-agnostic.
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 48000


def _atempo_chain(pace: float) -> str:
    """atempo only accepts 0.5-2.0 per filter; chain for anything outside."""
    steps, remaining = [], max(0.25, min(4.0, pace or 1.0))
    while remaining < 0.5 or remaining > 2.0:
        step = 0.5 if remaining < 0.5 else 2.0
        steps.append(step)
        remaining /= step
    steps.append(remaining)
    return ",".join(f"atempo={s:.4f}" for s in steps)


def stitch(session_dir: Path) -> dict:
    job = json.loads((session_dir / "voice_script.json").read_text(encoding="utf-8"))
    lines_dir = session_dir / "voice_build" / "lines"

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
    return {"ok": True, "output": str(out), "duration": info["duration"],
            "lines": len(labels), "warnings": info.get("warnings", [])}


def cmd_stitch(args) -> None:
    print(json.dumps(stitch(Path(args.session))))
