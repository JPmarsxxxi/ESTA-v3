---
name: plan
description: BrainBox — generates a shot-by-shot edit plan from the script, style analysis, and research. Estimates timing at 150 wpm; real timing is reconciled automatically when timestamps.json arrives. Produces plan.json consumed by the assets and render skills. Pure skill — Claude generates shots in-conversation, no external LLM API needed.
---

# Plan Skill (BrainBox)

You are the video editor's brain. You read the script and style DNA, then produce a precise shot list — visual type, description, asset search query, text overlay, audio layer, and timing for every sentence in the script.

## Preflight

Read these files before generating anything:

1. `sessions/<session-id>/requirements.json` — topic, style, duration, `orientation` (vertical/horizontal/square — the format dial)
2. `sessions/<session-id>/script.md` — the final approved script
3. `sessions/<session-id>/style_analysis.json` — cuts_per_minute, avg_shot_duration, energy_level, visual_style, pacing, dominant_content_type, keywords
4. `sessions/<session-id>/research.json` — verified facts and claims (optional, use if present)
5. `editing-principles.md` (repo root) — the editing canon ESTA assembles by. Apply the **judgment** half when generating shots: the Murch hierarchy (§0 — emotion/story first), and §2 (J1 never cut without a reason, J2 substance over matches, J3 shot variety — don't place visually similar shots back-to-back, J4 track the script's arc). Parameterize by §3 using `orientation` (format) + `style_analysis` (feel). The deterministic rules (§1: Ken Burns, transitions, fades) are enforced later by `render` — you don't apply those here, but generate shots that give render something to work with (e.g. don't make every shot the same length — vary by energy).

If `script.md` is missing: *"No script yet — run the scriptwriter skill first."* Stop.
If `style_analysis.json` is missing: *"Style analysis hasn't run yet — invoke the style-analysis skill first (or it may still be running in the background)."* Stop.

Check if `sessions/<session-id>/plan.json` already exists. If yes and `timing_source` is `"timestamps"`: *"Plan already exists with real timestamps — nothing to regenerate. Want me to rebuild it anyway?"* Wait for confirmation before proceeding.

## Mode selection

Two modes. `pipeline.json`'s plan step decides (`plan:bulk` / `plan:manual`); a bare `plan` token means bulk. The user can also switch conversationally at any time ("do this hands-on", "switch to manual", "just do the rest yourself") — respect it from the next shot onward and update the pipeline.json step token to match.

- **bulk** (default) — everything below as written: two-pass generation, all shots streamed to `plan_progress.jsonl` immediately.
- **manual** (hands-on) — the per-line approval loop in the "Manual mode" section. Same shot JSON, same streaming file, same downstream contracts; the ONLY difference is each line waits for the user's approval before it is appended.

## Derive pacing from style analysis

From `style_analysis.json`:
- `cuts_per_minute` → shots per minute
- `avg_shot_duration` → seconds per shot

Compute:
```
shots_per_second = cuts_per_minute / 60
seconds_per_shot = avg_shot_duration          # cross-check: 1 / shots_per_second
words_per_shot   = seconds_per_shot * 2.5     # 150 wpm = 2.5 words/second
sentences_per_chunk = max(2, round(words_per_shot / avg_words_per_sentence))
```

`avg_words_per_sentence` = count all words in script body divided by sentence count (rough is fine).

If `style_analysis.json` is absent or has no `cuts_per_minute`, fall back to:
- `cuts_per_minute = 8`, `avg_shot_duration = 7.5` (moderate pacing)

## Timing estimation (150 wpm)

For each sentence, compute cumulative word-position in the full script, then:
```
start_est = word_position / 2.5   (seconds from 0)
end_est   = (word_position + sentence_word_count) / 2.5
```

These are the initial `start` and `end` values too (both fields get the estimate). Real timestamps replace `start`/`end` when reconcile runs; `start_est`/`end_est` are never overwritten.

## Two-pass shot generation

### Pass 1 — type assignment

For each sentence in the script, assign:
- `visual.type`: `REAL_FOOTAGE` | `REAL_IMAGE` | `MOTION_GRAPHICS`
- A one-line rationale (internal — not in JSON output)

