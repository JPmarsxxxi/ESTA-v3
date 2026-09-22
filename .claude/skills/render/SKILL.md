---
name: render
description: Assembles the session into <session-id>.openreel.json — the project file the OpenReel web editor loads directly. Deterministic, no LLM. Reads plan.json (shots + timing), assets (downloaded media + in/out points, merged from assets.json + the live assets_progress.jsonl feed), timestamps.json (word-level karaoke subtitles), audio.wav + audio_metadata.json (voiceover), and requirements.json (title). ffprobe supplies real media metadata. Source media is referenced untrimmed (E1) — per-clip inPoint/outPoint carry the trim so cuts stay editable. Can run the moment plan.json exists (timeline structure needs only the plan); assets stream onto the timeline as they download. The final built step in the pipeline today (post is not built yet).
---

# Render Skill

You assemble everything the pipeline produced into a single `<session-id>.openreel.json` that the OpenReel web editor opens directly. Pure assembly — no LLM, no creative decisions. ffprobe reads real width/height/codec/duration off each downloaded file.

## Preflight

1. **Conda env check.** Confirm the `esta` env exists (`conda env list` shows `esta`). If not: *"Run `.\setup.ps1` first."* Stop. (ffprobe ships with the env.)
2. Confirm `sessions/<session-id>/plan.json` exists. If not: *"No plan yet — run the plan skill first."* Stop.
3. Soft checks (warn, don't stop): if no assets exist yet every shot becomes a stream-pending placeholder; if `audio.wav` is missing there's no voiceover track; if `timestamps.json` is missing there are no karaoke subtitles. Render still produces a valid project — just note what's absent.

**Timing model.** The timeline *structure* (which clips, where, how long, which track) comes entirely from `plan.json` — assets are only the media that fills each slot. So render does **not** wait for the assets pass to finish: it can run as soon as `plan.json` exists, in parallel with `assets`. It merges per-shot results from `assets.json` (final) **and** `assets_progress.jsonl` (the live feed the assets skill appends one line per downloaded shot, latest line wins). Shots already downloaded get real media + ffprobe metadata; the rest ship as stream-pending placeholders that the editor hydrates in place as the asset-server SSE feed delivers them. Re-running render later simply picks up more downloaded shots.

**Progressive invocation (standard-vo flow).** Render is designed to be run **twice** in the canonical pipeline so the editor's timeline materializes live:

1. **Early pass** — fired by the plan skill the moment `plan.json` is written. Produces the full timeline shape (shot slots, durations, transitions), real voiceover, and karaoke subtitles. Shots are stream-pending placeholders that the editor's asset-server SSE feed hydrates as the assets background job downloads each one.
2. **Final pass** — fired by the assets skill after the bulk fetch + review + YouTube HD upgrade completes. Produces the same file path, now with every shot pointing at real downloaded media + ffprobe metadata.

The editor's session-file-sync (`apps/studio/src/services/session-file-sync.ts`) polls the project file and auto-loads each new revision when the user hasn't manually edited; if they have, it surfaces a "Load update" banner so they choose whether to merge. Both render passes write the same `<session-id>.openreel.json` — no separate filenames.

## Invocation

```bash
conda run --no-capture-output -n esta python tools/render/run.py build \
  --session sessions/<id>
```

`--no-capture-output` is required (note F1 — conda's cp1252 relay crashes on the unicode in clip names). The command writes `<session-id>.openreel.json` (one file per session, named after the session folder so each project on disk has a recognizable name — e.g. `loneliness-2026-05-26.openreel.json`) and prints a one-line summary: `media_items`, `video_clips`, `placeholders`, `subtitles`, `duration`, `has_audio`.

### Orientation

Default is **vertical short-form, 1080×1920** (the product default; `requirements.json` carries no format field). Override only if the user asks for landscape:

```bash
  --width 1920 --height 1080      # horizontal / YouTube landscape
```

## Delivering to the OpenCut editor (post-render)

The `.openreel.json` is the assembly artifact; the editor the user actually opens is **OpenCut classic** (`C:\Users\User\opencut-classic`, bun, :3000). The chain from a finished render to a playable timeline is deterministic — run these after every render pass whose result the user wants to see:

```bash
# 1. Proxies for oversized sources (one-time per session, idempotent). Three 4K
#    clips decoding at once is what makes the timeline stutter; this downscales
#    anything bigger than the frame into assets/proxies/. Skips files already current.
conda run --no-capture-output -n esta python tools/media/proxy.py generate --session sessions/<id>

# 2. Bridge → OpenCut import, and copy it into the clone in one step. Auto-prefers
#    a proxy when one exists (no manual repoint), builds the caption track from the
#    karaoke word timings, and carries the mute flags. --emit does the copy.
conda run --no-capture-output -n esta python tools/opencut/from_openreel.py --session sessions/<id> \
  --emit "C:/Users/User/opencut-classic/apps/web/public/esta-import.json"
```

#### The export-bound import — `--originals`, automatically

The import above points at proxies, and **OpenCut encodes whatever the timeline
references** — so exporting from it ships a crf-23 `veryfast` downscale as the
finished video. The proxies exist for a smooth timeline, nothing else.

So there are two handoffs, and you pick without asking:

- **Reviewing / editing** → the command above (proxies, smooth scrubbing).
- **About to export** — the user says "export", "final", "render it out",
  "publish", or asks for the finished file → re-emit with `--originals` first,
  then tell them in one line: *"Re-imported off the original sources — reload
  /esta-seed before exporting."*

```bash
conda run --no-capture-output -n esta python tools/opencut/from_openreel.py --session sessions/<id> \
  --originals --emit "C:/Users/User/opencut-classic/apps/web/public/esta-import.json"
```

The command prints `"proxies": true|false` — check it, because a `true` on an
export-bound import means the final video is about to be made from proxies.
Re-seeding is required after re-emitting: the editor reads the import at seed
time, so an export from an already-open tab still uses the old media.

OpenCut's export quality default is `very_high` (mediabunny factor 4 ≈ 12 Mbps
target at 1080×1920, vs `high`'s 6). That lives in the clone
(`apps/web/src/export/defaults.ts`), not this repo — reapply it after a re-clone.

Then the user (or you, via Chrome) loads `http://localhost:3000/esta-seed`, which seeds IndexedDB and opens `/editor/<id>`. The **asset-server must be running** (`node tools/asset-server.mjs` — run it directly, not via pnpm; it orphans the child). Re-seeding replaces the project; clear stale media by wiping the `video-editor-media-*` IndexedDB **and** OPFS if a file changed size (e.g. after tightening the audio) — deleting IndexedDB alone leaves the old blob in OPFS.

### SFX from the plan (optional, before the mix)

The plan carries per-shot SFX suggestions in `audio_layer.sfx` (e.g. shot 8 → `["engine rev"]`) — the plan skill's creative call about *what sound on which beat*. This bridge fulfils them: fetches each named sound from Freesound (relevance-ranked, short-only), places it at the shot's start, and writes `sfx.json`.

```bash
conda run --no-capture-output -n esta python tools/audio/sfx_from_plan.py --session sessions/<id>
```

It's a strong first pass, not final: the plan says *what*, Freesound picks the *file*, and the pick can miss. Levels are placeholders — the mix pass below sets them. `sfx.json` is regenerated from the plan on each run, so hand-tune it (word-level placement, swapping a file) **after** this, and it's read as-is from then on. **SFX placement is the one creative step that isn't fully automated** — this gets you a plausible layer to refine, not a finished mix.

### Audio polish (before the OpenCut delivery, once per session)

Two deterministic passes belong on the audio *before* the final render, both idempotent and safe to re-run (each preserves the prior take):

```bash
# Tighten dead air. Cuts inter-word gaps (mid-sentence cap 0.35s, sentence-end
# 0.5s so comprehension beats survive), re-times timestamps.json analytically,
# then re-reconciles plan.json. Preserves audio.original.wav.
conda run --no-capture-output -n esta python tools/audio/tighten.py --session sessions/<id>
# (re-reconcile after: reconcile(session_dir, force=True) — the plan is already
#  marked reconciled against the pre-tighten timing.)

# Loudness mix (sound-design §1). Normalises the voice to -14 LUFS with true-peak
# limiting, and levels every sfx.json cue a fixed LU under it — MEASURED per file,
# not guessed, because sources vary 25dB+. --bake is REQUIRED: OpenCut's preview
# ignores per-element volume, so the attenuation must live in the sample. Preserves
# audio.premix.wav.
conda run --no-capture-output -n esta python tools/audio/mix.py --session sessions/<id> --bake
```

Order matters: **tighten → mix → render → proxy → bridge**. Tightening changes duration (everything downstream re-times off it); mix normalises levels; render assembles; proxy+bridge deliver. If there's an `sfx.json`, mix must run after it's written and before the final render.

## What it assembles

- **Media library** — one item per shot plus the voiceover. ffprobe fills real metadata for downloaded files; gap shots (no asset) get the project dimensions as a fallback.
- **Three video tracks** — Main (V1: REAL_FOOTAGE/REAL_IMAGE shots), Overlay (V2: empty, reserved for the user), Graphics (V3: MOTION_GRAPHICS shots + generated overlay clips). Higher tracks render on top. All muted, so clip audio never fights the voiceover. `fx: ["slow_motion"]` shots get `speed: 0.5`.
- **Per-shot `overlay` blocks** — when a plan shot carries an `overlay` and the motion-graphics skill has rendered its transparent WebM (keyed `<n>-overlay` in the assets feed), render emits a second clip on Graphics for the shot's window — the card floats over the footage. No file yet ⇒ no clip, no placeholder; the next render pass picks it up.
- **Three audio tracks** — Voice / Music / Ambience, stemmed by role for found-audio sessions; standard-VO sessions put `audio.wav` on Voice at t=0.
- **Subtitles** — karaoke style, word-level timing from `timestamps.json` (per-word highlight). None if timestamps haven't run.
- **Trim as metadata (E1)** — sources are referenced untrimmed; each clip's `inPoint`/`outPoint` come from `assets.json`. The editor can extend a cut past the originally-detected moment because every frame is on disk.

### Placeholders

Every media item ships `isPlaceholder: true` — that is the editor's hydration contract, not a defect. On import the editor runs `hydratePlaceholders()`, which fetches each item's `originalUrl` from the asset server and loads the real blob, then flips the item to `isPlaceholder: false`. Items with a URL (fetched shots + voiceover) hydrate; gap shots (no URL) stay flagged and render the yellow "Missing" badge so the user knows to fill them. **Do not set fetched items to `isPlaceholder: false`** — the hydrator skips those and the asset never loads.

## Output

- `sessions/<id>/<session-id>.openreel.json` — `{ version: "1.0.0", project: {...} }`, matching the `@openreel/core` `Project` schema (`packages/core/src/types/{project,timeline}.ts`).

## Hand-off to the editor

The project loads in the OpenReel web app (`pnpm dev`). For assets to hydrate, the dev asset-server must be running (`pnpm asset-server`, port 8787) — it serves `sessions/` under `/api/sessions`, which is where every `originalUrl` points. Two load paths:

- **In-app chat** (this very pipeline driven from the editor's Chat tab via `tools/chat-bridge.mjs`): tell the user the render is done and to load it.
- **Sessions list in Recent Projects**: the welcome screen lists every session that contains a `*.openreel.json`; click → it loads via `loadProject()` and the asset-stream SSE re-subscribes.
- **Manual import**: the Project JSON dialog imports `<session-id>.openreel.json`; placeholders hydrate in the background.

Announce concisely — duration, shot count, how many shots are still "Missing" placeholders the user may want to fill (re-run the assets skill per-shot for those), and that subtitles/voiceover are in.

## MVP scope — deferred follow-ups

Tracked, intentional gaps (not bugs):

- **Format presets** — only `--width/--height` today; named presets (tiktok/shorts/youtube/square) are not wired.
- **Transitions** — all hard cuts. The plan's `transition` field is not yet mapped to crossfade/zoom.
- **Per-shot caption overlays** — captions come from the timestamps karaoke track; the plan's per-shot `text.caption` overlays aren't emitted.
- **Other `fx`** — only `slow_motion` maps (to `speed`); other effects are deferred.
- **GIF** — rides as media `type: image` (the editor decodes animated GIFs).

## Next step

`post` (captions polish / thumbnail / description / upload) is not built yet — render is the final built step in the pipeline today.

## Code references

- `tools/render/run.py` — CLI, `build` subcommand. Always call via `conda run --no-capture-output -n esta`.
- `packages/core/src/types/project.ts`, `.../timeline.ts` — the schema this output must satisfy.
- `apps/web/src/services/hydrate-placeholders.ts` — the editor's import-time blob loader; the `isPlaceholder` contract above lives here.
- `tools/asset-server.mjs` — dev server mounting `sessions/` at `/api/sessions`.

> **Note — supersedes `packages/esta-bridge`.** That TypeScript package (`sessionToProject`) was the earlier prototype of this assembler. It is orphaned (no importers) and lacks real ffprobe metadata + E1 in/out points. This Python tool is the canonical render path.
