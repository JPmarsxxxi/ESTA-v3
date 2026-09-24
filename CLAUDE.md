# ESTA-v3

ESTA-v2's AI video factory (topic -> script -> voiceover -> plan -> assets -> edited video) as one local web app: an OpenCut-based editor with Premiere-style stage workspaces, where the UI enforces the pipeline order. Functionality is an exact copy of `C:\Users\User\ESTA-v2`; `SPEC.md` is the build spec and `PORTING.md` logs every deviation from v2 and every OpenCut mount point.

## Tech stack & commands

- Frontend: `apps/editor/`, a vendored fork of OpenCut classic (Next.js 16, React 19, bun). ESTA code lives in `apps/editor/src/esta/`.
- Backend: `server/`, one Node 24 process (TypeScript run by native type stripping) on :8787. Replaces v2's `asset-server.mjs` + `chat-bridge.mjs` with the same routes.
- Pipeline: `tools/` (Python, the `esta` conda env) and `.claude/skills/`, copied verbatim from v2.
- Install: `bun install` (the `esta` env is reused; run `.\setup.ps1` only if it's missing)
- Run: `bun run dev`, then open http://localhost:3000 (starts backend and editor; the backend restarts on edits under `server/`)
- Backend only: `bun run server`
- Typecheck: `bun run typecheck` (editor + server)
- Lint: `bun run lint` (ESTA frontend code + server). `bun run lint:all` also lints the vendored OpenCut code, which carries upstream's own baseline errors.
- Test: `bun test` in `apps/editor` runs OpenCut's unit tests (its timeline tests fail upstream too: wasm doesn't initialise under bun). Pipeline state is checked against `python tools/pipeline/conductor.py next --session sessions/<id>`.

## Code style

- Lean, precise, concise code. No unnecessary abstractions — three similar lines beats a premature helper.
- No emojis, in code, comments, or commit messages.
- No comments explaining WHAT code does. Only comment a non-obvious WHY (a workaround, a hidden constraint).

## Workflow contract

- For anything beyond a small fix: write or update `SPEC.md` via `/spec` before implementation starts. Don't start coding a nontrivial feature from a bare prompt.
- Before calling a feature/task done, run `/verify` against `SPEC.md`.
- List the steps you're about to take before writing code on anything nontrivial.
- Build in parts with a checkpoint between them where useful — don't silently produce one giant diff for a multi-part change.
- Never commit to `main`/`master` unless explicitly told to. Confirm the current branch before committing; if on main/master, stop and ask.
- Never force-push, rebase, or run other history-rewriting git commands without asking first.

## Project-specific rules

- `tools/` and `.claude/skills/` are verbatim v2 copies. Change them only for integration fixes, and log each in `PORTING.md` with the reason.
- v2's servers are gone. Where a skill says to run `node tools/asset-server.mjs` or `tools/chat-bridge.mjs`, the v3 backend (`bun run dev`) already serves the same routes on :8787. Where a skill points the user at `localhost:8787/_plan?session=<id>` or `/_picker?session=<id>`, point them at the session's workspace instead: `http://localhost:3000/esta/<id>`.
- Where the render skill emits `esta-import.json` into the OpenCut clone and loads `/esta-seed`, use the Edit stage's **Build project** instead, and **Build for export** where it says `--originals`. Both build the native OpenCut project `esta-<id>` from `<id>.openreel.json`.
- Approvals and overrides live under the `ui` key of `pipeline.json`. `conductor.py` round-trips unknown keys, so its commands keep working.
- OpenCut code outside `src/esta/` is upstream: keep edits there minimal and list each one in `PORTING.md`.

## Pipeline (from ESTA-v2)

### Skills

