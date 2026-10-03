# ESTA-v3 SPEC

Source of truth for functionality: `C:\Users\User\ESTA-v2` (read its `CLAUDE.md` first). v3 changes the packaging, not the behavior.

## Goal

ESTA-v3 is ESTA-v2's AI video factory (topic -> script -> voiceover -> plan -> assets -> edited video) rebuilt as **one local web app with an Adobe-style editor**. Every pipeline stage, every browser surface and the timeline editor live in a single window. The flow order is enforced by the UI instead of by chat discipline, so edits are fast and stages can't be run out of order by accident.

Concretely:
- **Shell:** a fork of OpenCut classic (Next.js, bun, Rust/wasm) vendored into this repo. It is the only frontend.
- **Pipeline:** v2's `tools/`, `.claude/skills/`, conductor and contracts, copied verbatim and driven by a single Node backend.
- **AI:** both explicit per-stage action buttons (scoped headless `claude -p` jobs) and a docked chat panel backed by a real headless Claude Code session. That session loads the same skills and the OpenCut live-edit MCP tools.
- **Layout:** Premiere-style **stage workspaces**. A persistent stage rail sits on the side, and each stage has a preset arrangement of dockable panels.

## Non-goals / out of scope

- Cloud hosting, auth, multi-user, deploy targets (Cloudflare functions, wrangler). Local single user only.
- Mobile or small-screen support. Desktop Chrome only.
- New pipeline capabilities beyond v2 in M1–M4. `post` and `profile-update` stay unbuilt. (Part 2, M5, is a user-requested exception: inspo matching.)
- Rewriting or improving the Python tools. `tools/` is copied verbatim; the only allowed changes are integration fixes (paths, progress output), each listed in `PORTING.md` with the reason.
- Keeping OpenReel as an editor. Its features are ported into the OpenCut-based editor (M4). The OpenReel engine itself and its custom agent layer (`bridges/` + `ChatPanel` as an agent) are not carried over.
- Changing `render/run.py` output. It still writes `<session-id>.openreel.json`.
- Sharing a sessions folder with v2 (v3 has its own; see Sessions).

## Files & interfaces involved

### Copied verbatim from v2 (in M1)
| v2 path | v3 path | Notes |
|---|---|---|
| `tools/**` (except `planner/`, `picker/` HTML, `asset-server.mjs`, `chat-bridge.mjs`) | `tools/**` | Python CLIs, conductor, contracts, templates, Kaggle lane, MG builder, MCP server |
| `.claude/skills/**` | `.claude/skills/**` | All 14 ESTA skills. Merge with the StyleSeed/humanizer skills already in v3 `.claude/skills/`; v2's `humanizer` wins on conflict |
| `.mcp.json` | `.mcp.json` | `esta-opencut` server path updated if moved |
| `CLAUDE.md` pipeline rules, `editing-principles.md`, `motion-design.md`, `sound-design.md` | same names | Referenced by skills. Merge v2's CLAUDE.md content into v3's |
| `config.example.yaml`, `environment.yml`, `setup.ps1`, `requirements.txt` | same | The `esta` conda env is reused, not recreated |
| `voice_samples/`, `characters/`, `profile/` | same | User property, copied once |
| `notebook/Untitled.ipynb` | same | Read-only ground truth for prompts and constants |

Not copied: `node_modules`, `sessions/` (imported on demand), `yolov8m.pt` and caches (referenced by path or re-downloaded), `r.out`, `experiments/`.

### New in v3
- `apps/editor/`: the vendored OpenCut classic fork (from `C:\Users\User\opencut-classic`, upstream `github.com/opencut-app/opencut-classic`). ESTA code lives under `apps/editor/src/esta/` where possible, plus a small number of mount points in OpenCut files; each mount point is listed in `PORTING.md`.
- `server/`: one Node backend (replaces `asset-server.mjs` + `chat-bridge.mjs`) on a single port. It must preserve every v2 route's behavior:
  - Media: `/api/sessions/<id>/...` static session files, with CORS and range requests.
  - Sessions: `/_sessions/list`, `/_sessions/create`, plus new `/_sessions/import` (copy a session from v2).
  - Planner: `/_plan/api/plan`, `/_plan/api/shot`, `/_plan/api/rewrite`, `/_plan/api/command`.
  - Picker: `/_picker/api/shots|candidates|pick|refetch|sources|jobs`.
  - Live edit: `/_cmd_stream` (SSE), `/_cmd`, `/_state`, `/_ack`, `/_frame`.
  - Chat: `/chat/stream`, `/chat/send`, `/chat/stop`, `/chat/health`.
  - New: `/_pipeline/:id` (state + gates, see below), `/_jobs` (list, SSE log/progress stream, cancel, retry), `/_files/:id` (SSE file-change events for the session folder).
- `tools/opencut/emit.py` (or an equivalent TS module in `apps/editor/src/esta/`): **new emitter** that turns `<id>.openreel.json` into a native OpenCut project, replacing the `esta-import.json` + `/esta-seed` spike. `from_openreel.py` stays for reference. It keeps the proxy-vs-originals rule: editing uses proxies (`tools/media/proxy.py`), and export must reference originals.
- `PORTING.md`: log of every deviation from verbatim copy and every OpenCut mount point.
- `PARITY.md`: feature matrix (see M4) mapping each v2 feature to its v3 location and status.

## Key decisions & tradeoffs

