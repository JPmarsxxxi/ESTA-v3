---
name: audio
description: Produces the session audio. Modes — expressive clone with IndexTTS2 on Kaggle's free GPU (per-line emotion, word stress, pauses, pace, plus Seed-VC guide takes the user acts out), legacy XTTS clone, multi-take self-recording, or found-fetch (gather a found-audio/SFX/music pool from free + fair-use sources for Bumblebee-style collages). Clone/self-record read sessions/<id>/script.md and write audio.wav; found-fetch reads requirements.json + research.json (no script needed) and writes audio_pool.json. Requires the esta conda env. Auto-chains toward timestamps (clone/self-record) or the scriptwriter arranger (found-fetch).
---

# Audio Skill

You produce the voiceover the audience will hear. The script is already locked (`script.md`) — your only job is getting a clean audio file at `sessions/<id>/audio.wav` and metadata next to it.

## Preflight

1. **Conda env check.** Run `conda env list` and check for a line starting with `esta`. If not found, tell the user: *"The esta conda env is missing — run `.\setup.ps1` once to create it, then come back."* Stop. (The env does not need to be active — skills call `conda run --no-capture-output -n esta` automatically.)
2. Read `sessions/<session-id>/script.md`. If missing, tell the user: *"No script yet — run the scriptwriter first, then we'll voice it."* Stop. **Exception:** the **found-fetch** mode runs BEFORE a script exists — it needs `requirements.json` (+ `research.json` as the brief), not `script.md`. Skip this check for found-fetch.
3. Read `sessions/<session-id>/requirements.json` (for `script_word_count` context).
4. Read `profile/preferences.md` if it exists.
5. Read `config.yaml` for `gpu_available` (defaults to false).
6. **Found-fetch / collage mode:** read `sound-design.md` (repo root) and apply its **judgment** half when picking and sequencing found audio — §0 mix hierarchy (voice intelligible above all), J1 silence as punctuation (don't fill every second), J2 ambience felt-not-heard, J3 SFX punctuate don't clutter, J4 sound carries emotion. Parameterize by §3 (music-forward vs narration-forward; `requirements.orientation` for the loudness/clarity target). The deterministic mix rules (§1: loudness, ducking, fades, levels) are enforced by `render` — not here — but gather/level sources so render has the stems to work with.
7. Append every conversational turn to `sessions/<session-id>/conversation.jsonl` with the actual current timestamp (`datetime.now().isoformat()`).

## Tone

Brief and clear — audio is operational, not creative. The creative work happened in scriptwriting. Don't over-talk it.

## Mode selection — natural language, never a numbered menu

Open with one question:

> "How are we voicing this — cloning your voice, you recording yourself, or building it from found audio (clips, SFX, music from across the internet — the Bumblebee approach)?"

Parse the user's natural answer:
- "clone my voice", "use AI", "tts", "the usual" → **expressive clone path** (IndexTTS2). This is the default clone engine.
- "XTTS" by name → **XTTS path** (legacy; warn about the licence first).
- "I'll record", "I'm doing it", "record myself", "manual" → **self-record path**.
- "found audio", "clips", "from the internet", "bumblebee", "no voiceover", "supercut", "multi-voice / cuts / SFX" → **found-fetch path**.
- Ambiguous / non-answer → briefly re-ask, defaulting to the expressive clone as the most common path: *"Going with the voice clone unless you tell me you're recording yourself."*

## Expressive clone path (IndexTTS2 — the default)

IndexTTS2 clones the voice *and* takes direction: an emotion per line, stressed
words, pauses, pace. It runs on Kaggle's free T4 — this machine's GPU is 4 GB,
which is too small — so generation is a detached background job, not a local one.

**The rule that matters: nothing is generated until the user approves the tagged
script.** Delivery is a creative decision and a Kaggle run costs ~8 minutes.

Preflight for this path: `~/.kaggle/kaggle.json` must exist. If it doesn't, say
*"Kaggle API token missing — drop your kaggle.json in ~/.kaggle/ and I'll pick it up"* and stop.

### 1. Voice sample

Same selection rules as the XTTS path below (`voice_samples/`, presets vs user
samples, 6-12s sweet spot). The sample is the voice; the tags are the delivery.

### 2. Ask the vibe — one question, not a form

> "What's the vibe for this one? Something like 'sarcastic, bitter, laughing at myself' — I'll tag each line from there and show you before anything generates."

Take the answer as the *baseline* register. Do not ask line-by-line questions —
the user fine-tunes specific lines at the approval step (step 4).

### 3. Tag the script yourself

Read `script.md` and write `sessions/<id>/script.tagged.md`: the same words, with
delivery markup added. Vary the emotion with the meaning of each line — the vibe
answer is the centre of gravity, not a label to paste on every line.

| Markup | Meaning |
|---|---|
| `{bitter, scoffing}` | Emotion for the line, free text, fed to IndexTTS2 as `emo_text` |
| `{emo: angry 0.5, disgusted 0.3}` | Exact emotion vector — skips the classifier |
| `*word*` | Stress this word (rendered to the engine as CAPS) |
| `[pause]` / `[pause: 800]` | Split here and insert silence (default 450ms) |
| `{... \| pace: slow}` | `very slow`/`slow`/`normal`/`fast`/`very fast`, or a raw multiplier |
| `{... \| pause: 600}` | Silence after the line |
| `{guide: takes/foolery.wav}` | The user acted this line out — Seed-VC converts their take into the cloned voice, keeping their exact delivery |

`[SECTION]` headers carry through untouched and are never spoken.

**Write emotions the model can actually place.** IndexTTS2 scores free text
against eight emotions — happy, angry, sad, afraid, disgusted, melancholic,
surprised, calm — and silently falls back to **calm** for anything it can't map:
`{sarcastic, amused}` came back calm=1.0 in testing, i.e. no direction at all.
So keep one of those eight words in the tag (`{amused, happy}`, `{bitter, angry}`),
or state the vector outright with `{emo: angry 0.5, disgusted 0.3}` when the read
matters. The run log prints the detected vector per line — check it after a run
and re-tag any line that came back calm when it shouldn't have.

Then parse it into the job list:

```powershell
conda run --no-capture-output -n esta python tools/audio/run.py tag-check --session sessions/<id> --sample voice_samples/<sample>.wav
```

This writes `voice_script.json` and reports line count, how many lines are tagged,
and any `{guide:}` file that doesn't exist yet.

### 4. Show it for approval — always

Display the tagged script in chat (the markup is the point — it's readable), then:

> "That's the delivery plan — change any line's emotion, stress or pauses before I generate."

Parse the reply:
- **Line edits** ("line 3 angrier", "don't stress 'war'", "longer pause before foolery") → edit `script.tagged.md`, re-run `tag-check`, re-show.
- **Wants to act a line out** → see step 7.
- **Green light** → generate.

### 5. Generate + stitch

```powershell
python tools/audio/run.py expressive --session sessions/<id>
```

**System python, not `conda run`** — the Kaggle CLI lives there (same as the
`ai-video` skill); the copy inside `esta` has no `-m kaggle` entry point.

Run via Bash with `run_in_background: true` — it pushes a Kaggle kernel and polls
(~8 min: install, checkpoint download, then a few seconds per line). Announce it,
then **immediately invoke `style-analysis`** so it runs in parallel. Each line lands
as `voice_build/lines/line_<id>.wav`.

When the notification arrives, join them (pace + pauses are applied here, locally):

```powershell
conda run --no-capture-output -n esta python tools/audio/run.py stitch --session sessions/<id>
```

That writes `audio.wav` + `audio_metadata.json` (`method: "indextts2"`).

### 6. Review + per-line redo

Tell the user the duration and that single lines can be redone:

> "2m 14s. Listen through — if a line's off, tell me which one and how, and I'll redo just that line."

To redo, edit that line's tags in `script.tagged.md`, re-run `tag-check`, then:

```powershell
python tools/audio/run.py expressive --session sessions/<id> --only L04,L07
```

Only those lines regenerate; everything else is reused. Re-run `stitch` after.

### 7. Guide takes (Seed-VC)

When the user wants a line delivered *exactly* their way, they record it and you
tag the line `{guide: takes/<name>.wav}` (path relative to the session folder).
Seed-VC keeps their timing, pauses and emphasis and swaps in the cloned voice.
Guide lines ignore `{emotion}` — the performance *is* the emotion — but pace and
pause still apply at stitch time.

## XTTS path (legacy)

Only when the user asks for XTTS by name. First run prompts to accept Coqui's
CPML licence, which is **non-commercial only** and can no longer be upgraded
(Coqui shut down) — say so and let the user decide; never accept it for them.

### 1. Voice sample selection

`voice_samples/` holds two kinds of files:
- **Presets** — filenames starting with `preset_` (e.g. `preset_brit_male.wav`). Ship with the repo, available to any user without recording.
- **User samples** — everything else (e.g. `voice_arsenal_2026-05-11.wav`). Recorded by this user, saved from previous sessions.

List both groups separately in plain language (name + duration). Then ask:

> "Want to use one of these, or record your own sample?"

Parse:
- Names a preset or user sample, or says "the brit one", "that first one", etc. → use it.
- "record my own", "I'll drop one", "fresh sample" → ask for a file path.
- If only presets exist (no user samples yet) → mention that, then offer presets or a fresh recording.

When the user provides a path to a new sample:
- Validate it inline (WAV, single speaker, 6-12s sweet spot — warn below 3s or above 20s).
- Surface warnings naturally: *"Sample is 18 seconds — a bit long, XTTS prefers 6-12s. Use it anyway?"*
- Once accepted, copy the file to `voice_samples/voice_<topic-slug>_<YYYY-MM-DD>.wav`. This is its canonical location for future re-use.

### 2. Generate

Tell the user: *"Generating with XTTS in the background — first run loads the model (~30s), then generation runs. Kicking off style-analysis in parallel now."*

Run via the Bash tool with `run_in_background: true`:

```bash
conda run --no-capture-output -n esta python tools/audio/run.py xtts \
  --session sessions/<id> \
  --sample voice_samples/<sample>.wav \
  --speed 1.0
```

(Add `--gpu` if `gpu_available` is true in config.yaml.)

Do NOT wait for this to finish. Immediately invoke the `style-analysis` skill so it runs in parallel with XTTS generation. When the XTTS background task completes you will be notified — at that point parse the JSON stdout. On `"ok": false`, surface `error` and offer the self-record path as a fallback. Then proceed to timestamps.

### 3. Validate the result

```powershell
conda run --no-capture-output -n esta python tools/audio/run.py validate --path sessions/<id>/audio.wav
```

Parse the JSON response to confirm the file landed cleanly and capture duration/channels/sample_rate/size for the metadata.

## Self-record path

### 1. Show the script + recording tips

Display `script.md`. One short paragraph of tips: read naturally not robotically, multiple takes are fine, save as WAV.

### 2. Multi-take loop

For each take attempt:
- Ask: *"Drop the path to your recording when you're ready."*
- Validate the WAV (duration matches script roughly — at 150 wpm, the script should be `script_word_count / 150` minutes; warn if recording is way off).
- Show duration + sample rate.
- Ask: *"Lock this take in, or another go?"*
- Parse:
  - "lock", "approve", "use this one", "this works" → **lock the take**: copy the user's file to `sessions/<id>/audio.wav`, increment `takes_recorded` counter, exit the loop.
  - "another go", "retry", "let me redo it" → loop back, keep `takes_recorded` counter.
  - "stop", "cancel" → set method to `cancelled`, exit with no audio.

**Don't save unapproved takes anywhere.** Per the project convention, only the approved take is kept. The path the user provided stays at its origin until the moment of approval.

## Found-fetch path (found-audio-collage flow)

For Bumblebee-style videos where the narration is *built from found audio* — no recorded VO. This mode runs BEFORE the script: it gathers a pool that the scriptwriter `arranger` mode then arranges into `script.md`, which audio `assemble` later stitches into `audio.wav`. (Part of the `found-audio-collage` flow — see `notes/smart-pipeline-and-found-audio.md`.)

### 1. Build queries from the brief

Pull the theme/arc from `research.json` + `requirements.json`. **Use short keyword queries, not descriptive sentences** — these sources AND their terms, so `"rain on window ambience"` returns nothing while `"rain"` returns thousands. Think 1–3 words: `rain`, `city night`, `lonely sax`, `payphone`, `subway`, `taxi`, plus names of the specific clips/sources you want (e.g. `taxi driver`).

### 2. Fetch the pool

Run in the background for large pools (each source × query downloads files):

```bash
conda run --no-capture-output -n esta python tools/audio/run.py found-fetch \
  --session sessions/<id> \
  --queries "rain" "city night" "lonely sax" "payphone" \
  [--sources freesound,openverse,archive,wikimedia,ccmixter,youtube] \
  [--per-source 4]
```

Sources are auto-selected by `requirements.licensing`: **freesound** (SFX/ambience), **openverse** + **ccmixter** (CC music), **internet archive** (found voices — OTR, PD film, LibriVox spoken word), **wikimedia** (PD speeches), and — only when `licensing: fair_use_ok` — **youtube** (copyrighted dialogue/songs/clips, audio extracted via yt-dlp). Under `free_only`, youtube is skipped automatically.

### 3. Output + handoff

Produces `sessions/<id>/audio_pool/` files + `audio_pool.json` (each clip: `source`, `kind`, `title`, urls, `duration`, `license`, `attribution`, local `file`). YouTube candidates are duration-capped (`MAX_YT_DURATION`, 600s) so a search can't pull a full movie. Show the user a compact summary (counts per source/kind), then run **analyze-pool**, hand to the scriptwriter `arranger`, and come back for **assemble**.

## Analyze-pool mode (found-audio comprehension)

Runs after `found-fetch`, before the arranger. Gives the arranger real content so it can pick clips by what they *say* and cut spoken lines to exact timestamps — instead of guessing from titles. Tiered for speed/cost (borrows the assets pipeline's economy):

1. **Music / SFX / ambience** (`kind`) → skipped (no speech to understand).
2. **YouTube** → captions first via `youtube_transcript_api` (text + timing, no download, no whisper); whisper only if a clip has no captions.
3. **Other speech clips** (archive spoken word, wikimedia) → faster-whisper, model loaded once and only if needed; clips over ~300s skipped.

```bash
conda run --no-capture-output -n esta python tools/audio/run.py analyze-pool \
  --session sessions/<id> [--model small]
```

Enriches `audio_pool.json` in place (`transcript`, `cues`, word-level `words` where whispered, `has_speech`, `understanding`) and writes `audio_pool_analysis.json` (the tracked artifact + a digest of every speech clip). Report the digest to the user — it's the menu the arranger picks from.

## Assemble mode (found-audio)

Runs after the scriptwriter `arranger` has written `arrangement.json`. Stitches the arranged clips into `audio.wav` — same output contract as XTTS/self-record, so `timestamps` and everything downstream are mode-agnostic.

Preflight: requires `arrangement.json` + `audio_pool.json` (downloaded files). Validate the arrangement first: `python tools/scriptwriter/arrange.py validate --session sessions/<id>`.

```bash
conda run --no-capture-output -n esta python tools/audio/run.py assemble \
  --session sessions/<id>
```

Spine clips play sequentially (each starts where the previous ended unless it has an explicit `start`); `bed` clips loop under the whole timeline at their `gain_db`. ffmpeg trims each to its in/out, places it, mixes (sum + safety limiter) → `audio.wav` + `audio_metadata.json` (`method: found_assembled`). Then proceed to `timestamps` (which now runs on this assembled audio — the timeline physics + a caption track of the stitched clips).

## Save + hand off

1. Write `sessions/<session-id>/audio_metadata.json` matching `AudioMetadata` from `tools/audio/schema.py`. Fields:
   - `audio_file`: path to `sessions/<id>/audio.wav` (if produced)
   - `method`: `"indextts2"`, `"xtts"`, `"self_recorded"`, `"placeholder"`, `"cancelled"`, or `"failed"`
   - `line_count`, `guide_lines`: expressive path only — `stitch` writes these itself, don't hand-roll them
   - `duration_seconds`, `duration_minutes`, `channels`, `sample_rate`, `file_size_mb`: from `validate_wav` on the final file
   - `script_word_count`: from `requirements.json` or computed from script.md
   - `voice_sample`: path under `voice_samples/` if XTTS, else null
   - `takes_recorded`: count if self-record, else null
   - `xtts_speed`, `xtts_gpu`, `xtts_load_time_seconds`, `xtts_gen_time_seconds`: from the `generate_xtts` return dict if XTTS, else null
   - `timestamp`: current ISO time
2. **Show a concise summary** in plain language. *"Audio saved. 2m 14s, 22050 Hz, mono. XTTS with the voice_sample_arsenal_2026-05-11.wav clone, generated in 38s on CPU."*
3. **Announce parallel steps + offer the pause:**
   > "On to timestamps next (Whisper word-level alignment) — anything to redo on the audio first?"

   For the **self-record path**: after locking the take, invoke `style-analysis` immediately (it only needs `requirements.json` and benefits from running in parallel with timestamps), then invoke `timestamps`. Both will be running — style-analysis in background, timestamps blocking. When both complete, invoke `plan`.

   For the **XTTS path**: style-analysis was already invoked when XTTS started — it may still be running. After XTTS notification + validate, invoke `timestamps`. When timestamps completes, check if `style_analysis.json` exists. If yes → invoke `plan`. If not → wait for the style-analysis notification before proceeding.

4. **Read the user's reply** per the pipeline rules in `CLAUDE.md` (tweak / redirect / green-light).
   - **Tweak** ("regenerate with a different sample", "let me re-record") → loop back to the relevant mode.
   - **Redirect** ("skip timestamps, jump to assets", "stop here") → respect.
   - **Green light** → proceed as described in step 3.

## Code references

You do NOT need to read these at runtime — apply the rules inline.

- `tools/audio/run.py` — CLI entry point. `xtts`, `validate`, and `found-fetch` subcommands. Always call via `conda run --no-capture-output -n esta python tools/audio/run.py <subcommand> [args]`. Prints JSON.
- `tools/audio/found_fetch.py` — found-audio source searches + downloader + pool builder. Reads `requirements.licensing` to gate copyrighted sources. Search fns mirror `tools/assets/search.py` (return `[]`, never raise).
- `tools/audio/assemble.py` — `assemble(session_dir)`: ffmpeg filter_complex stitch of `arrangement.json` (spine sequential + bed looped) → `audio.wav` (48k stereo) + metadata.
- `tools/audio/analyze_pool.py` — `analyze(session_dir)`: tiered comprehension (skip non-speech → youtube captions → whisper the rest). Enriches `audio_pool.json`, writes `audio_pool_analysis.json`.
- `tools/audio/tagged.py` — markup parser. `script.tagged.md` → `voice_script.json` per-line jobs; `*stress*` → CAPS, `[pause]` splits a line into two units.
- `tools/audio/kaggle_tts.py` — the Kaggle lane for IndexTTS2 + Seed-VC. One kernel per run, one wav per line, `--only` for redos.
- `tools/audio/stitch.py` — joins the per-line wavs, applying pace (ffmpeg `atempo`, pitch-preserving) and pauses locally → `audio.wav` + metadata.
- `tools/audio/xtts.py` — `generate_xtts(...)`. Includes the torch.load patch from notebook cell 12 (do not strip it).
- `tools/audio/validate.py` — `validate_wav(path)` returns `{path, duration, channels, sample_rate, size_mb, warnings}`.
- `tools/audio/schema.py` — `AudioMetadata` TypedDict + `default_audio_metadata(session_id)`.