Rules:
- Action, movement, crowds, sport → `REAL_FOOTAGE`
- Talking heads, portraits, still scenes, product shots → `REAL_IMAGE`
- Stats, facts, text reveals, abstract concepts, hook/CTA emphasis → `MOTION_GRAPHICS`
- A stat/name/phrase spoken **over relevant footage** → keep the footage type and add an `overlay` block instead (see overlay rules below) — reserve full `MOTION_GRAPHICS` for moments where the graphic IS the shot
- HOOK sentence: prefer `MOTION_GRAPHICS` or `REAL_FOOTAGE` (high energy)
- CTA sentence: prefer `MOTION_GRAPHICS` (clean, focused)
- Vary types — avoid 3+ consecutive identical types unless the content demands it

### Between Pass 1 and Pass 2 — start assets streaming

Immediately after Pass 1 completes (all types assigned):

1. Create an empty `sessions/<session-id>/plan_progress.jsonl` (Write tool, empty string content).
2. Fire assets in background:

```bash
conda run --no-capture-output -n esta python tools/assets/run.py fetch \
  --session sessions/<id>
```

Use `run_in_background: true`. Assets will poll `plan_progress.jsonl` and start downloading shot 1 the moment it appears — no waiting for the full plan.

### Pass 2 — full shot detail

For each sentence (= one shot), fill every field. After generating each shot's complete JSON, append it to `plan_progress.jsonl` (Write tool, full accumulated content so far — one shot JSON per line, no trailing comma, each line valid standalone JSON). This lets assets start downloading each shot the moment its search query exists.

```json
{
  "shot_number": 1,
  "start": <start_est>,
  "end": <end_est>,
  "start_est": <start_est>,
  "end_est": <end_est>,
  "audio": "<exact sentence from script>",
  "visual": {
    "type": "REAL_FOOTAGE | REAL_IMAGE | MOTION_GRAPHICS",
    "specificity": "high | medium | low",
    "search_sources": [
      {"source": "<source_name>", "queries": ["<most specific query>", "<broader fallback>"]},
      {"source": "<source_name>", "queries": ["<query>"]}
    ],
    "desc": "<what's on screen — 1 sentence, visual language>",
    "search_query": "<3-5 word query for stock search, concrete nouns>",
    "fx": ["<effect if any, e.g. zoom_in, slow_motion — empty list if none>"],
    "instance_markers": {
      "event_date": "<YYYY-MM-DD if shot references a specific dated instance, else omit field>",
      "location": "<venue/place if specific instance, else omit>",
      "key_participants": ["<named subject>", "..."],
      "expected_outcome": "<scoreline/result/verdict text the frames should support, else omit>",
      "exclude": ["<things that would indicate the WRONG instance — e.g. wrong venue, different season — else omit>"]
    }
  },
  "text": {
    "caption": "<key phrase if text overlay adds value, else empty string>",
    "style": "<bold_white | minimal | none>",
    "pos": "bottom | top | center"
  },
  "audio_layer": {
    "music": "<mood descriptor or empty string — e.g. 'upbeat hip-hop', 'tense strings'>",
    "sfx": [
      "<either a bare sound name — e.g. 'whoosh', 'record scratch'>",
      {"sound": "<sound name>", "on": "<the exact spoken WORD it should hit>"}
    ]
  },
  "overlay": {
    "desc": "<what the floating graphic shows — 1 sentence, visual language>",
    "caption": "<exact text on the card — the stat, name, or punchline>",
    "style": "stat_card | label | progress_bar | kinetic_text"
  },
  "transition": "cut | fade | zoom | wipe"
}
```

**overlay rules (optional field — omit entirely for most shots):**
- An `overlay` is a **generated motion graphic floating over the shot's footage** (transparent WebM on the Graphics track, made by the motion-graphics skill). The shot keeps its normal `visual` (footage/image fetched by assets) AND gets the graphic on top.
- Use overlay when on-screen text/numbers would **reinforce real footage**: a stat spoken over b-roll, a name label over a person, a score over match footage, a key phrase punched over the action.
- Do NOT put an `overlay` on a `MOTION_GRAPHICS` shot — that type is already a full-frame generated graphic; an overlay would be a graphic on a graphic.
- Decision rule: *does the audience need to see the footage AND the text at once?* Yes → `REAL_FOOTAGE`/`REAL_IMAGE` shot + `overlay`. *Is the text/graphic the whole point of the moment?* → `visual.type: MOTION_GRAPHICS`, no overlay.
- `caption` is the exact text the card renders — keep it under ~8 words, numbers welcome. `desc` describes the visual treatment.
- At most ~1 overlay per chunk; overlays lose punch when every shot has one.

