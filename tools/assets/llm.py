"""Claude-via-CLI helper for asset-picking decisions.

Calls `claude -p <prompt> --output-format json` as a subprocess, which uses
the user's existing Claude Code subscription auth — no API key needed.

Uses haiku for speed/cost on text calls. Vision calls (frame validation) save
frames to temp files and pass them via the @ attachment syntax.
"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_HAIKU  = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _claude_bin() -> str:
    """Return path to the claude executable, using CLAUDE_CODE_EXECPATH if set.

    On Windows, `claude` resolves to a .ps1 script that subprocess can't exec.
    Fall back to claude.cmd (npm shim) or scan common install paths for claude.exe.
    """
    explicit = os.environ.get("CLAUDE_CODE_EXECPATH")
    if explicit:
        return explicit

    import shutil
    import sys

    # On Windows, prefer claude.cmd (the npm shim) over the bare name
    if sys.platform == "win32":
        # Try to find claude.exe in npm node_modules (standard install location)
        npm_exe = os.path.join(
            os.environ.get("APPDATA", ""),
            "npm", "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe",
        )
        if os.path.isfile(npm_exe):
            return npm_exe
        # Fall back to claude.cmd (also runnable by subprocess on Windows)
        cmd_shim = shutil.which("claude.cmd")
        if cmd_shim:
            return cmd_shim

    return shutil.which("claude") or "claude"


def _call(prompt: str, model: str = _HAIKU, timeout: int = 30) -> str:
    """Run `claude -p <prompt>` and return the result text."""
    cmd = [_claude_bin(), "-p", prompt, "--output-format", "json", "--model", model]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=os.environ,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300] or r.stdout[:300])
    data = json.loads(r.stdout)
    return data.get("result", "")


def _call_with_images(prompt: str, image_paths: list[str], model: str = _HAIKU, timeout: int = 45) -> str:
    """Run `claude -p "<prompt> @img1 @img2 ..."` for vision calls."""
    from pathlib import Path as _Path
    # Use forward-slash paths so Claude CLI's @ parser handles them correctly on Windows
    fwd_paths = [_Path(p).as_posix() for p in image_paths]
    attachments = " ".join(f"@{p}" for p in fwd_paths)
    full_prompt = f"{prompt} {attachments}"
    cmd = [_claude_bin(), "-p", full_prompt, "--output-format", "json", "--model", model]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=os.environ,
                       stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300] or r.stdout[:300])
    data = json.loads(r.stdout)
    return data.get("result", "")


def _parse_json(text: str) -> Any:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    try:
        return json.loads(text.strip())
    except Exception:
        return None


def pick_best_videos(entries: list[dict], query: str, n: int = 3) -> list[int]:
    """Return indices of the n best entries for finding this specific moment."""
    video_list = [
        {
            "index": i,
            "title": e.get("title", ""),
            "channel": e.get("channel", ""),
            "duration": e.get("duration", 0),
            "views": e.get("view_count", 0) or 0,
        }
        for i, e in enumerate(entries)
    ]
    prompt = (
        f'Select the {n} best YouTube videos for finding this exact moment: "{query}"\n\n'
        f"VIDEOS:\n{json.dumps(video_list, indent=2)}\n\n"
        f"Prefer: title specifically about this moment, credible channel, shorter duration.\n"
        f'Reply with JSON only, no explanation: {{"picks": [{{"index": 0}}, ...]}}'
    )
    try:
        result = _parse_json(_call(prompt))
        if result and result.get("picks"):
            return [p["index"] for p in result["picks"] if "index" in p][:n]
    except Exception:
        pass
    # Fallback: prefer shorter dedicated clips over long compilations
    return sorted(range(len(entries)), key=lambda i: entries[i].get("duration", 9999))[:n]


def find_moment_in_transcript(
    transcript_lines: list[str], query: str, shot_dur: float
) -> list[dict]:
    """Return [{start, end, confidence, reason}] from a formatted transcript.

    transcript_lines: list of "[Xs] text" strings.
    """
    target_dur = max(shot_dur * 1.5, 5.0)
    transcript_text = "\n".join(transcript_lines)
    if len(transcript_text) > 12000:
        transcript_text = transcript_text[:12000] + "\n...(truncated)"

    prompt = (
        f'Find the exact moment "{query}" in this video transcript.\n\n'
        f"TARGET CLIP DURATION: approximately {shot_dur:.1f}s (up to {target_dur:.1f}s)\n"
        f"Return up to 2 candidate moments with precise timestamps.\n\n"
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f'Reply with JSON only: {{"found": true, "segments": [{{"start": 0.0, "end": {target_dur:.1f}, "confidence": 80, "reason": "brief"}}]}}'
    )
    try:
        result = _parse_json(_call(prompt))
        if result and result.get("segments"):
            return result["segments"]
    except Exception:
        pass
    return []


def find_best_frame_at_timestamps(
    frame_paths: list[str], timestamps: list[float], query: str, shot_desc: str, round_n: int = 1,
    instance_markers: dict | None = None,
) -> dict | None:
    """Ask Claude Vision which of N sampled frames is closest to the target moment.

    Used by the visual binary search in _visual_moment_finder.
    Returns {best_index, confidence, reasoning} or None on failure.
    """
    ts_str = ", ".join(f"frame {i}: {t:.1f}s" for i, t in enumerate(timestamps))
    instance_block = _format_instance_block(instance_markers)
    prompt = (
        f"Round {round_n} of visual search. These {len(frame_paths)} frames are sampled from a video.\n"
        f"Timestamps — {ts_str}\n\n"
        f'TARGET (primary criterion — match against this):\n'
        f'  "{shot_desc[:400]}"\n\n'
        f'Search query for context only: "{query}"\n'
        f'{instance_block}\n'
        f"Which frame index (0–{len(frame_paths)-1}) shows content CLOSEST to the TARGET?\n"
        f"Match on the specific physical action, body positions, composition, AND subjects in TARGET.\n"
        f"Topical match alone (same teams / same sport / same venue / same general topic) is NOT enough.\n"
        f"If instance_markers are present and the frame appears to contradict any of them, that frame is NOT a match — pick something else (or signal low confidence).\n"
        f'JSON only: {{"best_index": 0, "confidence": 0-100, "reasoning": "what you see and why it matches TARGET"}}'
    )
    try:
        result = _parse_json(_call_with_images(prompt, frame_paths))
        if result and "best_index" in result:
            return result
    except Exception as e:
        print(f"    [llm] vision error: {e}", flush=True)
    return None


def _format_instance_block(instance_markers: dict | None) -> str:
    """Render plan.json `instance_markers` for inclusion in validator prompts.

    Returns an empty string when no markers provided. When markers exist, the
    block tells the validator to reject candidates that contradict any marker
    (wrong date, wrong venue, different participant, contradicting outcome,
    or appearance of any explicitly-excluded content).
    """
    if not instance_markers:
        return ""
    lines = ["", "INSTANCE CONSTRAINTS — frames must NOT contradict these:"]
    for k, v in instance_markers.items():
        if v not in (None, "", [], {}):
            lines.append(f"  - {k}: {v}")
    if len(lines) == 2:
        return ""
    lines.append(
        "If anything visible in the frames contradicts these markers — wrong "
        "date cue, wrong venue, different participant doing the action, "
        "contradicting scoreboard/outcome, or any 'exclude' item appears — "
        "this is the WRONG INSTANCE and the result is MISMATCH regardless of "
        "how well the general topic matches."
    )
    return "\n".join(lines) + "\n"


def validate_frames(
    frames_b64: list[str], query: str, shot_desc: str, audio_txt: str,
    instance_markers: dict | None = None,
) -> dict:
    """Save frames to temp files, send to Claude Vision for content validation.

    Strict prompt: must see the specific action AND match any instance_markers,
    not just topical context.
    """
    if not frames_b64:
        return {"matches": True, "confidence": 50, "what_i_see": "no frames"}

    import base64

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = []
            for i, fb in enumerate(frames_b64[:4]):
                p = Path(tmpdir) / f"frame_{i}.jpg"
                p.write_bytes(base64.b64decode(fb))
                paths.append(str(p))

            instance_block = _format_instance_block(instance_markers)

            prompt = (
                f'These frames are from a clip we downloaded.\n'
                f'Verify the frames show the SPECIFIC visual content described below — not just the right general topic.\n\n'
                f'REQUIRED VISUAL CONTENT (primary criterion — judge against this):\n'
                f'  "{shot_desc[:400]}"\n\n'
                f'Search query that surfaced this clip (reference only — topical match alone is NOT sufficient):\n'
                f'  "{query}"\n'
                f'{instance_block}\n'
                f'STRICT RULES:\n'
                f'- The frames must show the specific physical action, mood, composition, AND subjects described above.\n'
                f'- Same teams / same location / same sport / same season / same person is NOT enough on its own.\n'
                f'- If desc says "under pressure / defending" but frames show celebration → MISMATCH.\n'
                f'- If desc says "wide stadium shot" but frames are close-ups → MISMATCH.\n'
                f'- If desc names person X but frames show person Y doing the action → MISMATCH.\n'
                f'- If desc says "midfield possession" but frames show a set piece / corner → MISMATCH.\n'
                f'- If instance_markers are present, any contradiction (wrong date, wrong venue, wrong participant, contradicting outcome) → MISMATCH regardless of how well other criteria match.\n'
                f'- Default to MISMATCH when uncertain. False positives are worse than false negatives here.\n\n'
                f'Describe literally what you see (specific action, body positions, kit/clothing colours, location cues, identifiable subjects, any visible text/score/date).\n'
                f'Then judge AGAINST the REQUIRED VISUAL CONTENT and INSTANCE CONSTRAINTS only.\n\n'
                f'JSON only: {{"what_i_see": "specific observation", "matches": true/false, "confidence": 0-100, "reason": "why it matches or not, citing specifics from desc and instance markers"}}'
            )
            result = _parse_json(_call_with_images(prompt, paths))
            if result:
                return result
    except Exception:
        pass
    return {"matches": True, "confidence": 50, "what_i_see": "validation failed"}


def validate_image_url(
    url: str, query: str, shot_desc: str, audio_txt: str = "",
    instance_markers: dict | None = None,
) -> dict | None:
    """Download an image URL, base64-encode, and validate via Claude Vision.

    Extends the same validation pipeline used for YouTube frames to stock-image
    candidates (Pexels, Pixabay, Wikimedia, Google Images). Returns the
    validate_frames result dict, or None if download fails.
    """
    try:
        import base64
        import requests

        headers = {"User-Agent": "ESTA-Pipeline/1.0 (image validation; github.com/esta-v2)"}
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code != 200 or not r.content:
            return None
        b64 = base64.b64encode(r.content).decode("ascii")
        return validate_frames([b64], query, shot_desc, audio_txt, instance_markers=instance_markers)
    except Exception:
        return None
