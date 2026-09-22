"""Deterministic loudness mix — sound-design §1 (levels), applied with numbers.

Two jobs:

1. Normalise the voiceover to a target integrated loudness. A raw XTTS/self-record
   take lands wherever it lands (this session's was -24 LUFS, ~10 dB under the
   social norm), which makes everything else feel loud by comparison.

2. Set every SFX cue's gain so it sits a fixed number of LU *under* the voice.

Point 2 is the part that can't be done by eye: source SFX vary by 25 dB or more,
so a hand-picked multiplier means something different for every file. A 0.13 gain
on a -5 LUFS scratch is still louder than a -24 LUFS narrator. Gains here are
computed per file from measured loudness, so "12 LU under the voice" is literally
what you get.

Voice audio is normalised in place; the pre-mix take is preserved once as
audio.premix.wav.
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_VOICE_LUFS = -14.0   # social/streaming norm
DEFAULT_DUCK_LU = 12.0       # how far under the voice SFX sit
TRUE_PEAK = -1.5             # dBTP ceiling so the limiter has headroom


def measure_lufs(path: Path) -> float | None:
    """Integrated loudness via ffmpeg's EBU R128 meter."""
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-filter_complex", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.findall(r"I:\s*(-?\d+\.?\d*)\s*LUFS", r.stderr)
    return float(m[-1]) if m else None


def normalise_voice(wav: Path, target: float) -> tuple[float | None, float | None]:
    before = measure_lufs(wav)
    if before is None:
        return None, None
    premix = wav.with_name("audio.premix.wav")
    if not premix.exists():
        shutil.copy(wav, premix)
    tmp = wav.with_name("audio.mix.tmp.wav")
    # loudnorm also limits, so the +10dB lift can't clip the peaks.
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(premix),
         "-af", f"loudnorm=I={target}:TP={TRUE_PEAK}:LRA=11",
         "-ar", "48000", str(tmp)],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"loudnorm failed: {r.stderr[-400:]}")
    tmp.replace(wav)
    return before, measure_lufs(wav)


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalise voice + level SFX against it")
    ap.add_argument("--session", required=True)
    ap.add_argument("--voice-lufs", type=float, default=DEFAULT_VOICE_LUFS, dest="voice_lufs")
    ap.add_argument("--duck", type=float, default=DEFAULT_DUCK_LU,
                    help="LU below the voice that SFX should sit (default 12)")
    ap.add_argument("--skip-voice", action="store_true", dest="skip_voice",
                    help="only re-level the SFX; leave audio.wav alone")
    ap.add_argument("--bake", action="store_true",
                    help="write pre-levelled copies of each cue and point sfx.json at "
                         "them with gain 1.0 — required because the editor's preview "
                         "ignores per-element volume")
    args = ap.parse_args()

    session = Path(args.session)
    wav = session / "audio.wav"
    sfx_path = session / "sfx.json"
    if not wav.exists():
        print(json.dumps({"ok": False, "error": f"{wav} not found"}))
        sys.exit(1)

    out: dict = {"ok": True}

    if args.skip_voice:
        voice_lufs = measure_lufs(wav)
        out["voice"] = {"lufs": voice_lufs, "normalised": False}
    else:
        before, after = normalise_voice(wav, args.voice_lufs)
        voice_lufs = after
        out["voice"] = {"before_lufs": before, "after_lufs": after,
                        "target": args.voice_lufs, "normalised": True}
        meta_path = session / "audio_metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["loudness_lufs"] = after
            meta["file_size_mb"] = round(wav.stat().st_size / (1024 * 1024), 2)
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if voice_lufs is None:
        print(json.dumps({"ok": False, "error": "could not measure the voiceover"}))
        sys.exit(1)

    if sfx_path.exists():
        doc = json.loads(sfx_path.read_text(encoding="utf-8"))
        target = voice_lufs - args.duck
        rows = []
        for cue in doc.get("cues", []):
            # Always measure the ORIGINAL source. Once a cue has been baked its
            # `file` points at an already-attenuated copy, and re-running would
            # measure that and attenuate again, compounding on every pass.
            src = cue.get("_source") or cue.get("file", "")
            f = Path(str(src).replace("\\", "/"))
            if not f.exists():
                continue
            cue["_source"] = str(f).replace("\\", "/")
            lufs = measure_lufs(f)
            if lufs is None:
                continue
            # gain in linear amplitude: dB difference -> 10^(dB/20)
            gain = 10 ** ((target - lufs) / 20)
            gain = max(0.005, min(gain, 1.0))
            rows.append((cue.get("label", "")[:44], cue.get("gain"), round(gain, 4), lufs))

            if args.bake:
                # The editor's preview does not apply per-element volume (manual
                # edits in the UI don't change it either), so a gain in the project
                # file is inaudible. Bake the whole cue treatment into the sample —
                # trim [in:out], fade the tail, then level — so the file IS exactly
                # what should play and no editor-side interpretation is needed.
                in_pt = float(cue.get("in", 0) or 0)
                out_pt = float(cue.get("out", 0) or 0)
                slice_dur = max(out_pt - in_pt, 0.05) if out_pt > in_pt else 0.0
                fade = float(cue.get("fade_out", 0) or 0)
                baked_dir = session / "assets" / "sfx" / "mixed"
                baked_dir.mkdir(parents=True, exist_ok=True)
                tag = f"{int(round(gain * 1000)):04d}_{int(round(slice_dur * 100)):04d}"
                baked = baked_dir / f"{f.stem}_{tag}.wav"
                if not baked.exists():
                    af = [f"volume={gain:.4f}"]
                    # Hard-cutting a sound with a tail (explosion, riser) clicks;
                    # a short fade at the trim boundary smooths any truncation.
                    if slice_dur > 0 and fade > 0:
                        af.append(f"afade=t=out:st={max(slice_dur - fade, 0):.3f}:d={fade:.3f}")
                    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
                    if slice_dur > 0:
                        cmd += ["-ss", f"{in_pt:.3f}", "-t", f"{slice_dur:.3f}"]
                    cmd += ["-i", str(f), "-af", ",".join(af), "-ar", "48000", str(baked)]
                    r = subprocess.run(cmd, capture_output=True, text=True)
                    if r.returncode != 0:
                        raise RuntimeError(f"bake failed for {f.name}: {r.stderr[-300:]}")
                cue["file"] = str(baked).replace("\\", "/")
                cue["gain"] = 1.0
                # The baked file IS the trimmed slice — reset the window so render
                # plays it whole rather than trimming an already-trimmed file.
                if slice_dur > 0:
                    cue["in"] = 0.0
                    cue["out"] = round(slice_dur, 3)
                cue["_baked_gain"] = round(gain, 4)
            else:
                cue["gain"] = round(gain, 4)
            cue["_measured_lufs"] = lufs
        doc["mix"] = {"voice_lufs": voice_lufs, "sfx_target_lufs": round(target, 2),
                      "duck_lu": args.duck}
        sfx_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        out["sfx"] = {"cues": len(rows), "target_lufs": round(target, 2)}
        out["changes"] = [{"label": lbl, "was": was, "now": now, "src_lufs": lufs}
                          for lbl, was, now, lufs in rows]

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