**sfx rules (optional — most shots have none):**
- A cue is punctuation, not wallpaper — a sound that lands ON a beat (sound-design §J3). One or two per shot at most, and only where the script *sets one up*: a reveal, a turn, a punchline, an impact.
- **Name the trigger word when the comedy or emphasis rides on a specific word.** Use the object form `{"sound": "record scratch", "on": "but"}` — `on` is the exact spoken word the sound should hit. The fulfilment step (`tools/audio/sfx_from_plan.py`) looks that word up in the real word-level timing and lands the sound's peak on it, so a scratch hits on *"but"*, a cha-ching after the number, an engine rev under the flex. Without `on` the sound falls to the shot's start — fine for ambience, weak for a joke.
- Pick the `on` word from the shot's own `audio` line (the words actually spoken in that shot). Bare-string form is fine when timing to the shot is enough.

**specificity rules:**
- `"high"` — shot requires a specific named person, named event, or named place that stock libraries won't have. Examples: "Leandro Trossard goal", "Donald Trump press conference", "2022 World Cup final penalty". For high-specificity shots: `search_sources` must include `youtube` or `wikimedia` first — never lead with `pexels`/`pixabay`.
- `"medium"` — specific event or context but generic footage can work. Examples: "goalkeeper diving save", "bench erupting celebration". Mix of sources; YouTube or Archive alongside Pexels/Pixabay.
- `"low"` — fully generic b-roll, reactions, or graphics. Examples: "crowd cheering", "man surprised face", "clock graphic". Lead with `pexels`/`pixabay`/`giphy`.

**search_sources rules:**
- 2–3 sources ordered best-first for this shot's specificity
- Each source gets 1–3 queries: most specific first, broadening toward fallback
- Include at least 2 of these in high-specificity queries: exact name, year, event, location, opposing team
- Available sources: `youtube`, `pexels_video`, `pixabay_video`, `pexels_image`, `pixabay_image`, `wikimedia`, `archive`, `giphy`, `google_images`, `pinterest`
- For `REAL_FOOTAGE` high: `["youtube", "archive"]`
- For `REAL_IMAGE` high: `["google_images", "wikimedia"]` — Google Images returns real press/news photos; wikimedia as fallback for CC-strict needs
- For `REAL_FOOTAGE` low/medium: `["pexels_video", "pixabay_video", "archive"]`
- For `REAL_IMAGE` low/medium: `["pexels_image", "pixabay_image", "pinterest", "wikimedia"]`
- For `MOTION_GRAPHICS`: `["giphy", "pixabay_image"]`
- **Meme override:** when `desc` mentions "meme", "reaction", "this is fine", "shrug", "facepalm", or similar reaction-meme cues, the source list MUST include `giphy` as the first or second source — even for `type: REAL_IMAGE`. Giphy is the reaction-meme library; without it the picked candidate will be generic stock that doesn't land.
- **Aesthetic override:** when `desc` (or the `style` from style_analysis) mentions "aesthetic", "moodboard", "mood board", "vibe", "vibes", "minimalist", "minimal", "cozy", "dreamy", "ethereal", "ambient", "lo-fi", "softcore", "core" (as a vibe suffix like cottagecore / dark academia), or similar mood/atmosphere cues, **lead with `pinterest`** in the source list. Pinterest is the moodboard library — without it the picks will be flat stock that doesn't carry the vibe. Example: aesthetic shot → `[{"source": "pinterest", "queries": ["minimalist desk morning light"]}, {"source": "pexels_image", "queries": ["minimalist desk"]}]`.

**instance_markers rules (optional — include only when shot references a specific dated/recurring instance):**
- Use ONLY when the audio references a specific instance of a recurring topic — a particular match, speech, launch, keynote, earnings call, news event. SKIP for generic b-roll, reactions, motion graphics.
- `event_date`: ISO date if known (derive from currentDate context — see search_query rules below).
- `location`: venue / city / country if the instance has a specific place.
- `key_participants`: named subjects expected to be visible or central to the action in this exact instance.
- `expected_outcome`: anything a viewer should be able to see in-frame to confirm the right instance — scoreboard, headline text, result graphic, badge/banner.
- `exclude`: red-flag content that would indicate the WRONG instance was picked — wrong venue, wrong kit, wrong era, wrong season. The validator uses this as a reject signal.
- All sub-fields are optional. Include only what you can derive from the script + research; omit any field you'd be guessing at.

