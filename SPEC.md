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
