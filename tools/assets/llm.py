"""Claude-via-CLI helper for asset-picking decisions.

Calls `claude -p` as a subprocess, which uses the user's existing Claude Code
subscription auth — no API key needed.

Uses haiku for speed/cost. Calls are lean (SPEC.md Part 8): stream-json input
with images inline, a one-line system prompt, no tools/MCP/settings/skills and
thinking off. A full Claude Code session per call carried ~33k tokens of
overhead and took 15-19 s; lean calls take ~2k tokens and ~5 s.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.usage import ledger  # noqa: E402

_HAIKU  = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"

_SYSTEM = "You check footage and pick moments for a video editor. Reply with only the requested JSON."
_LEAN = ["--strict-mcp-config", "--setting-sources", "", "--tools", "", "--max-turns", "1", "--no-session-persistence"]
MAX_SIDE = 768


class ClaudeUnavailable(RuntimeError):
    pass


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


def _spawn(argv: list[str], message: str, timeout: int) -> str:
    """One `claude -p` process; returns stdout. Tests replace this."""
    r = subprocess.run(argv, input=message + "\n", capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env={**os.environ, "MAX_THINKING_TOKENS": "0"})
    return r.stdout or r.stderr


def _ask(content: list[dict], kind: str, model: str = _HAIKU, timeout: int = 60) -> str:
    """One lean turn over text and image blocks; returns the reply text.
    Raises ClaudeUnavailable once a limit/auth reply has been seen in this process."""
    if ledger.unavailable():
        raise ClaudeUnavailable(ledger.unavailable())
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    argv = [_claude_bin(), "-p", "--model", model, "--input-format", "stream-json", "--output-format",
            "stream-json", "--verbose", "--system-prompt", _SYSTEM, *_LEAN]
    t0 = time.time()
    try:
        out = _spawn(argv, msg, timeout)
    except subprocess.TimeoutExpired:
        ledger.record(kind, model, None, time.time() - t0, "timeout")
        raise
    result = None
    for line in out.splitlines():
        if line.startswith("{"):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") == "result":
                result = e
    text = (result or {}).get("result") or ""
    if ledger.fatal_reply(text or out[-500:]):
        print(f"    [llm] claude unavailable, skipping further checks: {ledger.unavailable()}", flush=True)
        ledger.record(kind, model, result, time.time() - t0, ledger.unavailable())
        raise ClaudeUnavailable(ledger.unavailable())
    if result is None or result.get("is_error"):
        err = (text or out[-300:]).strip()[:300] or "no result"
        ledger.record(kind, model, result, time.time() - t0, err)
        raise RuntimeError(err)
    ledger.record(kind, model, result, time.time() - t0)
    return text


def _jpeg_b64(data: bytes, max_side: int = MAX_SIDE) -> str:
    """Re-encode an image as a JPEG no larger than max_side: a 1080p frame is ~2.7k
    image tokens, 768 px ~0.8k, and full-size originals can exceed the API's limits."""
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("undecodable image")
        h, w = img.shape[:2]
        if max(h, w) > max_side:
            s = max_side / max(h, w)
            img = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            return base64.b64encode(buf.tobytes()).decode("ascii")
    except ImportError:
        pass
    return base64.b64encode(data).decode("ascii")


def _image(b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}}


def _call(prompt: str, model: str = _HAIKU, timeout: int = 60, kind: str = "text") -> str:
    """Run a lean text-only turn and return the result text."""
    return _ask([{"type": "text", "text": prompt}], kind, model, timeout)


def _call_with_images(prompt: str, images_b64: list[str], model: str = _HAIKU, timeout: int = 60,
                      kind: str = "vision", labels: list[str] | None = None) -> str:
    """Vision turn: images (re-encoded <= MAX_SIDE, optionally each preceded by a label), then the prompt."""
    content = []
    for i, b in enumerate(images_b64):
        if labels:
            content.append({"type": "text", "text": labels[i]})
        content.append(_image(_jpeg_b64(base64.b64decode(b))))
    content.append({"type": "text", "text": prompt})
    return _ask(content, kind, model, timeout)