**search_query rules:**
- Concrete nouns + context: "Arsenal fans celebrating Wembley" not "fans"
- Match `visual.type`: footage queries use verbs ("players running pitch"), image queries use nouns ("goalkeeper portrait stadium"), MG queries describe the graphic ("percentage stat counter")
- 3-5 words maximum
- No stop words (the, a, an, in, on)
- **Year context:** when a query includes a year, derive it from the `currentDate` in the CLAUDE.md project context. For recent or current-events subject matter, prefer the current year; the previous year is only acceptable as a fallback query variant on a separate retrieval pass. Never hardcode years; never use training-cutoff-era years (2023/2024) unless the topic is genuinely from that era.

**text overlay rules:**
- Add captions only when they reinforce the audio — key stats, punchlines, names
- HOOK: usually a caption (grabs attention); CTA: usually a caption ("Subscribe", "Link in bio")
- Body shots: captions only for stats or memorable phrases

**music rules:**
- One music note per chunk (4-5 shots) — don't change music every shot
- Use the `energy_level` from style_analysis to set overall music intensity
- Empty string for shots where the previous shot's music continues (render will inherit)

**transition rules:**
- Default: `cut` (fastest, matches most modern content)
- Use `fade` for scene changes or CTA
- Use `zoom` for emphasis moments (big reveal, stat drop)
- Use `wipe` sparingly — only for structured "chapter" transitions

## Manual mode (hands-on) — per-line approve → fetch pipeline

The user is the editor-in-chief; you present one shot at a time and their approval releases it to assets. Approval gates the **idea only** — fetched picks are judged visually on the live timeline (the user typically has OpenCut open in a VS Code Simple Browser panel), not re-approved in chat.

Setup (once, before the first card):
1. Do Pass 1 type assignment internally for the WHOLE script (you need the full-arc view for shot variety — J3 — even though shots are revealed one at a time).
2. Create the empty `plan_progress.jsonl` and fire the assets background fetch exactly as in bulk mode — it idles until lines appear.

The loop, for each script sentence in order:
1. Generate the shot's complete JSON (Pass 2 detail) internally.
2. Show a **compact card** — not raw JSON: the spoken line, visual type + one-line desc, the search query, caption/overlay text, duration, transition. One or two sentences of rationale only when the choice is non-obvious.
3. Read the reply per pipeline rules:
   - **Green light** ("go", "yeah", "next", silence-equivalents) → append the shot's JSON line to `plan_progress.jsonl` (assets starts fetching it) → **immediately present the next card**. Never wait for the fetch.
   - **Tweak** ("make it a meme", "different query", "no caption") → apply to the card in place, re-show ONLY what changed, wait again. Tweaks are cheap; never regenerate the whole card unless asked.
   - **Redo a released shot** ("redo shot 3", "shot 3 is ugly") → re-fetch with `run.py shot --n 3 --source <src> --query "..."` (new query/source per their feedback), then continue where you were.
   - **Mode switch** ("just finish the rest", "back to auto") → append all remaining shots without approval (bulk the tail), or the reverse.
4. When a fetch completes in the background, run the render pass (`tools/render/run.py build`) so the timeline hydrates shot by shot — do this without narrating it every time; one short note every few shots is plenty.

After the last line is approved: assemble `plan.json` from all released lines (same schema as bulk), run reconcile if `timestamps.json` exists, and continue with the normal handoff below. MOTION_GRAPHICS shots and `overlay` blocks fire their hyperframes generation on approval too (same rhythm — the sub-agent renders while you present the next card; publishing follows the motion-graphics skill's feed rules).

## Output format

Build the full plan in one JSON block. Chunk shots into groups of `sentences_per_chunk` for editorial reference (internal grouping only — not a separate JSON field):

```json
{
  "session_id": "<session-id>",
  "timing_source": "estimated",
  "video_metadata": {
    "title": "<descriptive title from requirements>",
    "duration_est": <total end_est of last shot>,
    "style": "<visual_style from style_analysis>",
    "shot_count": <N>,
    "chunk_count": <ceil(N / sentences_per_chunk)>
  },
  "shots": [ ... ],
  "editing_notes": {
    "pacing": "<1 sentence on the rhythm — e.g. 'Fast cuts at 9/min matching reference energy'>",
    "avg_shot_est": <avg_shot_duration from style_analysis>,
    "method": "150wpm-estimate"
  },
  "generated_at": "<ISO 8601 UTC timestamp>"
}
```

Write to `sessions/<session-id>/plan.json`.

## Timing safety

`timing_source` starts as `"estimated"`. The timestamps skill runs `reconcile` automatically after transcription, which updates `start`/`end` fields with real word-level timing. `start_est`/`end_est` are permanent reference — they are never touched by reconcile or anything else.

If `timestamps.json` already exists when plan runs (e.g. timestamps finished first), run reconcile immediately after writing plan.json:

```bash
conda run --no-capture-output -n esta python tools/timestamps/run.py reconcile \
  --session sessions/<id>
```

Parse the result and note whether timing was updated.

## Early render — make the timeline visible NOW

The editor is session-bound from project creation, watches the session's
`<session-id>.openreel.json` on disk, and auto-loads any revision it sees. So
the moment we write a project file, the user's timeline materializes. We don't
have to wait for assets to finish — render's contract already covers a "shots
are placeholders" run as long as `plan.json` (and audio.wav / timestamps.json
if they ran) exists.

