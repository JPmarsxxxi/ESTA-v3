---
name: style-analysis
description: Downloads and analyses style reference videos to extract pacing patterns, visual style, energy level, and content type. Phase 1 runs Python (OpenCV + CLIP + Whisper) in background to extract frames and audio. Phase 2 Claude reads the JPEG frames and audio transcripts in-conversation and writes style_analysis.json consumed by the plan skill.
---

# Style Analysis Skill

You extract the visual and audio DNA of the user's desired video style. This feeds BrainBox (plan skill) so it knows how fast to cut, what kind of shots to use, and what energy to target.

## Preflight

1. **Conda env check.** Run `conda env list` and confirm `esta` exists. If not: *"Run `.\setup.ps1` first."* Stop.
2. **ffmpeg check.** Run `ffmpeg -version`. If not found: *"ffmpeg is required — install with `winget install ffmpeg` then come back."* Stop.
3. Read `sessions/<session-id>/requirements.json` for `topic` and `style`.

## Ask for style references

One question, not a menu:

> "Got any videos that match the style you're going for? Drop YouTube links or local file paths — or I'll find some automatically."

Parse the response:

- **YouTube URLs** (`youtube.com`, `youtu.be`) → pass via `--youtube-urls`
- **Local file paths** (`.mp4`, `.mov`, `.avi`, etc.) → validate file exists, pass via `--local-paths`
- **Other URLs** → *"I can only pull YouTube directly — download that one as an MP4 and drop the path, or I'll skip it."*
- **Nothing / "just find something"** → auto-search: generate a YouTube search query from `topic` + `style`, pass via `--search-query`
- **Mix** → handle each type, combine what's usable.

Max 5 sources. One short confirmation: *"Got it — analysing [N] video(s)."*

## Phase 1 — Extract in background

Fire via Bash with `run_in_background: true`:

```bash
conda run --no-capture-output -n esta python tools/style_analysis/run.py analyze \
  --session sessions/<id> \
  --youtube-urls "<comma-sep urls or empty>" \
  --local-paths "<comma-sep paths or empty>" \
  --search-query "<query or empty>"
```

Tell the user:

> "Extracting frames, pacing, and audio from [N] video(s) — I'll analyse them when done."

Do NOT wait. Continue with other parallelisable work (e.g., script editing).

## Phase 2 — Analyse in conversation (on background completion)

Parse the JSON stdout from Phase 1. On `"ok": false`, surface the error and stop.

On success:

1. Read `sessions/<session-id>/style_extraction.json` — this gives you `extractions[]`, each with:
   - `frame_paths` — dict of `{seq_number: [abs_path_to_jpeg, ...]}` (8 sequences × 5 frames each)
   - `seq_transcripts` — dict of `{seq_number: "whisper text for this 3s window"}`
   - `clip_content_types` — CLIP label probabilities
   - `timing` — cuts_per_minute, avg_shot_duration, etc.

2. For each video, for each of the 8 sequences, read the first JPEG frame with the Read tool (the one at index 0 for each sequence is enough — read more if ambiguous):

   ```
   Read frame_paths[seq_number][0]
   ```

3. While looking at each frame, also read `seq_transcripts[seq_number]` for what was being said/heard in that 3-second window.

4. Analyse each sequence asking yourself:

   **Visual:** What kind of shot is this? (tight close-up, wide establishing, POV, reaction cut?) How fast is the motion? What's the color grading like? Any text overlays, graphics, or meme elements?

   **Audio:** What do I hear in this transcript? (hype commentary, dry narration, crowd noise, music cues, silence, sound effects?) What's the speech pacing — rushed, punchy, deliberate?

   **Energy:** How does what I see AND hear together make me feel? Frantic and loud? Calm and cinematic? Punchy and rhythmic?

5. After reviewing all sequences across all videos, synthesise:

   - `energy_level`: `low` / `medium` / `high` / `very-high`
   - `pacing`: `slow` / `moderate` / `fast` / `ultra-fast`
   - `visual_style`: one of `cinematic` / `raw-handheld` / `clean-polished` / `meme-heavy` / `graphic-heavy` / `docu-style`
   - `dominant_content_type`: the highest-probability CLIP label across all videos
   - `shot_patterns`: plain-language description of shot types that dominate (e.g., "tight close-ups with fast reaction cuts", "wide establishing shots held 3–5s")
   - `audio_character`: how speech, music, and SFX combine (e.g., "punchy hype commentary over crowd noise", "dry voiceover on clean b-roll", "no speech — music drives everything")
   - `keywords`: 5–8 words/phrases capturing the feel (e.g., ["high-energy", "reactive", "stadium", "crowd-driven", "quick cuts"])

6. Write `sessions/<session-id>/style_analysis.json`:

```json
{
  "session_id": "<session-id>",
  "source": "<user_provided | auto_search>",
  "videos_analyzed": N,
  "pacing_patterns": {
    "cuts_per_minute": X,
    "avg_shot_duration": Y
  },
  "energy_level": "...",
  "pacing": "...",
  "visual_style": "...",
  "dominant_content_type": "...",
  "shot_patterns": "...",
  "audio_character": "...",
  "keywords": ["...", "..."],
  "timestamp": "..."
}
```

Report to user:

> "Style analysis done. [N] video(s) — [energy_level] energy, [pacing] pacing, [cuts_per_minute] cuts/min. Dominant style: [visual_style]."

Check if `sessions/<session-id>/audio.wav` also exists. If yes → invoke `timestamps`. If not → *"Waiting for audio to finish before timestamps."*

## Code references

- `tools/style_analysis/run.py` — CLI entry point. Downloads clips, runs Phase 1 extraction, writes `style_extraction.json`.
- `tools/style_analysis/analyzer.py` — `VideoAnalyzer.extract()`. OpenCV for cuts, CLIP for content type, faster-whisper for timestamped audio transcript sliced per sequence window.
- `tools/style_analysis/downloader.py` — YouTube download + search.