1. **Local web app, OpenCut fork as the shell.** OpenCut's engine played back smoothly where OpenReel lagged (v2 spike, `notes/opencut-mcp-build.md`). One origin, one store, no iframes. Cost: we own a fork; confining ESTA code to `src/esta/` keeps upstream merges possible.
2. **Python pipeline copied verbatim and wrapped.** This guarantees v2 behavior (prompts, 150 wpm, 12 s hook/CTA, validators). The backend shells out to the same CLIs using v2's conventions (`conda run -n esta python tools/...`, system python for the Kaggle lanes `genvideo`, `genchar`, audio `expressive`).
3. **AI = buttons + chat, both backed by the real `claude` CLI.** No custom in-app agent layer; v2 learned that it made chat worse than the CLI. Buttons run scoped `claude -p` jobs (as v2's planner Rewrite/command do: Haiku, lean prompt, cost shown in the UI, never automatic). The chat panel is a persistent headless stream-json Claude Code session in the v3 repo with the ESTA skills and the `esta-opencut` MCP server (`get_timeline`, `get_frame`, `update_clip`, `animate_clip`, `set_clip_duration`), so chat can edit the timeline live. The terminal Claude Code in this repo must work identically.
4. **Gates with override.** Each stage's actions are locked until its `contracts.json` `needs` exist on disk **and** upstream human checkpoints are approved. The lock shows the reason (e.g. "needs timestamps.json"). An explicit **Force / Skip** action unlocks it and records the override in `pipeline.json`. This mirrors v2's ability to redirect ("skip to assets").
5. **Approval model.** Stages with a v2 human checkpoint need an explicit **Approve** click, recorded in `pipeline.json`: requirements, script finalize (the user-finalized `script.md`), tagged-script approval (`script.tagged.md`), plan. All other stages count as done when their outputs exist, exactly like `conductor.py`. Sessions with no `pipeline.json` fall back to v2's canonical order.
6. **Stage workspaces.** Stage rail: Requirements, Voice profile, Research, Script, Voice (audio), Timestamps, Style, Plan, Assets (picker + MG + AI video), Edit. Each stage has a saved preset of dockable panels (e.g. Script = script editor + research + chat; Plan = plan editor + preview + timeline; Edit = OpenCut full layout + chat + jobs). Users can rearrange panels within a workspace; layouts persist per user.
7. **Planner and picker rebuilt as React panels** with the same fields, actions and endpoints as v2's `tools/planner/index.html` and `tools/picker/index.html`. Selection is shared with the timeline (selecting shot N in the planner selects it on the timeline and vice versa).
8. **Render path: add an emitter, don't touch render.** `render/run.py` stays verbatim (two passes: early placeholders + VO + subs, final real media). The new emitter builds the native OpenCut project from its output, and the editor refreshes live when it changes.
9. **Sessions: v3's own `sessions/`**, same folder convention (`<topic-slug>-<YYYY-MM-DD>`, same file names). "Import from v2" copies a session folder from `C:\Users\User\ESTA-v2\sessions`.
10. **Concurrency via file-watch.** The backend watches the open session folder and pushes changes. If the UI has no unsaved local edits to the affected artifact, it reloads silently; otherwise it shows a banner with **Keep mine / Take theirs**. This covers the terminal, chat and background jobs writing files.
11. **Jobs panel + stage badges.** Every long job (Kaggle TTS, whisper, style-analysis, asset fetch, MG render, ai-video, render) runs in the background and shows up in a dockable Jobs panel with live log, progress (from `*_progress.jsonl` where available), cancel and retry. Stage rail badges show idle / running / failed / done / overridden. Parallel steps run in parallel as in v2's parallelism map.

## Milestones (build in order, checkpoint between each)

- **M1 Shell + pipeline:** vendor OpenCut, copy the v2 files, backend with all v2 routes, stage rail + gates + approvals + overrides, session list/create/import, jobs panel, chat panel (without MCP), stage buttons that run the skills/tools.
- **M2 Surfaces:** planner and picker React panels, script/line editor (port of v2 `WritingStageView` + `LineEditor`), requirements form, tagged-script review.
- **M3 Editor integration:** native emitter, live refresh on render, MCP live-edit via the chat panel, shared shot selection, file-watch + conflict banner, export with originals.
- **M4 OpenReel parity:** write `PARITY.md` first, listing every feature in v2 `apps/studio` (inspector sections under `components/editor/inspector/`, `audio-mixer/`, bridges such as beat-sync, silence-cut, motion tracking, audio-text-sync, auto-caption, TTS panel, templates, share page, screen recorder, keyframe editor, scopes, etc.). Mark each as "OpenCut native", "port" or "dropped (reason, user-approved)". Then port everything marked "port".

## Edge cases

- `esta` conda env missing: preflight shows a blocking notice ("run `.\setup.ps1`") on Python stages, the same check as v2 skills (`conda env list`). Non-Python stages still work.
- `kaggle` CLI missing, or Kaggle quota exhausted: the job fails with the tool's error surfaced in the Jobs panel and retry is available. There is no silent fallback to legacy XTTS (non-commercial license; never auto-selected).
- `voice-profiler` is skipped when `example_scripts` is the `ASSET_COLLECTOR_PLACEHOLDER` sentinel. It re-runs if samples are added mid-flow.
- `skip_scriptwriter: true` (uploaded script): the Script stage shows as skipped, not blocked.
- Both flow templates (`standard-vo`, `found-audio-collage`) work, including the found-audio inversion (script depends on the audio pool). Custom orders must pass `validate_flow.py`; invalid ones are rejected with its message.
- Plan is invoked while style-analysis is still running: gated, with the reason shown. It unlocks when `style_analysis.json` appears.
- `timing_source: "estimated"` plan reconciled when `timestamps.json` arrives: the UI updates live.
- Early render pass: the timeline shows placeholders that hydrate as assets stream in (`assets_progress.jsonl`), including `<n>-overlay` MG entries.
- Crossfade A/B split: "shot N" resolves by flattening `main` + tracks whose names start with `Main`, sorted by start time (v2 gotcha).
- Export while the timeline references proxies: export must reference originals, or it is blocked with a clear message.
- Browser ~6-connections-per-host limit: all SSE streams (cmd, jobs, files, chat) must be multiplexed so that opening every panel does not starve requests. One shared SSE channel per tab is acceptable.
- Backend restart mid-job: on restart, jobs whose processes died show as failed/interrupted (not running forever). Stage state is recomputed from disk.
- Pipeline override recorded, then the missing input appears later: the badge changes from overridden to done.
- Conflicting external write while the user is editing the same artifact: a banner, never a silent overwrite either way.
- Importing a v2 session that already exists in v3: prompt to overwrite or rename, never merge silently.
- The chat session dies (claude process exits): the panel shows it disconnected and offers restart; the UI keeps working.

## Acceptance criteria

M1
- [x] `bun install` then one documented command starts the editor and backend. Opening `http://localhost:3000` shows the session list. Both commands are recorded in CLAUDE.md "Tech stack & commands".
- [x] `diff -r` of v2 `tools/` vs v3 `tools/` shows only the excluded files and the changes listed in `PORTING.md`.
- [x] Every v2 skill is present in `.claude/skills/`, and `/requirements`, `/plan` etc. are invocable from terminal Claude Code in the v3 repo.
- [x] Creating a session from the UI writes `sessions/<slug>-<date>/requirements.json` with the same fields as v2's requirements skill.
- [x] "Import from v2" copies `do-alphas-even-exist-2026-09-16` in, and its stage rail state matches `python tools/pipeline/conductor.py next --session sessions/<id>`.
- [x] A stage whose `needs` are missing is locked and shows the missing file names. Force unlocks it and writes the override into `pipeline.json`.
- [x] Approve on requirements/script/tagged-script/plan is required before the next stage unlocks, and is persisted in `pipeline.json`.
- [x] Starting timestamps shows a running job in the Jobs panel with a live log; cancel kills the process; retry restarts it.
- [x] The chat panel can run "what runs next?" and gets the same answer as the conductor CLI.

M2
- [x] Every field and action in v2's planner (including Rewrite and the structural commands split/merge/add overlay) works in the React panel and produces the same `plan.json` as v2's page for the same input.
- [x] Every picker action (candidates, pick, refetch, sources, jobs) works in the React panel, and picking writes `assets_progress.jsonl` as v2 does.
- [x] Selecting shot N in the planner selects it on the timeline, and vice versa.

M3
- [x] After the final render pass, the editor shows the native OpenCut project with no `/esta-seed` step. Clip count, track mapping and media match `from_openreel.py`'s mapping for the same session.
- [x] Re-running render updates the open timeline without a page reload.
- [x] In the chat panel, "make shot 3 two seconds" resizes the correct clip live (verified on a crossfaded session).
- [x] `get_frame` from chat returns a composited frame of the current timeline.
- [x] Editing `plan.json` from the terminal while the planner is open: with no local edits it reloads silently; with local edits the Keep mine / Take theirs banner appears.
- [x] An exported video's source references are originals, not proxies (checked via ffprobe resolution against the originals).

M4
- [ ] `PARITY.md` lists every v2 `apps/studio` feature with a status, and every "dropped" entry is approved by the user.
- [ ] Every "port" entry is usable in the editor (a manual check per row, ticked in `PARITY.md`).

Global
- [x] Typecheck passes for `apps/editor` and `server/`, and lint passes for the code ESTA owns (`apps/editor/src/esta/`, ESTA routes, `server/`, `scripts/`); vendored OpenCut code keeps its upstream lint baseline (see `PORTING.md`). Commands recorded in CLAUDE.md.
- [ ] An end-to-end run of `standard-vo` on a short test topic reaches an exported video entirely from the UI, without touching the terminal.
- [ ] The same end-to-end run using the `found-audio-collage` template reaches the Edit stage.

---

# Part 2 — Inspo match (M5)

Decided with the user on 2026-09-27. Part 1's rules still apply: ESTA code in `apps/editor/src/esta/` and `server/`, OpenCut edits and any change to v2-copied files logged in `PORTING.md`, lean code, no emojis.

## Goal

Make generated videos follow the user's inspo videos measurably, not only by vibe. Today style-analysis measures two pacing numbers (cuts per minute, mean shot length, from a crude brightness-diff cut detector on two 60 s clips per video) and hands the rest to the plan skill as prose; nothing ever checks the result against the inspo.

M5 adds:
1. **Search queries that follow the shot.** In the planner, rewriting a shot, changing its type, or splitting it re-derives that shot's search queries (per half for a split), unless the user has edited the queries by hand.
2. **An inspo profile**, measured from the whole inspo videos with small free models chosen by a bake-off (M5.1), cached per video.
3. **A similarity score** in five sections, computed for the plan and for the final edit:
   - a. asset distribution
   - b. colour and grading
   - c. thematic adherence
   - d. complexity (overlays, on-screen text, multi-panel shots, clips per shot, variety)
   - e. shot duration, mean **and** median
4. **Targeted auto-adjust.** A new `match` pipeline step that, when the score is under the pass mark, nudges only the failing sections (split/merge, retype, overlays, composites, requery, colour grade), then re-scores, for at most 3 rounds.
5. **A score card** in the Plan stage.

The division of labour: local models and scripts do the looking and the arithmetic; Claude only reads the numeric report and makes the judgement calls (which shots to retype or requery, what the new queries are).

## Non-goals / out of scope

- **Script similarity.** Scoring the script against the inspo narration (pace, sentence length, hook shape, second-person/question rate, structure beats, a Claude check with a threshold and revise loop) is a later build. Record only: the inspo transcripts that style-analysis already produces are its input. Not built in M5.
- A full re-plan when the score is low. Adjust only edits the shots it needs to.
- Changing shots the user edited by hand (they are locked; see Key decisions).
- Scoring audio, music, SFX or transitions.
- Editing `tools/style_analysis/` or the plan skill's generation logic. M5 adds new tools beside them; `style_analysis.json` and `plan.json` keep their schemas (new optional fields only, listed below).
- Fine-tuning any model. The bake-off only selects among existing checkpoints.
- An Adjust button. Adjust runs as a pipeline step; the card has only a cheap **Re-score** (no Claude).

## Files & interfaces involved

New, owned by v3 (not v2 copies):
- `tools/match/` (Python, `esta` env except the Kaggle lane):
  - `inspo.py` — resolve inspo sources, download whole videos, build and cache profiles.
  - `cuts.py` — cut detection, wrapping the winning detector.
  - `colour.py` — per-shot colour statistics (no model).
  - `embed.py` — image (and, for plan estimates, text) embeddings with the winning model.
  - `tag_kaggle.py` — `push` / `status` / `apply` for shot tagging on Kaggle, following the `tools/genvideo/run.py` + `tools/kaggle_lane.py` pattern; runs on the **system** python, like the other Kaggle lanes.
  - `score.py` — `python tools/match/score.py --session sessions/<id> --stage plan|final`, writes `match_report.json`.
  - `adjust.py` — deterministic operations: split/merge (calls `tools/plan/ops.py`), retype, add/remove overlay, make composite, mark requery, write grades.
  - `bakeoff/` — answer-key tooling, one Kaggle notebook that runs every candidate (`bakeoff/kaggle.py push|status|apply`, same lane pattern and system python), and a results report for M5.1.
  - Unit tests under `tools/match/tests/` (pytest, synthetic data, no GPU).
- `.claude/skills/match/SKILL.md` — the pipeline step: run `score.py`, read the report, choose and apply adjustments, re-score; announce as other skills do.
- `apps/editor/src/esta/panels/match-panel.tsx` — the score card, added to the Plan stage preset in `workspace.tsx`.
- `server/match.ts` — `GET /_match/:id` (latest report and history), `POST /_match/:id/rescore` (runs `score.py` as a job); route in `server/index.ts`.
- Repo-level cache: `cache/inspo/<source-hash>/` (`video.mp4`, `profile.json`, keyframes, embeddings). Gitignored.

Per-session artifacts:
- `inspo.json` — the inspo sources: `[{kind: "youtube"|"local", ref, source: "user_provided"|"auto_search"}]`. Written by `inspo.py`. For sessions that predate it, derived from `style_examples/<id>_start.mp4` names (YouTube ids) and `style_extraction.json`'s `source`.
- `match_report.json` — see Scoring. Keeps a `history` of every score and adjust round.
- `match_grades.json` — per-shot Grade effect parameters (the M4 Grade effect's `grade` JSON) written by the colour adjust.

Changed (v2 copies, so each change is logged in `PORTING.md`):
- `tools/pipeline/contracts.json`, `tools/pipeline/templates.json` — add the `match` skill (needs `plan.json` and `style_analysis.json`; produces `match_report.json`), run after `plan` and again after the final `render`, in both templates.
- `server/planner.ts` (v3) — rewrite system prompt and the new requery endpoint (see decision 1).
- `apps/editor/src/esta/panels/planner-panel.tsx` (v3) — pinned queries, stale marker, auto requery on type change.
- `apps/editor/src/esta/opencut/emit.ts` (v3) — apply `match_grades.json` as Grade effects at Build project.

New optional `plan.json` fields:
- `visual.queries_pinned: true` — hand-edited queries.
- `visual.queries_stale: true` — queries changed, asset not yet re-fetched.
- `locked: true` — the shot was edited by hand; adjust must not touch it.

`config.yaml`: a new `match` block holding the weights, pass marks, max rounds and the chosen models (filled by M5.1).

## Key decisions & tradeoffs

1. **Queries follow the shot, folded into existing calls.**
   - Rewrite: `REWRITE_SYSTEM` must return `search_queries` whenever it changes `desc` or `type`.
   - Type change (planner dropdown) and split: one small Haiku call per shot via `POST /_plan/api/requery` (`{session, shot_number}`), which returns `desc`-consistent `search_sources` following the plan skill's `search_sources` rules for the new type. For a split it runs once per half, on that half's spoken words, and may also rewrite each half's `desc`. Cost is shown in the UI like Rewrite.
   - Queries typed by hand set `queries_pinned`, and auto-follow then skips that shot (the planner shows "queries pinned" with an Unpin control).
   - `tools/plan/ops.py` is not modified: the backend calls requery after `split` returns.
2. **Changed queries mark the asset stale, then fetch in the background.** The old clip stays on the timeline, visibly marked stale, until the new pick replaces it through the existing picker refetch path (`/_picker/api/refetch`, `assets_progress.jsonl`). A split no longer relies on the cloned parent clip once its halves are re-fetched.
3. **Bake-off before building the scorer (M5.1).** Model accuracy on these exact jobs is unproven, so candidates are measured on an answer key built from the user's own inspo videos. Only winners that clear the bar are used; a tag no model gets right enough is dropped from scoring rather than trusted.
4. **Where things run (user decision).** The whole M5.1 bake-off runs on Kaggle: every candidate (cuts, tagging, theme) in one notebook on the same T4, so the comparison is fair and nothing has to be installed locally for it. In everyday use only shot tagging runs on Kaggle; cuts, colour, embeddings, scoring and adjust run locally, because they take seconds there and a Kaggle round-trip would add minutes to every score.
   **Tagging always runs on Kaggle.** The shot tagger (vision-language model) runs as a detached Kaggle job on the free T4, like `ai-video`. Cuts, colour and embeddings run locally in the `esta` env (small; the local GPU is 4 GB).
   - The tradeoff, accepted: each Kaggle run adds minutes of queue, install and model download, and uses the shared 30 GPU h/week.
   - Mitigations: inspo profiles are cached per video, so an inspo is tagged once ever; final-edit tagging only sends shots whose asset changed since the last tagging.
5. **Inspo depth: the whole video, up to 10 minutes.** Longer videos are sampled as evenly spaced chunks totalling 10 minutes.
6. **Several inspos form one combined target.** All their shots are pooled into one profile, weighted by duration.
7. **Auto-searched inspo (no user inspo) is treated like user inspo:** scored and adjusted.
8. **Scoring runs twice.**
   - Plan stage: from `plan.json`, before downloads.
   - Final edit: from the rendered project with real media, after assets and the final render.
   - Colour cannot be judged from a plan, so at the plan stage it shows "n/a" and is left out of the overall score (weights renormalised).
   - Theme at the plan stage is an estimate (text embedding of `desc` and queries against inspo keyframe embeddings) and is labelled as one.
9. **Weights and pass marks.**
   - Overall = weighted mean of the sections, with shot duration weighted 2 and the others 1.
   - Pass = overall ≥ 80 and every section ≥ 70.
   - All stored in `config.yaml` `match`, so there are no per-session controls.
10. **Adjust is targeted, ordered and capped.**
    - Each round fixes only the sections under their mark, structure first: e duration → a asset mix → d complexity → c theme → b colour, since splits and retypes change what later sections see.
    - At most 3 rounds. A round that doesn't raise any failing section by ≥ 1 point stops the loop early.
    - Claude is called only to choose shots and write queries for a, c and d, with only the failing section's report and candidate shots in context.
    - Operations per section:
      - **e:** split the longest shots at word boundaries (`ops.py split`), merge adjacent short shots (`ops.py merge`). At the final stage it may also move cut points to a neighbouring word boundary (≤ 0.5 s) in `plan.json` and re-render.
      - **a:** retype shots whose spoken line suits the under-represented type; the new type's queries come from decision 1.
      - **d:** add or remove `overlay` blocks; turn a shot into a `composite` (render's existing `layout` presets: `side_by_side`, `stack`, `triptych`, `inset`; at most 3 slots).
      - **c:** requery the least on-theme shots (stale then background fetch, decision 2).
      - **b:** compute a per-shot correction toward the inspo colour target and write it to `match_grades.json`. The emitter applies it as a Grade effect, so no re-download is needed and it survives rebuilds.
11. **Hand-edited shots are locked.** Any planner save that changes a shot's fields sets `locked`. Adjust never edits locked shots. When a section can't reach its mark because of locked shots, the card says so.
12. **Score card only in the Plan stage.** Two columns, Plan and Final edit. Per section: score, pass/fail and the measured numbers (e.g. "median 1.8 s vs inspo 1.2 s"). Also shown: the overall score, the status ("tagging on Kaggle…", "n/a at plan"), the adjust history (what each round changed) and Re-score.

### Revisions decided with the user on 2026-09-29
These override the text above where they conflict.
- **Local models run on the system python, not `esta`.** `esta` pins `transformers==4.33.3` for XTTS, which predates DINOv3 and SigLIP 2. The system python already hosts the Kaggle CLI, TransNetV2 and a CUDA torch, so cuts, embeddings and colour run there (`python tools/match/...`), like the Kaggle lanes.
- **SigLIP 2 joins the picks as the text-image model.** DINOv3 is image-only, so it cannot compare a shot's text (plan-stage theme) or a candidate's fit to its description. SigLIP 2 passed the theme bar (AUC 0.974). DINOv3 stays the image-image model (inspo look).
- **`kind` is measured in merged classes**, whichever of these clears the tag bar on a re-run of the answer key: 4 classes `footage` (footage, talking_head, screen, ai), `still`, `graphic`, `meme`; or 3 classes with `meme` folded into `footage`. Plan kinds: `REAL_FOOTAGE`/`AI_VIDEO` → footage, `REAL_IMAGE` → still, `MOTION_GRAPHICS` → graphic, and (4-class only) a non-graphic shot whose first search source is giphy → meme.
- **`panels` and `clips_in_shot` are unmeasured** (every answer-key shot is 1/1), so their scores carry no weight in picking a model. All tags run on `gemma4-e4b` in one pass per keyframe, 5x cheaper than Qwen3-VL-8B; `clips_in_shot` moves off Qwen for that reason.
- **Adjust runs until pass**, not 3 rounds: it stops on pass, on a round that fails to raise the overall score by at least 1 point (that round is reverted), or at a safety cap of 8 rounds.
- **Auto-pick replaces the default asset picks.** `tools/match/autopick.py` gathers candidates per shot (`assets/run.py candidates`), ranks them locally by SigLIP 2 fit to the shot's desc and spoken line plus DINOv3 similarity to the inspo's keyframes, and sends each shot's top 3 to Gemma 4 on Kaggle in one batched job to choose (and reject watermarked or off-topic ones). Picks are written as `visual_verdict: "auto_picked"`. A stale shot (decision 2) is refetched through the same path.
- **Final-stage kinds come from what was placed** (a HyperFrames clip is a graphic, an image file a still, otherwise the plan's kind), not from tags: Gemma reads static stock video as stills (F1 0 on the answer key). Only the inspo is tagged.
- **Colour compares picture shots only** (footage and stills above near-black), the set a grade can change; otherwise the shot mix reads as a colour gap. The colour adjust is rank-preserving: each shot is graded toward the inspo's value at its own quantile, which is what minimises the Wasserstein distance the section scores.
- **The overlay rate is out of complexity.** Gemma counts speech captions as overlays even when told not to, and every ESTA render carries subtitles.
- **Two report files.** `match_plan.json` (plan stage) and `match_final.json` (final stage), each with sections, overall, pass and history; the conductor tracks them as `match:plan` and `match:final`.

### M5.1 bake-off design
- **Answer key:** 2–3 of the user's inspo videos (about 100 shots), chosen by the user, stored under `tools/match/bakeoff/key/`.
  - Cuts: proposed by the union of all cut candidates, confirmed or rejected by Claude from frame strips, plus a scan of 1 s contact sheets for missed cuts.
  - Per-shot labels, drafted by Claude from keyframes:
    - kind: `footage` / `still` / `graphic` (motion graphic, text card) / `ai` / `talking_head` / `screen` / `meme`
    - `text_on_screen` (bool)
    - `panels` (1, 2, 3+)
    - `overlay` (bool)
    - `clips_in_shot` (int)
  - The user spot-checks at least 10 shots in a simple review page before the key is frozen.
- **Candidates (all run in the one Kaggle notebook):**
  - Cuts: TransNetV2, AutoShot, PySceneDetect `AdaptiveDetector`.
  - Tagging: Qwen3-VL-8B, Qwen3-VL-4B, Gemma 3 4B, plus Florence-2-large for `text_on_screen` only.
  - Theme embeddings: SigLIP 2, CLIP ViT-B/32 (the current one), DINOv3 (small).
- **Metrics and bars:**
  - Cuts: F1 with ±0.1 s tolerance; bar ≥ 0.90.
  - Tags: per-tag accuracy (macro-F1 for `kind`); bar ≥ 0.85 per tag.
  - Theme: AUC of same-inspo vs different-style shot pairs (different-style frames from a second style with no overlap); bar ≥ 0.80. The same pairs give the calibration curve that maps similarity to 0–100.
  - Speed and cost are recorded per candidate (seconds per minute of video on the T4; GPU minutes). For the local jobs (cuts, theme), the winner must also run in the `esta` env on the user's 4 GB GPU or CPU; the user runs one local timing check before approving.
- **Output:** `tools/match/bakeoff/results.md` (a table per job, the winner and why), and the winners written to `config.yaml` `match.models`. Checkpoint: the user approves the winners before M5.3.

### Scoring formulas (sections are 0–100)
- **a. Asset distribution:** duration-weighted share of shots per kind; score = 100 × (1 − total variation distance) between ours and the inspo's.
  - Plan kinds come from `visual.type`: `REAL_FOOTAGE` → footage, `REAL_IMAGE` → still, `MOTION_GRAPHICS` → graphic, `AI_VIDEO` or a `generate` block → ai. A `composite` counts as its slot-0 kind.
  - Final kinds come from tags.
- **b. Colour and grading** (final only): per-shot mean L\*, L\* standard deviation (contrast), mean chroma (saturation), mean a\* and b\* (tint, warmth) and colourfulness, from 3 keyframes per shot.
  - Per feature: Wasserstein distance between our and the inspo's per-shot distributions, divided by the inspo's interquartile range (floored so a very uniform inspo can't divide by ~0).
  - Score = 100 × exp(−mean normalised distance).
  - The per-feature numbers are kept for the colour adjust.
- **c. Thematic adherence:** for each of our shots, the highest calibrated similarity to any inspo keyframe; the score is the duration-weighted mean. Final uses image embeddings; plan uses text embeddings (labelled an estimate).
- **d. Complexity:** four per-shot rates, compared to the inspo's: share with an overlay, share with on-screen text, mean panels, mean clips per shot. Plus variety: the number of distinct kinds per minute.
  - Each rate's sub-score = 100 × (1 − min(1, |ours − inspo| / max(inspo, floor))); the section is their mean.
  - Plan values come from `plan.json`: `overlay`, `text.caption`, `composite` slots.
  - Final values come from the rendered project and tags.
- **e. Shot duration:** mean and median separately, each sub-score = 100 × max(0, 1 − |ours − inspo| / inspo); the section is their average.
  - Plan uses `plan.json` start/end (real timing once reconciled; the card marks estimated timing).
  - Final uses clip durations on the rendered timeline (crossfade lanes flattened as in Part 1).
  - Tags dropped by the bake-off are excluded from a and d, and the report says which.

## Edge cases

- No inspo at all and style-analysis has not run: `match` is gated on `style_analysis.json`, as `plan` is.
- An inspo can't be downloaded (private, region-locked, removed): profile the rest and list the failures on the card. If none can be downloaded, score only e from `style_analysis.json`'s pacing numbers and say so.
- A local inspo file path that moved: reported as missing, never guessed.
- Inspo longer than 10 minutes: evenly spaced chunks (decision 5). Shorter than 30 s: used whole, with a note that the profile is thin.
- A video with no detected cuts (one continuous shot) or very frequent flashes: the detector's raw output is kept, and shots under 2 frames merge into their neighbour before scoring.
- Kaggle unavailable, over quota or failing: tag-dependent parts (final a, d, and the kind-based parts of the inspo profile) show "pending: Kaggle" with the error. Adjust doesn't act on sections that can't be scored. Cuts, colour, theme and duration still score. Retry is in the Jobs panel.
- `esta` env missing: the card shows the same blocking notice as other Python stages.
- Every shot locked: adjust makes no changes and reports it.
- A split or merge renumbers shots: `match_grades.json` and the report history reference shots by id (the spoken-line identity the planner already uses), not by number.
- An adjust round makes a section worse: that round's plan edits are reverted from the `ops.py` backups, and the loop stops.
- The user edits the plan while `match` is adjusting: the file-watch conflict banner (Part 1) applies; adjust re-reads `plan.json` before each operation and skips shots that became locked.
- Requery returns nothing usable (Haiku error, empty list): the shot keeps its old queries, is not marked stale, and the error is shown on the shot.
- Type changed back before the requery finishes: only the latest request's result is applied.
- Re-score with no plan changes: returns the cached report (same inputs hash), no recompute.
- A composite would need more than 3 slots: capped at 3, as render's `MAX_COMPOSITE_SLOTS`.

## Acceptance criteria

M5.1 Bake-off
- [ ] `tools/match/bakeoff/key/` holds the answer key for 2–3 user-chosen inspo videos (≥ 80 shots total), with ≥ 10 shots marked as user-checked.
- [ ] `python tools/match/bakeoff/kaggle.py push` runs every candidate for all three jobs in one Kaggle notebook; `apply` pulls the outputs and writes `tools/match/bakeoff/results.md` with F1 / accuracy / AUC, speed and GPU cost per candidate.
- [ ] The winning cut detector and theme model run locally in the `esta` env on the user's PC (timing noted in `results.md`).
- [ ] Each job's winner clears its bar (cuts F1 ≥ 0.90, each used tag ≥ 0.85, theme AUC ≥ 0.80), or the results list which tags or jobs have no passing model and are dropped.
- [ ] The winners are recorded in `config.yaml` `match.models` and approved by the user.

M5.2 Queries follow the shot
- [ ] Rewrite with an instruction that changes `desc` or `type` returns and applies new `search_sources` (checked with a stubbed `claude`).
- [ ] Changing a shot's type in the planner calls `/_plan/api/requery` and updates its queries; the shot is marked `queries_stale`, and after the background refetch the new asset replaces the old one on the timeline.
- [ ] Splitting shot N produces two shots whose queries differ and each match their own half's spoken words; neither half keeps the parent's cloned asset once refetched.
- [ ] Editing the queries by hand sets `queries_pinned`; a later rewrite, type change or split of that shot leaves its queries unchanged until Unpin.

M5.3 Inspo profile
- [ ] `python tools/match/inspo.py profile --session sessions/<id>` downloads the whole inspo videos (≤ 10 min each), runs cuts, colour and embeddings locally, pushes tagging to Kaggle, and writes `cache/inspo/<hash>/profile.json` with per-shot duration, colour features, embeddings path and tags.
- [ ] Running it again for the same video reuses the cache (no download, no Kaggle run).
- [ ] An older session with no `inspo.json` gets one derived from `style_examples/`.

M5.4 Scoring and score card
- [ ] `score.py --stage plan` on a mock session writes `match_report.json` with a–e (b = n/a), the overall score, pass/fail per the config marks, and the measured numbers behind each section.
- [ ] `score.py --stage final` on a mock rendered session fills all five sections.
- [ ] Unit tests: identical plan and inspo distributions score 100 on a, d, e; known shifted inputs score within ±2 of hand-computed values for each formula.
- [ ] The Plan stage shows the Match card with Plan and Final columns, per-section numbers, pass marks and adjust history; Re-score runs as a job and refreshes the card.

M5.5 Auto-adjust
- [ ] The `match` step is in `contracts.json` and both templates. `validate_flow.py` passes, and `conductor.py next` names `match` after `plan` and after the final render.
- [ ] On a mock session whose median shot length is double the inspo's, one round of adjust splits shots and raises section e without touching locked shots or any passing section's data.
- [ ] Adjust stops at 3 rounds, or earlier when passing or not improving, and records each round in `match_report.json` history.
- [ ] A colour adjust writes `match_grades.json`, and Build project applies those Grade effects to the right clips (checked on the native project's effect params).
- [ ] A round that lowers a section is reverted.

Global
- [ ] `bun run typecheck` and `bun run lint` pass; `pytest tools/match/tests` passes.
- [ ] `PORTING.md` lists every change to v2-copied files (contracts, templates) made for M5.
- [ ] An end-to-end run on the user's PC with a real inspo reaches a final score, with any adjust rounds visible on the card (user check; this sandbox has no conda or Kaggle).

# Part 3 — Inspo match v2: copy the inspo shot by shot (M6)

Decided with the user on 2026-10-02, after the describe bake-off (`tools/match/experiments/describe_bakeoff/README.md`) and a survey of comparable tools (video-style-kit, ReelMimic, CutClaw, OpenMontage, and Google's "Automatic Non-Linear Video Editing Transfer", arXiv 2105.06988). Parts 1 and 2 still apply where not overridden here.

## Goal

M5 builds a plan, scores it against the inspo, then nudges it. The result on `do-alphas-even-exist-2026-09-29` was off: the plan was cut one shot per sentence at style-analysis's 4.84 s average while the inspo measures 2.4–2.8 s (TransNetV2), splits came out as matched pairs, the plan stopped 79 s before the voiceover ended, and 44 gaps left 22 s of black — and the score still passed, because section e compares only mean and median from `plan.json`.

Every comparable tool works the other way round: measure the reference per shot, then build each new shot as the counterpart of one reference shot, and check the result side by side. M6 does that:

1. **Describe lane.** Claude Haiku describes each inspo shot (description, kind, content, sourcing hint, text and overlay flags) from a 384 px keyframe plus the words spoken over it. Replaces the Gemma/Kaggle tagger.
2. **`ref_shot` mapping.** Each of our shots copies one inspo shot, picked by normalised position: our shot at 30 % of our video copies the inspo shot at 30 % of the inspo. It inherits that shot's real length in seconds, snapped to our word boundaries, its kind, and its camera move.
3. **Hybrid cut with a hard validator.** A tool proposes the slots; the plan skill writes the shots under rules; a validator rejects only the failing sections, with what to change, and freezes the parts that passed.
4. **Auto-pick by duration, then kind, then likeness to the `ref_shot`**, with Haiku as the judge instead of Gemma on Kaggle.
5. **Camera moves and fades copied from the inspo**, measured per inspo shot and emitted by render as keyframes on scale, position, rotation and opacity (the editor already animates all four; render only ever emitted scale).
6. **A side-by-side review page**: every shot of ours next to its `ref_shot`, linked from the Match card.
7. **The score stays** as the summary and as adjust's driver, with section d made subtitle-blind and section e scoring median plus distribution shape.

## Non-goals / out of scope

- Scoring or guessing the exact source site. Haiku's top source is unreliable (it says `youtube` for ~80 % of shots, including clean Pexels stock); sources only guide search through `sourcing_hint`.
- Gemma and Kaggle in the match path. `tools/match/tag.py`, `vlm_kaggle.py` and `bakeoff/` stay in the repo as the M5.1 record but nothing in M6 calls them. Other Kaggle lanes (audio, ai-video) are untouched.
- Script similarity (still deferred from Part 2).
- Stretching inspo durations to our length: lengths are real seconds; only position is normalised.
- Changing `tools/style_analysis/`. Its OpenCV `avg_shot_duration` is simply not used for pacing when a mapped plan is built.
- Playback-speed transfer (the paper's third feature): needs a human label there too.
- Eased keyframe curves. `emit.ts` interpolates linearly; punch-ins and crash zooms are built from closely spaced linear keyframes.
- A native review panel. The review page is static HTML served by the backend.

## Files & interfaces involved

New (v3-owned):
- `tools/match/describe.py` — Haiku describe lane. `describe_shots(items, log) -> {answers: {id: answer}, cost_usd, wall_secs, errors}`; batches of 10 keyframes per `claude -p` call, 4 calls in parallel, lean flags (`--strict-mcp-config --setting-sources "" --tools "" --max-turns 1`, short `--system-prompt`, stream-json input with inline base64 images). Cache `cache/describe.json` keyed by keyframe sha1 + prompt version. CLI: `python tools/match/describe.py inspo --session sessions/<id>`.
- `tools/match/speech.py` — words spoken over each inspo shot (faster-whisper `small` with word timestamps; CUDA, CPU int8 fallback), cached as `cache/inspo/<hash>/words.json`.
- `tools/match/motion.py` — per-shot camera move and boundary fades from frames (OpenCV ORB + RANSAC similarity transform between frames at 20 % and 80 % of the shot, plus a 5-frame jitter check; mean luma over the first and last 0.5 s).
- `tools/match/slots.py` — `python tools/match/slots.py --session sessions/<id>` writes `slots.json` (the proposed cut).
- `tools/match/validate_plan.py` — `python tools/match/validate_plan.py --session sessions/<id>` writes `plan_validation.json` and exits non-zero on any hard failure.
- `tools/match/review.py` — writes `match_review.html` (self-contained, 384 px base64 keyframes).
- Tests under `tools/match/tests/`: `test_slots.py`, `test_validate.py`, `test_motion.py`, `test_describe.py` (stubbed `claude`), additions to `test_score.py`.

Changed (v3-owned):
- `tools/match/inspo.py` — `tag_profile` replaced by `describe_profile` (speech → describe → motion); profile shots gain `words`, `tags` (below) and `motion`.
- `tools/match/score.py` — d text rate subtitle-blind; e = median + shape; reads `ref_shot`.
- `tools/match/adjust.py` — kept whole (user decision); splits and merges keep `ref_shot` and must leave `validate_plan.py` passing, else the round is reverted; `write_wording` uses the lean flags.
- `tools/match/autopick.py` — duration and kind filters, `ref_shot` likeness, Haiku judge.
- `tools/match/common.py` — `DEFAULT_MATCH.models.tags = "haiku"`, the lean `claude` argv helper, describe/judge config.
- `.claude/skills/match/SKILL.md` — new `profile` mode; plan-mode reads validator output.
- `server/match.ts` — `GET /_match/:id/review` serves `match_review.html`.
- `apps/editor/src/esta/panels/match-panel.tsx` — "Open side-by-side" link; validator failures shown.

Changed (v2 copies; each logged in `PORTING.md` with the reason):
- `.claude/skills/plan/SKILL.md` — mapped mode (below).
- `tools/render/run.py` — camera moves and fades from the plan's `camera` / `transition_in` / `transition_out`.
- `tools/pipeline/contracts.json`, `tools/pipeline/templates.json` — new `match:profile` step; `plan` gains optional needs `slots.json` / `inspo_profiles.json`.

Per-session artifacts (new):
- `inspo_profiles.json` (exists from M5) — now produced by `match:profile`, before plan.
- `slots.json` — `{"voice_end": s, "inspo_total": s, "slots": [{"slot": 1, "start", "end", "target_dur", "ref_shot", "ref_pos", "alts": [ids], "words": "..."}]}`.
- `plan_validation.json` — `{"pass": bool, "failures": [{"section": [first_shot, last_shot], "start", "end", "problems": ["..."], "fix": "..."}], "frozen": [shot numbers]}`.
- `match_review.html`.

Inspo profile shot fields (added):
- `words`: text spoken over the shot.
- `tags`: `{"description", "kind": "footage|still|graphic", "content": "single_focus|multi_subject|background|text_card|ui_chart", "sourcing_hint": "search phrase", "likely_sources": [...], "text_extra": bool, "overlay_extra": bool, "text_on_screen": bool, "overlay": bool, "panels": 1, "clips_in_shot": 1}`. `text_on_screen`/`overlay` mirror `text_extra`/`overlay_extra` so M5 code paths keep reading them.
- `motion`: `{"move": "static|push_in|push_out|pan_left|pan_right|tilt_up|tilt_down|punch_in|shake", "amount": 0.0–1.0, "fade_in": "none|black|white", "fade_out": "none|black|white"}`.

`plan.json` shot fields (new, optional):
- `ref_shot` (inspo profile shot id), `ref_target_dur` (s), `ref_swap` (reason, when the shot took an alt instead of the positional ref).
- `camera`: `{"move", "amount"}` — defaults to the ref's motion; the plan may change it.
- `transition_in` / `transition_out`: `cut|fade_black|fade_white` — from the ref's fades.

## Key decisions & tradeoffs

1. **Describe with Haiku, not Gemma.** Bake-off on 225 shots: $0.43–0.63 and 3–5 min per run with batching and lean flags, versus Gemma on Kaggle cancelled after ~30 min. Kind (footage/still/graphic) was right 17/17 on our shots when the spoken words were included; exact source was 8/17. So the prompt asks for kind, content, sourcing hint and a description, and the spoken words over the shot are always sent. Keyframes are 384 px on the long side. Results are cached per keyframe, so an inspo is described once.
2. **Content classes from the paper, plus two of ours.** `single_focus` / `multi_subject` / `background` (the paper's classes, which drive framing and retrieval) plus `text_card` and `ui_chart` for the terminal-card and chart look ESTA inspos use. Kind and content are separate fields.
3. **`ref_shot` by normalised position, real seconds (user decision).** Position p in our video maps to p × inspo_total in the inspo; the inspo shot covering that time is the ref and gives the target length in seconds. A video longer than its inspo has more shots than the inspo and walks through the inspo's rhythm proportionally. Several inspos are concatenated in `inspo.json` order into one timeline.
4. **The line can swap to a nearby ref (user decision).** The positional ref sets the default; the plan may instead take any inspo shot within ±3 shots of it (`alts`) whose description fits the spoken line better, recording `ref_swap`. Target length always stays the positional ref's, so the rhythm is kept even when the look swaps.
5. **Hybrid cut (user decision).** `slots.py` proposes the cut deterministically; the plan skill writes one shot per slot and may merge or split slots under the rules below; `validate_plan.py` checks the result.
   - Snapping: a cut goes to the word boundary nearest `start + target_dur`; a boundary is the midpoint of the gap between one word's end and the next word's start (or the shared instant when there is no gap). The first slot starts at 0; the last ends at `voice_end` (the audio duration, not the last word).
   - A single word longer than its target becomes one slot. A last slot under 0.4 × its target merges into the previous one.
   - Plan rules: keep slot boundaries unless merging two slots whose combined length is within 1.35 × the first slot's target, or splitting a slot at an inner word boundary when its words hold two distinct visual ideas; every edit must still pass the validator.
6. **The validator is hard but section-scoped (user decision).** Hard failures:
   - coverage: the first shot does not start at 0 or the last does not end at `voice_end` (±0.1 s);
   - a gap or overlap between consecutive shots over 0.1 s;
   - a cut inside a word (more than 0.05 s from both of its edges). A cut anywhere in the pause between two words is on a boundary: `tools/plan/ops.py split` cuts at a word's onset, not at the pause midpoint `slots.py` snaps to;
   - a shot outside ±35 % of its `ref_target_dur` (±75 % for the last shot, which may hold the stub `slots.py` merges into it), unless no word boundary lies closer to the target (then it is exempt);
   - a shot missing `ref_shot`.
   Failing shots are grouped into sections (consecutive failures plus one shot of context each side); each section gets a plain fix instruction ("shots 41–44, 312.4–325.0 s: gap 0.8 s between 42 and 43; shot 44 is 6.1 s against a 2.6 s target — cut after 'returns' at 322.0 s"). Every other shot is listed as frozen: the plan skill rewrites only failing sections, keeps frozen shots byte-identical, and re-runs the validator, up to 3 times; then it stops and shows the remaining failures to the user.
7. **Pipeline order.** The mapping needs the inspo profile and real word timing, so in mapped mode `plan` runs after `timestamps` and after a new `match:profile` step (`inspo.py profile`: cuts, colour, embeddings, speech, describe, motion). `match:profile` needs only `style_analysis.json` (for the inspo sources). It sits right after `style-analysis` in the templates; it is not marked `parallel`, because that flag means "needs only `requirements.json`" to the server's stage gating, so in practice it runs after timestamps. Without an inspo profile or without `timestamps.json`, the plan skill falls back to its current behaviour, unchanged.
8. **Adjust stays whole (user decision)** — e, a, d, c, b fixes as in Part 2. Additions: a split gives both halves the parent's `ref_shot` and `ref_target_dur` / 2 each; a merge keeps the first shot's ref and sums the targets; after each round `validate_plan.py` runs, and a round that adds validator problems (more of them, or a kind the plan did not have) is reverted exactly like a round that lowers the score.
9. **Section d is subtitle-blind.** Ours: a shot counts as text when it has a `text.caption`, an `overlay` with text, or is `MOTION_GRAPHICS` — never for subtitles. Inspo: `text_extra` ("text other than speech subtitles"). Overlay rate stays out of d as in Part 2.
10. **Section e scores the shape.** e = mean of a median sub-score (100 × max(0, 1 − |median_ours − median_inspo| / median_inspo)) and a shape sub-score (100 × (1 − KS), KS = two-sample Kolmogorov–Smirnov statistic between our and the inspo's shot lengths). The mean is dropped: shot lengths are skewed and the median is the robust pace measure (film-statistics literature). At the final stage e reads clip durations from the rendered project, per Part 2's spec.
11. **Auto-pick order (from the paper).** Hard filters first: video candidates must be at least the shot's length (from their probed duration minus `in_point`; stills are exempt), and the candidate's kind must match the shot's (image file = still, video = footage, graphics are generated not picked). Then rank by SigLIP 2 fit to desc + spoken line plus DINOv3 similarity to the shot's `ref_shot` keyframe (not the whole inspo). Then Haiku judges the top 3 per shot, 10 shots per call, seeing the ref keyframe and its description; it may reject all three (watermark, off-topic), in which case the next-ranked survivor is used as in M5.
11a. **The right section of a long clip (decided 2026-10-02).** A candidate more than 3× its shot's length (an Archive.org reel, a long stock clip) is judged on its best section, not its first seconds: auto-pick samples a frame every 0.5 s, scores each with the same SigLIP 2 fit and DINOv3 ref likeness as the ranking, and sets `in_point` to the start of the shot-length window with the best mean score. YouTube candidates keep the moment their transcript/visual finder chose and are not re-windowed. The models judge stills, so this finds the right scene, not the instant of an action.
11b. **Too-short clips are filled, not cut short (decided 2026-10-02).** Render and the editor already play a clip's `speed`; nothing loops. So after the pick, for a video whose usable length (`source_duration − in_point`) is under the shot's:
   - ≥ 0.6 × the shot: slow it to fit, `speed = usable / shot` (reads as natural slow motion);
   - shorter, Giphy: repeat it at normal speed, `repeat = ceil(shot / usable)` (reaction loops are made to loop);
   - shorter, any other source: prefer another survivor that is long enough; with none, slow to 0.6× and repeat the rest, flagged `short_clip`.
   The pick's `speed` and `repeat` go on its `assets_progress.jsonl` row (with `short_clip` when flagged, so it outlives `autopick.json`). Render sets the clip's `speed`, plays `in_point → in_point + shot × speed`, and emits `repeat` back-to-back copies (`clip-shot-<n>`, `clip-shot-<n>-r2`, …) with no dissolve between copies of one shot. Giphy therefore stays exempt from the length filter (it is filled by repeating) and from the kind filter (the plan skill's meme override sends reaction loops to Giphy even for still shots).
11c. **All three finalists rejected:** the next-ranked survivor after them is used; only when there is none does the top-ranked finalist stand.

12. **Camera moves measured, not guessed.** `motion.py` samples 9 frames across the middle 80 % of each inspo shot and estimates a similarity transform between consecutive samples (ORB keypoints + RANSAC, foreground faces not excluded — cheap first version); the chained steps give the net move and the per-step jitter. Classification: one step with a scale jump > 10 % that is either within 0.3 s or holds at least 60 % of the shot's net zoom → punch_in (a smooth push spreads its zoom over every step); scale change > 4 % → push_in/push_out; translation > 3 % of width/height → pan/tilt; high frame-to-frame jitter with near-zero net motion → shake; else static. `amount` is the normalised magnitude. Fades: mean luma below 8 (or above 247) on a cut-adjacent frame, ramping over ≥ 3 frames.
13. **Render emits the moves on every channel.** `camera.move` becomes keyframes on `scale.x/y`, `position.x/y`, `rotation` (shake only, whole degrees: the editor snaps rotation to a 1-degree step) and `opacity` (fades), in the units `emit.ts` `KEYFRAME_PATHS` expects. Applies to stills and footage. A shot with `camera` replaces the automatic alternating Ken Burns; a still without `camera` keeps Ken Burns. Inspo fades replace the energy-gated R5 dissolves wherever the plan carries `transition_in` / `transition_out`. Fades are opacity ramps over the black canvas, so `fade_white` renders as a fade through black (a white fade would need a white layer; not built). On a repeated clip (decision 11b) only the first copy fades in and the last fades out.
14. **Review page.** After every score, `review.py` writes `match_review.html`: one row per shot of ours — our keyframe (final stage; plan stage shows the desc only), the `ref_shot` keyframe, both descriptions, kind ours/ref, target vs actual length, camera move, and flags (validator failure, low theme, swap reason). The Match card links to it through `GET /_match/:id/review`.
15. **Cost visible.** Describe and judge costs are summed into the match reports and shown on the card, like adjust's wording cost.

16. **Generated shots copy the inspo's animation (M6.6, decided 2026-10-02).** One keyframe cannot show how a graphic moves, and `motion.py` measures the camera, not movement inside the frame. So:
   - **Animate pass.** After the describe pass, every inspo shot described `kind: graphic` gets a strip image: frames at 20 %, 50 % and 80 % of the shot side by side (each 256 px wide), saved as `cache/inspo/<hash>/strips/<id>.jpg`. Haiku reads the strips, 10 shots per call with the same lean flags, and answers per shot `{"reveal": types_on|counts_up|draws_on|slides_in|pops_in|fades_in|scrolls|static|other, "speed": slow|medium|fast, "layout": "<where things sit>", "palette": "<colours>", "type_style": "<font feel: monospace, bold sans, serif, handwritten...>", "notes": "<one sentence on anything else distinctive>"}`. Stored as `tags.animation`; cached by strip content and prompt version.
   - **The generator sees the inspo.** `slots.json` `refs` carry `animation` and `strip` for each ref. The motion-graphics skill, for a `MOTION_GRAPHICS` shot or an `overlay` whose plan shot has a `ref_shot` with an `animation`, reads that strip (Read tool) and builds the HyperFrames composition to match the reveal, speed, layout, palette and type style, with our content. Without a ref it works as before.
   - **AI video by mapping.** When a ref's `likely_sources` lead with `ai_video`, the mapped plan types the shot `AI_VIDEO` and writes `generate.preset` from the ref's measured move: `push_in` -> `push_in`, `push_out` -> `pull_back`, `punch_in` -> `crash_zoom_in`, `pan_left`/`pan_right`/`tilt_up`/`tilt_down` -> the same name, `shake` -> `handheld`, `static` -> `static`. `slots.py` precomputes it as `refs[id].ai_preset`. Stock stays the fallback, as the ai-video skill already does.
   - **Review page** shows a graphic ref's animation (reveal, speed) and the shot's `generate.preset` when there is one.

## Edge cases

- Haiku call fails or returns unparseable JSON: retry that batch once; still failing, those shots stay without `tags` and the profile is `partial`. Sections a and d use the described shots if ≥ 90 % are described, else show "pending: describe" as Part 2 did for Kaggle.
- `claude` not on PATH: profile builds without tags (cuts, colour, embeddings, motion still work), with the error on the card.
- Inspo has no speech: descriptions use the image alone.
- Inspo described with an older prompt version: re-described on next profile (cache key includes the prompt version).
- Our voiceover shorter than the inspo: same normalised mapping; fewer shots, inspo rhythm compressed in position only.
- Leading silence before the first word: the first slot still starts at 0. Trailing silence after the last word: the last slot runs to `voice_end`.
- Words overlapping in timestamps (whisper artefacts): boundaries are clamped to be non-decreasing before snapping.
- Inspo shot under 2 frames or a flash cut: merged into its neighbour before mapping (Part 2 rule).
- Locked (hand-edited) shot fails the validator: reported as "locked: needs a hand fix" and never rewritten by the plan skill or adjust.
- Found-audio-collage flow: mapped mode applies whenever `timestamps.json` and an inspo profile exist; the arranger's audio supplies the words.
- Auto-pick: no candidate long enough — fall back to the longest candidate and fill it per decision 11b, flagging `short_clip` on the asset row (shown on the review page).
- Motion estimation finds too few keypoints (flat graphic, black frame): move `static`, amount 0.
- Review page for a 200-shot video stays under ~5 MB (384 px JPEG at quality 70).

## Milestones (checkpoint between each; each testable on the committed first-minute harness in `tools/match/experiments/describe_bakeoff/`)

- **M6.1 Describe lane:** `speech.py`, `describe.py`, `inspo.describe_profile`, subtitle-blind d, shape-based e.
- **M6.2 Mapping:** `slots.py`, `validate_plan.py`, plan skill mapped mode, `match:profile` step, adjust keeps refs and validates.
- **M6.3 Auto-pick:** filters, ref likeness, Haiku judge.
- **M6.4 Moves and fades:** `motion.py`, render emission.
- **M6.5 Review page:** `review.py`, route, card link.
- **M6.6 Generated shots copy the inspo:** animate pass, refs carry animation/strip/ai_preset, motion-graphics and plan skills use them, review page shows them.

## Acceptance criteria

M6.1 Describe lane
- [ ] `python tools/match/describe.py inspo --session <s>` fills `tags` (all fields above) for every shot of each inspo profile, with ≤ 10 keyframes per `claude` call, and records cost and wall time in the profile.
- [ ] A second run makes no `claude` calls (cache hit by keyframe hash + prompt version).
- [ ] `test_describe.py`: with a stubbed `claude` returning fixed JSON, answers are parsed, a malformed batch is retried once, and the lean flags are present in the argv.
- [ ] Section d's text rate counts no subtitle-only shot of ours as text; on the first-minute harness d moves off its ~39 floor.
- [ ] Section e has `median` and `shape` sub-scores; identical distributions score 100; a unit test checks the KS sub-score against a hand-computed value (±1).
- [ ] No match code path imports `tag.py` or `vlm_kaggle.py` (grep check).

M6.2 Mapping
- [ ] `slots.py` on the harness session tiles 0 → `voice_end` with no gap or overlap, every inner cut on a word boundary, and the slot median within 15 % of the inspo median (`test_slots.py` on synthetic words and inspo shots, plus the real session).
- [ ] `validate_plan.py` on the current `do-alphas-even-exist` plan fails with sections naming the 79 s uncovered tail and the gaps; on a plan built from `slots.json` it passes.
- [ ] `test_validate.py`: each hard rule triggers on a crafted plan; frozen shots exclude every failing section; locked shots are reported, not rewritten.
- [ ] The plan skill's mapped mode writes `ref_shot`, `ref_target_dur`, `camera`, `transition_in/out` on every shot, and a run on the harness passes the validator within 3 attempts.
- [ ] `contracts.json` / `templates.json` include `match:profile`; `validate_flow.py` passes; `conductor.py next` names `match:profile` once `style_analysis.json` exists and `plan` once `inspo_profiles.json` and `timestamps.json` exist.
- [ ] An adjust round that would break the validator is reverted (test with a stubbed wording call).

M6.3 Auto-pick
- [ ] No video candidate shorter than its shot is chosen when a long-enough one exists; kind mismatches never chosen (unit test on synthetic candidates).
- [ ] Ranking uses the `ref_shot` keyframe's DINOv3 embedding (unit test with fake embeddings).
- [ ] Judging runs through `claude -p` with ≤ 10 shots per call; no Kaggle job is created.
- [ ] A candidate over 3× its shot's length gets the `in_point` of its best-scoring window (unit test with fake embeddings where the matching frames sit mid-clip); YouTube candidates keep their finder's `in_point`.
- [ ] Fill rule (unit tests): a 3 s clip on a 4 s shot gets `speed` 0.75; a 1 s Giphy loop on a 4 s shot gets `repeat` 4; a 1 s stock clip with no long survivor gets `speed` 0.6, a repeat count covering the shot, and `short_clip`.
- [ ] Render: a row with `speed`/`repeat` produces that many back-to-back clips covering the shot exactly, each with that speed and `outPoint − inPoint = clip duration × speed`, and no crossfade between copies of one shot (unit test on `build`).
- [ ] When Haiku rejects all three finalists, the 4th-ranked survivor is picked.
- [ ] `PORTING.md` logs the render change.

M6.4 Moves and fades
- [ ] `test_motion.py`: synthetic clips made with ffmpeg (zoompan in, zoom out, horizontal pan, static, fade from black) classify correctly.
- [ ] Render turns each `camera.move` into keyframes on the right channels, and `emit.ts` maps them (checked on a built project's animation paths); stills without `camera` still get Ken Burns.
- [ ] `PORTING.md` logs the render and plan-skill changes.

M6.5 Review page
- [ ] After `score.py`, `match_review.html` exists, opens offline, and shows one row per shot with both keyframes (final stage) and target vs actual length.
- [ ] The Match card's "Open side-by-side" link loads it via `/_match/:id/review`.

M6.6 Generated shots copy the inspo
- [ ] `describe_profile` builds a 3-frame strip for every `graphic` inspo shot and fills `tags.animation` with the fields above, ≤ 10 strips per `claude` call; a second run makes no calls (`test_describe.py` with a stubbed `claude`, strips from an ffmpeg clip).
- [ ] `slots.json` refs carry `animation`, `strip` and `ai_preset`; the move-to-preset mapping matches decision 16 for every move (unit test).
- [ ] The motion-graphics skill reads the ref strip and animation for mapped graphic shots and overlays; the plan skill's mapped mode types `AI_VIDEO` with `generate.preset` from `ai_preset` when the ref leads with `ai_video`. `PORTING.md` logs both skill changes.
- [ ] The review page shows a graphic ref's reveal and speed, and the shot's `generate.preset` (`test_review.py`).

Global
- [ ] `bun run typecheck` and `bun run lint` pass; `pytest tools/match/tests` passes.
- [ ] End-to-end on the user's PC (needs `assets/` and the local GPU): the first-minute harness reruns with M6 and reports describe cost, validator pass, and the new score next to the M5 numbers in the experiment README.

# Part 4 — Characters and talking shots (M7)

Decided with the user on 2026-10-02, with a same-day deadline, so M7 reuses what exists and adds as little as possible. Parts 1–3 still apply.

## Goal

Let a video be made largely or wholly of AI-generated shots, realistic people or cartoon characters, that stay on-model from shot to shot and can speak the voiceover with lip-sync. All of it runs free on Kaggle's GPUs through the lanes the repo already has.

It adds two things on top of `tools/genvideo` (AI video) and `tools/genchar` (character design):
1. **On-model keyframes from the character's LoRA.** genchar already designs a character, culls an on-model set, trains an SDXL LoRA on Kaggle (`train`) and renders the character in new scenes with it (`render`). M7 connects that lane to a session. `genchar render --session` turns every plan shot naming the character into a keyframe in the session's look; genvideo then generates the shot image-to-video from that keyframe. Without a trained LoRA, the picked design (`ref.png`) is the seed instead.
2. **Lip-sync for talking shots.** A shot marked as talking gets its generated clip lip-synced to that shot's slice of the voiceover.

## What other projects do, and what applies here

- **OpenMontage** ([calesthio/OpenMontage](https://github.com/calesthio/OpenMontage), AGPL-3.0):
  - Runs Wan 2.2 through ComfyUI 4-step workflows (`tools/_comfyui/workflows/wan22-*-4step.json`) on a capable GPU.
  - Paid Kling for avatars.
  - Wav2Lip or MuseTalk for lip-sync (`tools/avatar/lip_sync.py`).
  - SVG-rigged GSAP puppets for its cartoon pipeline.
  - Its split is the one taken here: a video model makes the shot, a separate lip-sync model makes it talk. No code is copied (AGPL).
- **Wan 2.2 / InfiniteTalk / Wan S2V** are bf16-native. The repo's own registry already measured Wan 2.2 5B on Kaggle (`tools/genvideo/run.py`, `wan5b`): T4 and P100 have no native bf16, so it falls back to fp16 and "crawls". InfiniteTalk (on Wan 2.1 14B) has the same problem, so it is out.
- **HunyuanVideo 1.5** (`hunyuan`, `hunyuan-hq`), fp16-native and step-distilled, is the registry's "best quality that still fits a free T4". It stays the video model.
- **Lip-sync on a 16 GB T4:**
  - LatentSync 1.6 needs 18 GB, so it doesn't fit.
  - **LatentSync 1.5** needs ~8 GB in fp16 and is the default ([bytedance/LatentSync](https://github.com/bytedance/LatentSync)).
  - MuseTalk 1.5 (~4 GB) is the named alternative if LatentSync fails on the T4 ([TMElyralab/MuseTalk](https://github.com/TMElyralab/MuseTalk)).
  - Both repaint the mouth of an existing clip of a face (video-to-video). They are strongest on realistic faces and weaker on flat cartoons.

## Non-goals / out of scope

- Style LoRAs and LoRAs for the video model (HunyuanVideo 8.3B is too large to train on a free T4). The character LoRA is on the image model (SDXL), which genchar already trains.
- Wan 2.2, InfiniteTalk or any bf16 model on Kaggle's free GPUs.
- SVG/GSAP puppet characters.
- Two characters speaking in one shot, or one shot's speech split between characters.
- Lip-sync quality guarantees on flat cartoon faces: it is attempted, and a failure keeps the silent clip.
- Changing render: talking clips arrive through `assets_progress.jsonl` like every other generated clip.

## Files & interfaces involved

Changed (v2 copies; each logged in `PORTING.md`):
- `tools/genchar/run.py`:
  - A `realistic` model entry (an fp16 photoreal SDXL finetune, chosen at implementation from those that load in diffusers fp16), beside `animagine` and `sdxl`.
  - `pick` also copies the chosen variation's image to `characters/<name>/ref.png`, the fallback seed.
  - `render --session sessions/<id>`: the scenes are that session's plan shots whose `visual.generate.character` is this character. Each gets a prompt of the trigger, the character's `desc`, the shot's `visual.desc` and the session's `look_style`, keyed `<session>__s<n>`. `fetch --mode render` lands them as `characters/<name>/render/<session>__s<n>.png`. Existing `render --prompts` use is unchanged.
- `tools/genvideo/run.py`:
  - **Character seeding:** a shot whose `visual.generate.character` is `<name>` is generated image-to-video from its LoRA keyframe `characters/<name>/render/<session>__s<n>.png`, else from `characters/<name>/ref.png`, else text-to-video with the character's `desc` (scaled and cropped like `attach_seed_images`, ahead of any `--seed-from-assets` frame). The prompt gets the session's `look_style`. The push report says which seed each shot used. `--seed-from-assets` never seeds a character shot from a stock frame (it would replace the face); a talking shot with no spoken line is not lip-synced.
  - **Lip-sync step:** after generation, every shot with `visual.generate.talk: true` is lip-synced on the same Kaggle run with LatentSync 1.5, against that shot's slice of `audio.wav`. The slice is cut locally with ffmpeg and uploaded with the job. The synced clip is the one `apply` writes; a failed sync keeps the silent clip and records why.
  - New CLI flag `--lipsync latentsync|off` (default `latentsync`). MuseTalk 1.5 stays the named next option if LatentSync proves unusable on Kaggle; it is not built.
  - The LatentSync setup in the notebook (clone, requirements minus torch, `ByteDance/LatentSync-1.5` checkpoints, `scripts.inference` with `configs/unet/stage2.yaml`) follows the upstream README and is unverified until the first Kaggle run. Any failure there is recorded per shot and keeps the silent clip.
- `.claude/skills/plan/SKILL.md`: when `requirements.look` is set, AI shots carry `generate.character` (when a named character is on screen) and `generate.talk: true` (when that character says the line).
- `.claude/skills/ai-video/SKILL.md`: documents `character`, `talk` and `--lipsync`.
- `tools/requirements` (schema) and the `requirements` skill: optional `look: realistic|cartoon|anime` and `look_style` (free text, e.g. "flat bold-outline yellow-skinned sitcom cartoon").

Per-character files: `characters/<name>/ref.png` (new), next to genchar's existing outputs.

## Key decisions & tradeoffs

1. **Reuse the lanes.** Video stays `hunyuan` (or `hunyuan-hq` for hero shots) and character design stays genchar. M7 adds a seed image and a lip-sync pass to the existing Kaggle job, not a new lane or service.
2. **Consistency from the character LoRA, through keyframes.** The LoRA lives on the image model (SDXL, trainable on a free T4 and already wired in genchar), not on the video model. Each shot's keyframe is rendered on-model by the LoRA in that shot's pose and setting, and the video model only adds motion from it. This is the standard keyframe-then-animate route, and it holds identity better than one `ref.png` reused for every pose. `ref.png` stays as the fallback for a character without a trained LoRA. Per character, the once-off cost is genchar's existing explore → pick → sheet → cull → train (one Kaggle training run). Per session, it costs one render run for the keyframes before the video run.
3. **Generate first, then lip-sync.** HunyuanVideo makes the motion and acting; LatentSync 1.5 repaints only the mouth to the line. One Kaggle run does both, so a talking shot costs one queue wait.
4. **The look is a session setting.** `look` and `look_style` live in `requirements.json`:
   - genchar uses them to pick its model when a character is created (realistic → `realistic`, anime → `animagine`, cartoon → `sdxl`), and `explore --look-style` folds `look_style` into the character's `desc`, so the design sheet, the LoRA captions and every render carry it; the LoRA is trained on that model, so the look is baked into the character.
   - genvideo appends `look_style` to every prompt.
   Realistic and cartoon videos therefore use the same code.
5. **Failures degrade, never block.** A shot whose generation fails keeps its stock fallback (as today). A talking shot whose lip-sync fails keeps its silent generated clip. Both are flagged on the review page (Part 3, M6.5).

## Edge cases

- **The named character has no LoRA keyframe for the shot:** use `ref.png`. With no `ref.png` either, generate text-to-video with the character's `desc` from genchar's `character.json`. The report names the seed used.
- **The LoRA keyframe drifts off-model:** that is the existing genchar consistency check (`render` is described as "the consistency test"). The user can re-render the shot with another seed before the video run.
- **The talking shot's line is empty or under 0.5 s:** no lip-sync.
- **LatentSync finds no face** (wide shot, back of head, a flat cartoon it can't read): keep the silent clip and record "no face".
- **The voiceover slice is longer than the generated clip** (HunyuanVideo makes ~5 s): render's fill rule (Part 3, decision 11b) already slows or repeats the clip. Lip-sync runs on the filled length, so the cut audio slice matches what plays.
- **Kaggle out of quota:** as today, the shot keeps its fallback and the job can be re-pushed.

## Milestones

- **M7.1 Look, LoRA keyframes and character seeding** (today): `look` fields, genchar `realistic` model, `ref.png`, `render --session`, genvideo seeding (keyframe → ref.png → text), plan and ai-video skill text.
- **M7.2 Talking shots** (today if time allows): LatentSync 1.5 pass in the genvideo job, audio slicing, `--lipsync`, fallback.

## Acceptance criteria

M7.1
- [ ] `genchar pick` writes `characters/<name>/ref.png`, a copy of the chosen variation (unit test on a fake explore dir).
- [ ] `genchar render --session ... --dry-run` builds one job per plan shot naming the character, keyed `<session>__s<n>`, with the trigger, the character's `desc`, the shot's `desc` and `look_style` in the prompt (unit test, no Kaggle).
- [ ] `genvideo push --dry-run` on a plan with `generate.character` seeds each shot from its LoRA keyframe when present, else `ref.png`, else text-to-video, at the model's size; the prompt carries `look_style` and the report names each shot's seed (unit tests for all three cases, no Kaggle).
- [ ] `requirements.json` accepts `look`/`look_style`, and the plan and ai-video skills document `character`/`talk`. `PORTING.md` logs every v2-copy change.

M7.2
- [ ] `push` cuts each talking shot's voiceover slice with ffmpeg and ships it with the job; the generated notebook runs LatentSync 1.5 after generation for exactly those shots (dry-run test inspects the job).
- [ ] `apply` writes the synced clip when present, else the silent clip with a recorded reason (unit test on fake Kaggle output).
- [ ] `--lipsync off` produces the M7.1 behaviour unchanged.

Global
- [ ] `pytest tools/match/tests` plus the new genvideo/genchar tests pass; `bun run lint` passes.
- [ ] User check on Kaggle: one realistic and one cartoon character (trained through genchar), three shots each with one talking. Record the minutes per shot and whether the face holds across shots. The user supplies the style references for both characters.

# Part 5 — Look references (M8)

## Goal

Style reference images are a real input to the pipeline. The user drops images that show the world (streets, colour, light) and the characters (faces, body proportions). Those images steer every generated image directly. They are not only summed up in a hand-written `look_style` line. A session with no reference images behaves exactly as in Part 4.

The refs reach generation in two ways (user decision: both):
1. **Pixels.** An SDXL IP-Adapter in InstantStyle mode feeds the images into every SDXL generation:
   - genchar explore, sheet and render (so they also reach the LoRA through its training set);
   - a new styled-keyframe pass in genvideo.
2. **Words.** Haiku reads the same images and writes `look_style` (when the user hasn't written one). Prompts and genvideo's text fallback then describe the same look.

## Non-goals

- Reproducing the identity of a character in a ref (e.g. Miles or Gwen). Prompts keep "original character". The refs give style and structure, not a person.
- Style images going directly into a video model. No free T4 video model takes one; the look reaches video through styled keyframes (decision 5).
- Training a style LoRA from the refs. The character LoRA is trained on the styled sheet as before.
- Reference video clips. The inspo video is Part 3's job.
- Editing or cropping images in the editor. Drop, set a role, delete.

## Files and interfaces

- **`sessions/<id>/look_refs/`** holds the images, normalised on add to JPEG with a 1024 px long side.
- **`sessions/<id>/look_refs.json`** is the index:
  ```json
  {"images": [{"file": "r01.jpg", "role": "world|character", "role_source": "haiku|user", "note": "<Haiku's one-line read>"}],
   "look_style_auto": "<Haiku's line>", "described": "<sha of the image set>"}
  ```
- **`tools/look/refs.py`** (new; system python, like `tools/match`):
  - `add --session <dir> <files...>` copies and normalises images and appends them to the index. Unreadable files are rejected and named.
  - `role --session <dir> --file r01.jpg --role world|character` sets `role_source: user`.
  - `remove --session <dir> --file r01.jpg`.
  - `describe --session <dir>` makes one Haiku call through `tools/match/describe.py`'s lean `claude -p` with inline images. It returns a role and a note per image, and a `look_style` of at most 30 words (SDXL reads about 75 tokens of prompt, and the trigger, desc and scene share them). It never overwrites a role a user set, and it writes `requirements.look_style` only when that is empty. Cached on the image-set hash.
  - `resolve(session, character=None, purpose)` returns the images to use: character refs for `design`, character plus world for `scene`, world for `keyframe`. A character's own `characters/<slug>/style_refs/` replace the session's character refs. At most 4 per role, in index order.
- **`tools/genchar/run.py`:**
  - `explore`, `sheet` and `render` take `--session` (render already does) and `--style-refs <dir>`. `--style-refs` copies the images into `characters/<slug>/style_refs/` once, so they travel with the character to later videos.
  - `--ref-strength <0..1.5>` (default 1.0) scales the adapter.
  - The refs are base64-embedded in the notebook. The notebook loads the IP-Adapter only when refs are present.
- **`tools/genvideo/run.py`:**
  - When the session has refs and the model has an image-to-video pipeline, every AI slot that is still unseeded after character seeding gets a `keyframe` job.
  - The notebook first renders those keyframes with SDXL plus the IP-Adapter at the video model's size. SDXL here is the `look`'s genchar model; `sdxl` when `look` is empty.
  - It then frees the SDXL pipeline and generates video image-to-video from them.
  - The seed report says `styled_keyframe`.
- **Backend:**
  - `server/look.ts` (new) and routes in `server/index.ts`:
    - `GET /_look/:id` returns the index;
    - `POST /_look/:id/add` takes a raw image body plus an `x-filename` header and runs `refs.py add`;
    - `POST /_look/:id/role`, `POST /_look/:id/remove` and `POST /_look/:id/style` (sets only `requirements.look_style`, since the full requirements update re-validates topic, style and duration).
    - The images are served by the existing session-file route (`/api/sessions/<id>/look_refs/<file>`).
  - `server/actions.ts` gets a `look-describe` action (stage `style`).
- **Editor:** `apps/editor/src/esta/panels/look-panel.tsx` (new), on the Style stage:
  - a drop zone and a thumbnail grid;
  - a per-image World/Character toggle and delete;
  - a "Describe" button;
  - the resulting `look_style`, editable, saved through `/_look/:id/style`.
- **Skills:**
  - `requirements` step 4c: images dropped in chat go through `refs.py add`, then `describe`.
  - `ai-video`: documents `--session`/`--style-refs` on genchar and the keyframe pass.
  - Both are logged in `PORTING.md`.

## Key decisions

1. **Both pixels and words** (user). The IP-Adapter carries what words can't (the halftone texture, the painted reflections). The words keep the prompt and the text fallback consistent with the pixels.
2. **Roles: world and character** (user). Haiku proposes a role and the user can override it. Character refs steer design (explore and sheet). World and character refs together steer scenes (render). World refs steer non-character keyframes. This stops city colour from bleeding into a character sheet as its background.
3. **Style + structure** (user). InstantStyle scales the style block (`up.block_0`, middle attention) at 1.0 and the layout block (`down.block_2`) at 0.6, both multiplied by `--ref-strength`.
   - Layout borrows composition and proportions, such as the turnaround's long limbs.
   - The cost is a higher chance of copying content, so prompts keep "original character" and the user check looks for it.
   - Both numbers are unverified until the first Kaggle grid. They are the knobs to tune.
4. **Adapter:** `h94/IP-Adapter`, `sdxl_models/ip-adapter_sdxl.bin`, with the image encoder from the same repo's `sdxl_models/image_encoder`, in fp16 on the T4. It works on every genchar model, because animagine, sdxl and RealVisXL are all SDXL bases. Several refs of one role go in as one multi-image input.
5. **Every AI shot gets a styled keyframe** (user). Video models on a free T4 take a start image, not a style image. So every AI shot, character or not, starts from a still drawn in the look.
   - Precedence: character seed (LoRA keyframe, then `ref.png`) first, then the styled keyframe, then the `--seed-from-assets` stock frame.
   - When refs exist, stock seeding only fills what's left: no shots, if the model has an image-to-video pipeline.
   - An image-to-video-only model already needs every slot seeded; keyframes satisfy that.
   - A model with no image-to-video pipeline skips the pass and the report says so.
6. **Shared refs, per-character override** (user). Characters use the session's character refs unless they have their own `style_refs/`, which win and persist with the character.
7. **Failures degrade, never block.**
   - If the IP-Adapter download or load fails on Kaggle, the run continues without refs. It records `ref_error` in results and prints it.
   - If Haiku fails, roles stay `world` and `look_style` stays as it was.
   - If a styled keyframe fails, that shot falls back to the next seed in the precedence order.

## Edge cases

- **No refs:** the notebooks contain no IP-Adapter code path and genvideo builds the same slots as before (tested by diffing the dry-run output).
- **Only world refs, or only character refs:** a purpose with no images of its role uses the other role's images rather than none.
- **More than 4 images in a role:** the first 4 are used, and the push output says which.
- **A user-written `look_style`** is never overwritten by `describe`. The auto line is still kept in `look_refs.json` for reference.
- **The same image added twice:** skipped, by content hash.
- **Non-image or corrupt files** are rejected by `add` with the reason. Accepted formats: png, jpg, webp.
- **Notebook size:** refs are embedded at up to 768 px, JPEG quality 85, and still count toward genvideo's 4 MB `MAX_NOTEBOOK_BYTES` check.
- **The image set changes after `describe`:** the hash differs, so the next `describe` reruns. Stale roles for removed files disappear with the files.

## Milestones

- **M8.1 Ingest and describe:** `tools/look/refs.py`, the index, Haiku roles and `look_style`, and the requirements skill.
- **M8.2 Pixels:** the genchar IP-Adapter path with `--session`/`--style-refs`/`--ref-strength`, and the genvideo styled-keyframe pass.
- **M8.3 Editor:** backend routes, the `look-describe` action, and the Look card on the Style stage.

## Acceptance criteria

M8.1
- [ ] `refs.py add` normalises png/jpg/webp to JPEG with a 1024 px long side, skips duplicates and rejects a non-image with its reason (unit tests).
- [ ] `refs.py describe` with a mocked `claude` sets roles and `look_style_auto`. It leaves user-set roles and a non-empty `requirements.look_style` untouched, fills an empty one, and makes no call when the image-set hash is unchanged (unit tests).
- [ ] `resolve` returns character refs for design, character plus world for scene and world for keyframe. It applies the per-character override, the fallback when a role is empty, and the cap of 4 (unit tests).

M8.2
- [ ] `genchar explore|sheet|render --session ... --dry-run` with refs embeds the right images per purpose, and the notebook loads `h94/IP-Adapter` with the InstantStyle scales times `--ref-strength`. Without refs, there is no IP-Adapter in the notebook (unit tests).
- [ ] `--style-refs <dir>` copies the images to `characters/<slug>/style_refs/`, and they override the session's character refs (unit test).
- [ ] `genvideo push --dry-run` with refs gives every unseeded AI slot a keyframe job and reports `styled_keyframe`, with character seeds still winning. With no refs, its slots match the pre-M8 output. With a model that has no image-to-video pipeline, it skips the pass and says so (unit tests).
- [ ] The notebooks parse as Python (`ast.parse`) with and without refs.

M8.3
- [ ] `bun run typecheck` and `bun run lint` pass. The `/_look` routes add, list, set a role, remove and serve an image on a scratch session (manual curl check).
- [ ] The Style stage shows the Look card: dropped images appear with a role toggle, and Describe fills an editable `look_style`.

Global
- [ ] The existing pytest suites still pass. `PORTING.md` logs the skill and v2-copy changes.
- [ ] User check on Kaggle with the five Spider-Verse-style refs:
  - an explore grid of an original character shows the painted comic look and long-limbed proportions without reproducing Miles or Gwen;
  - one non-character AI shot's keyframe matches the neon city look.
  - Tune the `--ref-strength` and InstantStyle scales from that grid.