Right after writing `plan.json` (and after the optional reconcile above), fire
the early render pass:

```bash
conda run --no-capture-output -n esta python tools/render/run.py build \
  --session sessions/<id>
```

This writes `sessions/<id>/<id>.openreel.json` with: the full timeline shape
(shot slots, durations, transitions), the voiceover track, and karaoke
subtitles — and stream-pending placeholders for the shots whose media hasn't
landed yet. The editor's session-file-sync picks it up and the timeline
appears live; as the assets background job downloads each shot, the
asset-server SSE feed hydrates the placeholders in place.

If render exits non-zero (rare — usually a missing dependency), don't block:
log the message and continue. The final render pass below will catch any
recoverable state.

## Show + hand off

Show a concise summary — not raw JSON:

> "Plan done. [N] shots across [duration_est]s (~[duration_est/60:.1f] min), [chunk_count] chunks at [cuts_per_minute] cuts/min. Timing: estimated (150 wpm) [· Real timing reconciled — N shots updated. if reconcile ran]."

Then announce next step **and point at the browser editor** — reviewing 20+ shots in chat is serial and gated on reply latency; the editor lets the user work through them at their own pace, in any order, while assets fetch:

> "Early timeline is on screen — voiceover + subs live, shots stream in as assets download. Review + adjust the shot list at **http://localhost:8787/_plan?session=<id>** (needs `node tools/asset-server.mjs` running), or just tell me here. Anything to change?"

Read the user's reply per pipeline rules (tweak / redirect / green-light).

**The plan editor (`tools/planner/`, served by the asset-server) is the official review surface.** It edits `plan.json` shot-by-shot — fields, per-source queries, SFX with `sound | word` triggers, captions — and carries two agent actions the user drives themselves:
- **✨ Rewrite** (`/_plan/api/rewrite`): describe a vibe, a lean background `claude` (~$0.03/haiku) rewrites the shot's fields; the user reviews and saves. Nothing touches `plan.json` until they save.
- **Structural command** (`/_plan/api/command` → `tools/plan/ops.py`): "split at the word 'had'", "merge with the next shot", "add an overlay saying X". The agent parses intent; the engine does the timing (word→onset from `timestamps.json`), renumbering, and asset-feed migration deterministically.

Chat edits still work (Edit `plan.json` directly). The editor is for when the user wants to drive the review themselves without waiting on turns.

**Motion graphics hand-off:** if the plan contains any `MOTION_GRAPHICS` shots or `overlay` blocks, invoke the `motion-graphics` skill after the green light (assets keeps downloading in the background — the two run side by side; assets' giphy picks for MG shots are the fallback the generated clips overwrite).

**Tweak handling:** If the user wants to change a shot, edit it directly in plan.json with the Edit tool. Re-show only the changed shot(s). Do NOT regenerate the whole plan. If assets already downloaded a shot being changed, note the query changed — the user can re-run assets for that shot manually.

When assets completes (background notification arrives), invoke the `render` skill again for the final pass — same command, same file path. The editor's
session-file-sync auto-loads the new revision (silently if the user hasn't
edited locally; banner-with-choice if they have).

## Code references

- `tools/plan/schema.py` — TypedDicts for `Shot`, `Visual`, `TextOverlay`, `AudioLayer`, `Plan`.
- `tools/timestamps/reconcile.py` — Sequential word-overlap matching. Called via `tools/timestamps/run.py reconcile`.
- `tools/timestamps/run.py` — `reconcile` subcommand. Always call via `conda run --no-capture-output -n esta`.