| Skill | Purpose |
|---|---|
| `requirements` | Conversational intake — topic, style, duration, comments, examples, script-source choice, licensing stance |
| `conductor` | Picks a flow template (`standard-vo` / `found-audio-collage`), adapts it within guardrails, writes + validates a per-session `pipeline.json`, and answers "what runs next?". Runs after requirements. Additive — no `pipeline.json` ⇒ canonical-order fallback. |
| `voice-profiler` | Extracts the user's writing techniques from their `example_scripts` and saves a named technique list to `voice_profile.md`. Auto-runs after requirements when examples are provided. Consumed by scriptwriter and humanizer for technique-level voice matching (not surface pastiche). |
| `research` | Web research → `research.json` (broad context + claim verification). Replaces notebook cells 5, 19, 20 with Claude-native `WebSearch`/`WebFetch`. Append-only: re-invoke any time to deepen. |
| `scriptwriter` | Two-pass scripting — talking points → full script in `[HOOK]/[BODY]/[CTA]` form. Plans technique application from `voice_profile.md` BEFORE drafting. Auto-invokes the humanizer on the draft, then user pastes back the finalized version (which is what gets saved as `script.md`). |
| `humanizer` | Text-in, text-out. Three-stage scan → rewrite → audit. Removes AI tells AND injects user voice techniques from `voice_profile.md` where the draft is missing them. Auto-invoked by generative skills; also user-invocable on any text. |
| `audio` | Voiceover production. Default is the **expressive clone**: Claude tags `script.md` with per-line emotion, `*stress*`, `[pause]` and pace into `script.tagged.md`, the user approves it, then IndexTTS2 voices each line on **Kaggle's free T4** (local GPU is 4 GB) and lines the user acted out themselves are converted by Seed-VC. One wav per line, so a bad line is redone with `--only L04` instead of regenerating the lot. Other modes: legacy XTTS (CPML is non-commercial — never accept it for the user), self-record with multi-take loop, found-fetch collage. Writes `audio.wav` + `audio_metadata.json`. Runs in background; assets starts in parallel. |
| `timestamps` | Word-level audio alignment via faster-whisper. Reads `audio.wav`, streams segments to `timestamps_progress.jsonl` as they arrive, writes final `timestamps.json`. Feeds plan and render with frame-accurate timing. |
| `style-analysis` | Downloads YouTube reference clips matching the video style. Phase 1 runs Python (OpenCV + CLIP + Whisper) in background to extract frames and audio. Phase 2 Claude reads frames + transcripts in-conversation and synthesises `style_analysis.json`. Runs in parallel with audio — only needs `requirements.json`. |
| `plan` | BrainBox — shot-by-shot video plan. Pure skill (Claude does shot generation in-conversation, no API key). Reads `style_analysis.json` + `script.md`, estimates timing at 150 wpm. Produces `plan.json` with `timing_source: "estimated"`; real timing is reconciled automatically by the timestamps skill when `timestamps.json` arrives. Two modes: `bulk` (default — full shot list streamed immediately) and `manual` (hands-on — each shot card shown for user approval; approval releases it to the assets fetch while the next card is presented, so approving and fetching overlap). |
| `assets` | Parallel asset search + download across Pexels, Pixabay, Giphy, Wikimedia, Archive.org, YouTube. Reads `plan.json`, fills each shot with a downloaded file. Produces `assets/` folder + `assets.json`. |
| `motion-graphics` | Generates motion graphics with HyperFrames (HTML/CSS/GSAP → deterministic video; Node + cached headless Chrome, no conda). Full-frame MP4s replace the stock pick for `MOTION_GRAPHICS` shots; transparent VP9 WebMs render `overlay` blocks that float over footage on the Graphics track. Streams results into `assets_progress.jsonl` (full-frame overwrites shot key, overlays under `<n>-overlay`); stock stays as per-slot fallback. Runs alongside the assets fetch. Writes `motion_graphics.json`. |
| `ai-video` | Generative AI B-roll with Higgsfield-style camera moves (crash zoom, orbit, FPV drone, 2.5D parallax) on **Kaggle's free GPU** — 30 GPU-hrs/week, 12-hour detached runs, and a real API (`kernels push/status/output`), so it's a headless background job rather than a browser-driven one. Fills shots typed `AI_VIDEO` or carrying a `generate` block. `--seed-from-assets` turns text-to-video into image-to-video by seeding from the frame already fetched for that shot. Streams into `assets_progress.jsonl` like motion-graphics; stock stays as the per-slot fallback. Writes `gen_video.json`. |
| `render` | Deterministic assembler (no LLM). Reads `plan.json` + `assets.json` + `timestamps.json` + `audio.wav`/`audio_metadata.json` + `requirements.json` and emits `<session-id>.openreel.json` — the project the OpenReel web editor loads directly. ffprobe supplies real media metadata; trim lives as per-clip `inPoint`/`outPoint` (E1). Runs **twice** in the canonical flow: early pass after plan (placeholders + voiceover + subs, editor's SSE hydrates shots as they download), final pass after assets (real media everywhere). |

Skills planned next: `post`, `profile-update`.

### Pipeline rules

Skills form a flowing pipeline, not a menu. The canonical order is:

**requirements → voice-profiler (if example_scripts is a list) → research → scriptwriter → [audio + style-analysis] (parallel, background) → [timestamps + plan] (timestamps streams, plan polls) → render (early pass — placeholders + voiceover + subs) → [assets + motion-graphics] (parallel — stock fetch in background, generation in-conversation) → render (final pass — real media + generated graphics) → post**

Render fires **twice** in the canonical flow so the editor's timeline materializes live: an early pass right after `plan.json` is written (full timeline shape + voiceover + karaoke subs, shots as stream-pending placeholders), and a final pass after `assets.json` is written (placeholders replaced with real media + ffprobe metadata). Both passes write the same `<session-id>.openreel.json`; the editor's session-file-sync auto-loads each revision (silently if no local edits, banner-with-choice if there are).

`voice-profiler` is conditional: it only runs when `requirements.example_scripts` is a non-empty list. If `example_scripts` is the sentinel `"ASSET_COLLECTOR_PLACEHOLDER"`, the pipeline skips voice-profiler and goes straight from requirements to research. If the user drops a sample mid-flow during scriptwriter or humanizer, those skills re-invoke voice-profiler before continuing.

### Orchestration — the conductor

The order above is the **`standard-vo` template**. After `requirements`, the `conductor` skill picks a flow template (e.g. `standard-vo`, or `found-audio-collage` for Bumblebee-style found-audio videos), adapts it within guardrails, and writes a per-session `pipeline.json`. From then on, **sequencing is owned by `pipeline.json`, not by individual skills**: ask `python tools/pipeline/conductor.py next --session sessions/<id>` for the next step rather than relying on a skill to name its successor. A step is "done" when its outputs exist on disk, so progress is self-tracking. Any custom order must validate against `tools/pipeline/contracts.json` (`validate_flow.py`) — a step may only run when the artifacts it `needs` have been produced upstream.

**Fallback:** if a session has no `pipeline.json`, follow the canonical order above exactly as before. The conductor is additive — the per-skill "on to X next" handoff notes are the `standard-vo` fallback, overridden by `pipeline.json` when it exists.

### Conda environment

Python-invoking skills use the `esta` conda env via `conda run -n esta python tools/<skill>/run.py` — the env never needs to be manually activated. Locked versions: `TTS==0.22.0`, `transformers==4.33.3`, `torch==2.6.0`, `faster-whisper==1.2.1`, `numpy==1.26.4`. The Kaggle-lane commands (`genvideo`, `genchar`, audio's `expressive`) are the exception to `conda run`: they run on the **system** python, which is where the `kaggle` CLI lives — the copy inside `esta` has no `-m kaggle` entry point. Run `.\setup.ps1` once to create the env.

Every Python-heavy SKILL.md must check that the `esta` env **exists** (not active) in its preflight: `conda env list | grep esta`. If missing, tell the user to run `.\setup.ps1` and stop.

Skills that don't invoke Python (`requirements`, `voice-profiler`, `research`, `scriptwriter`, `humanizer`) need no env check — they work in any session.

### Background steps

Long-running Python tasks (XTTS audio generation, faster-whisper transcription) run via Bash with `run_in_background: true`. The skill announces the background job, then immediately continues with the next parallelisable step. When the background task completes Claude is notified and resumes.

**Parallelism map for the pipeline:**

| Background task | Fires in parallel |
|---|---|
| XTTS audio generation (~5-15 min) | `style-analysis` skill (needs only requirements.json — starts the moment XTTS fires) |
| Self-record path: style-analysis fires after take is locked | `timestamps` (blocking, runs after audio) |
| faster-whisper transcription (~3-5 min) | nothing blocks — after transcription, `reconcile` updates plan.json timing automatically |

**Chain rule:** after timestamps finishes, invoke `plan`. Plan requires `style_analysis.json` — if style-analysis is still running, wait for its notification before invoking plan.

Every Python-heavy skill that could take >1 min MUST use `run_in_background: true` and document what runs alongside it in its SKILL.md.

After each skill saves its output, do three things in one turn:

1. **Show the artifact concisely** — not raw JSON, just the key fields in plain language.
2. **Announce the next step and offer a pause** — one short line, not a question with options. Example: *"Going to research it next — anything to tweak first?"*
3. **Read the user's reply as one of three things:**
   - **Tweak** ("change X to Y", "actually make it Z") → edit the saved JSON in place with the Edit tool, re-show the updated artifact, re-announce.
   - **Redirect** ("skip to assets", "stop here, I'll come back", "do research but don't move past it") → respect it. Stop the pipeline, or jump to a different skill, as the user directs.
   - **Green light** (silence, "ok", "go", "do it", or any non-objection) → invoke the next skill.

The user never has to manually open a JSON file. If they want to change something they've already answered, they say so in chat and you rewrite the file. The pipeline can also be paused, skipped, or rewound from any point with natural language. Skip skills explicitly disabled by earlier steps (e.g., `scriptwriter` when `skip_scriptwriter: true`).

### Session folder convention

Every project lives in `sessions/<session-id>/`, where `<session-id>` is `<topic-slug>-<YYYY-MM-DD>`. Each skill reads what it needs and writes its output to this folder. A skill is "done" when its output file exists — and can be skipped on re-run if the file is already there.

| File | Produced by | Consumed by |
|---|---|---|
| `requirements.json` | `requirements` | every later skill |
| `pipeline.json` | `conductor` | the orchestrator (`conductor.py next`) — owns step sequencing |
| `conversation.jsonl` | every conversational skill | future `profile-update` skill |
| `script_uploaded.txt` | `requirements` (only when user uploads) | scriptwriter skips if present |
| `voice_profile.md` | `voice-profiler` | scriptwriter, humanizer, future generative skills |
| `research.json` | `research` | scriptwriter, brainbox |
| `script.md`, `script_metadata.json` | `scriptwriter` | audio, brainbox |
| `audio_pool.json`, `audio_pool/` | `audio` (found-fetch mode) | scriptwriter (arranger), audio (assemble) |
| `arrangement.json` | `scriptwriter` (arranger mode) | audio (assemble mode) |
| `script.tagged.md` | `audio` (expressive path, user-approved) | `audio` — parsed into `voice_script.json` |
| `voice_script.json`, `voice_build/lines/line_<id>.wav` | `audio` (tag-check + expressive) | `audio` stitch; per-line redos |
| `audio.wav`, `audio_metadata.json` | `audio` | `timestamps` |
| `timestamps_progress.jsonl` | `timestamps` (live, grows per segment) | `plan` (polls while transcribing) |
| `timestamps.json` | `timestamps` (final, written on completion) | `plan`, `render` |
| `style_analysis.json`, `style_examples/` | `style-analysis` | `plan` |
| `plan.json` | `plan` | `assets` |
| `assets.json`, `assets/` | `assets` | `render` |
| `gen_video.json`, `gen_video_kernel.json` | `ai-video` | conductor done-marker; generated clips land in `assets/source_pool/` and flow to `render` via `assets_progress.jsonl` |
| `motion_graphics.json`, `assets/mg/` | `motion-graphics` | conductor done-marker; rendered files land in `assets/source_pool/` and flow to `render` via `assets_progress.jsonl` |
| `<session-id>.openreel.json` | `render` | OpenReel web editor (loaded via the Sessions list or Project JSON dialog; live edits auto-write back to this file via the asset-server PUT) |

Plus a repo-level `voice_samples/` folder (not per-session) that stores reusable WAV files for the XTTS clone path. Voice samples are user property — same person across many video projects — so they live above the session folders.

### User profile

`profile/preferences.md` (created over time) holds Claude's running notes on this user's tone, recurring style choices, and phrases they use. Every conversational skill reads it before opening. It gets updated by a future `profile-update` skill that distills patterns from `sessions/*/conversation.jsonl`. You can also drop notes there manually — see `profile/README.md`.

### LLM provider

Configured in `config.yaml`. Default is `claude`, meaning Claude (this harness) generates content in-conversation — no API key, no Python LLM client. Other providers (`gemini`, `openai`) route through `tools/llm/router.py` (not built yet — will arrive with the scriptwriter skill).
