"""Audio assemble — Phase 5 of notes/smart-pipeline-and-found-audio.md.

Stitches a found-audio arrangement (arrangement.json, from the scriptwriter
arranger) into a single audio.wav, honoring the same output contract as the XTTS
and self-record modes — so timestamps + everything downstream are mode-agnostic.

Layering model:
- `spine` clips (the narration) play sequentially: each starts where the
  previous ended, unless it carries an explicit `start`.
- `bed` clips (music / ambience underlay) loop under the whole timeline at their
  `gain_db` (usually negative), starting at `start` (default 0).

Build: ffmpeg filter_complex — per clip atrim -> resample/format -> volume ->
adelay to its timeline position; bed clips use -stream_loop -1 then atrim to the
total duration. All streams amix (normalize=0 = sum, not average) + a safety
limiter.

    conda run --no-capture-output -n esta python tools/audio/run.py assemble \
      --session sessions/<id>
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SR = 48000
CH = 2


def _resolve(clip: dict, pool_by_id: dict) -> str:
    f = clip.get("file") or pool_by_id.get(clip.get("pool_id", ""), {}).get("file", "")
    return f


def _fmt_chain() -> str:
    return f"aresample={SR},aformat=sample_fmts=fltp:channel_layouts=stereo"


def assemble(session_dir: Path) -> dict:
    arr_path = session_dir / "arrangement.json"
    pool_path = session_dir / "audio_pool.json"
    if not arr_path.exists():
        raise FileNotFoundError("arrangement.json missing — run the scriptwriter arranger first")
    if not pool_path.exists():
        raise FileNotFoundError("audio_pool.json missing — run audio found-fetch first")

    arr = json.loads(arr_path.read_text(encoding="utf-8"))
    pool = json.loads(pool_path.read_text(encoding="utf-8"))
    pool_by_id = {f"{c.get('source')}:{c.get('id')}": c for c in pool.get("clips", [])}

    raw = arr.get("clips", [])
    spine = [c for c in raw if c.get("layer", "spine") != "bed"]
    beds = [c for c in raw if c.get("layer") == "bed"]
    spine.sort(key=lambda c: c.get("order", 1e9))

    # Compute sequential timeline starts for the spine.
    cursor = 0.0
    placed: list[dict] = []
    for c in spine:
        dur = float(c.get("out_point", 0)) - float(c.get("in_point", 0))
        if dur <= 0:
            continue
        start = float(c["start"]) if c.get("start") is not None else cursor
        placed.append({**c, "_start": start, "_dur": dur})
        cursor = max(cursor, start + dur)
    total = round(cursor, 3)
    if total <= 0:
        raise ValueError("arrangement has no playable spine clips")

    inputs: list[str] = []       # ffmpeg -i args (with per-input options)
    filters: list[str] = []
    labels: list[str] = []
    idx = 0

    def add_input(path: str, loop: bool) -> int:
        nonlocal idx
        if loop:
            inputs.extend(["-stream_loop", "-1"])
        inputs.extend(["-i", path])
        i = idx
        idx += 1
        return i

    # spine
    for k, c in enumerate(placed):
        f = _resolve(c, pool_by_id)
        if not f or not Path(f).exists():
            continue
        i = add_input(f, loop=False)
        ip, op = float(c.get("in_point", 0)), float(c.get("out_point", 0))
        gain = float(c.get("gain_db", 0))
        ms = int(round(c["_start"] * 1000))
        filters.append(
            f"[{i}:a]atrim={ip}:{op},asetpts=PTS-STARTPTS,{_fmt_chain()},"
            f"volume={gain}dB,adelay={ms}:all=1[s{k}]"
        )
        labels.append(f"[s{k}]")

    # beds — loop to total, then place
    for k, c in enumerate(beds):
        f = _resolve(c, pool_by_id)
        if not f or not Path(f).exists():
            continue
        i = add_input(f, loop=True)
        gain = float(c.get("gain_db", -14))
        start = float(c.get("start", 0) or 0)
        ms = int(round(start * 1000))
        ip = float(c.get("in_point", 0) or 0)
        # trim from in_point, cap to (total - start) so the bed ends with the piece
        bed_len = round(max(total - start, 0.1), 3)
        filters.append(
            f"[{i}:a]{_fmt_chain()},atrim={ip}:{ip + bed_len},asetpts=PTS-STARTPTS,"
            f"volume={gain}dB,adelay={ms}:all=1[b{k}]"
        )
        labels.append(f"[b{k}]")

    if not labels:
        raise ValueError("no arrangement clips resolved to downloaded files")

    out_path = session_dir / "audio.wav"
    if len(labels) == 1:
        graph = filters[0].replace(labels[0], "[mix]") + ";[mix]alimiter=limit=0.95[out]"
    else:
        graph = ";".join(filters) + ";" + "".join(labels) + \
            f"amix=inputs={len(labels)}:duration=longest:normalize=0,alimiter=limit=0.95[out]"

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", graph,
           "-map", "[out]", "-ar", str(SR), "-ac", str(CH), str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out_path.exists():
        tail = "\n".join((proc.stderr or "").splitlines()[-8:])
        raise RuntimeError(f"ffmpeg failed:\n{tail}")

    # metadata via the shared validator
    from tools.audio.validate import validate_wav
    info = validate_wav(out_path)
    meta = {
        "session_id": session_dir.name,
        "audio_file": str(out_path),
        "method": "found_assembled",
        "duration_seconds": round(info["duration"], 3),
        "duration_minutes": round(info["duration"] / 60.0, 3),
        "channels": info["channels"],
        "sample_rate": info["sample_rate"],
        "file_size_mb": round(info["size_mb"], 3),
        "script_word_count": 0,
        "voice_sample": None,
        "takes_recorded": None,
        "xtts_speed": None, "xtts_gpu": None,
        "xtts_load_time_seconds": None, "xtts_gen_time_seconds": None,
        "source_clips": len(labels),
        "timestamp": datetime.now().isoformat(),
    }
    (session_dir / "audio_metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "output": str(out_path), "duration_seconds": meta["duration_seconds"],
            "source_clips": meta["source_clips"], "channels": meta["channels"],
            "sample_rate": meta["sample_rate"]}


def cmd_assemble(args) -> None:
    print(json.dumps(assemble(Path(args.session))))