def _capture(kind: str, prompt: str, images_b64: list[str], raw: str, parsed: Any, error: str,
             secs: float, meta: dict | None) -> None:
    """Opt-in eval capture (ESTA_VISION_CAPTURE=1): the exact frames, prompt and verdict of a vision call,
    under <session>/vision_eval/, for tools/vision_eval/replay.py."""
    if os.environ.get("ESTA_VISION_CAPTURE") != "1":
        return
    try:
        root = ledger.ledger_path().parent / "vision_eval"
        cid = hashlib.sha1((prompt + "".join(b[:200] for b in images_b64)).encode()).hexdigest()[:16]
        d = root / cid
        d.mkdir(parents=True, exist_ok=True)
        files = []
        for i, b in enumerate(images_b64):
            p = d / f"frame_{i}.jpg"
            p.write_bytes(base64.b64decode(_jpeg_b64(base64.b64decode(b))))
            files.append(str(p.relative_to(root)))
        rec = {"id": cid, "kind": kind, "prompt": prompt, "frame_files": files, "model": _HAIKU,
               "raw_result": raw, "parsed": parsed, "error": error, "latency_s": round(secs, 2), **(meta or {})}
        with ledger._LOCK, open(root / "records.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


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
        result = _parse_json(_call(prompt, kind="pick_videos"))
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
        result = _parse_json(_call(prompt, kind="find_moment"))
        if result and result.get("segments"):
            return result["segments"]
    except Exception:
        pass
    return []


def find_best_frame_at_timestamps(
    frame_paths: list[str], timestamps: list[float], query: str, shot_desc: str, round_n: int = 1,
    instance_markers: dict | None = None, meta: dict | None = None,
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
    t0, raw, err, result = time.time(), "", "", None
    images = [base64.b64encode(Path(p).read_bytes()).decode("ascii") for p in frame_paths]
    try:
        raw = _call_with_images(prompt, images, kind="frame_search", labels=[f"frame {i}:" for i in range(len(images))])
        result = _parse_json(raw)
    except Exception as e:
        err = str(e)[:300]
        print(f"    [llm] vision error: {e}", flush=True)
    _capture("frame_search", prompt, images, raw, result, err, time.time() - t0, meta)
    if result and "best_index" in result:
        return result
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


def validate_prompt(query: str, shot_desc: str, instance_markers: dict | None = None) -> str:
    """The validator's prompt text, shared with tools/vision_eval/replay.py."""
    instance_block = _format_instance_block(instance_markers)
    return (
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


def validate_frames(
    frames_b64: list[str], query: str, shot_desc: str, audio_txt: str,
    instance_markers: dict | None = None, meta: dict | None = None,
) -> dict | None:
    """Send up to 4 frames to Claude Vision for content validation.

    Strict prompt: must see the specific action AND match any instance_markers,
    not just topical context. Returns None when there is nothing to judge or the
    check fails, so callers leave the candidate unvalidated: a failed check must
    never approve a clip (v2 returned a 50% match here).
    """
    if not frames_b64:
        return None
    prompt = validate_prompt(query, shot_desc, instance_markers)
    images = frames_b64[:4]
    t0, raw, err, result = time.time(), "", "", None
    try:
        raw = _call_with_images(prompt, images, kind="validate")
        result = _parse_json(raw)
        if not isinstance(result, dict) or "matches" not in result:
            err, result = "unparseable reply", None
    except Exception as e:
        err = str(e)[:300]
    _capture("validate", prompt, images, raw, result, err, time.time() - t0, meta)
    return result


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
        import requests

        headers = {"User-Agent": "ESTA-Pipeline/1.0 (image validation; github.com/esta-v2)"}
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code != 200 or not r.content:
            return None
        b64 = base64.b64encode(r.content).decode("ascii")
        return validate_frames([b64], query, shot_desc, audio_txt, instance_markers=instance_markers,
                               meta={"url": url})
    except Exception:
        return None
