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
- New pipeline capabilities beyond v2. `post` and `profile-update` stay unbuilt.
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
- [ ] `bun install` then one documented command starts the editor and backend. Opening `http://localhost:3000` shows the session list. Both commands are recorded in CLAUDE.md "Tech stack & commands".
- [ ] `diff -r` of v2 `tools/` vs v3 `tools/` shows only the excluded files and the changes listed in `PORTING.md`.
- [ ] Every v2 skill is present in `.claude/skills/`, and `/requirements`, `/plan` etc. are invocable from terminal Claude Code in the v3 repo.
- [ ] Creating a session from the UI writes `sessions/<slug>-<date>/requirements.json` with the same fields as v2's requirements skill.
- [ ] "Import from v2" copies `do-alphas-even-exist-2026-09-16` in, and its stage rail state matches `python tools/pipeline/conductor.py next --session sessions/<id>`.
- [ ] A stage whose `needs` are missing is locked and shows the missing file names. Force unlocks it and writes the override into `pipeline.json`.
- [ ] Approve on requirements/script/tagged-script/plan is required before the next stage unlocks, and is persisted in `pipeline.json`.
- [ ] Starting timestamps shows a running job in the Jobs panel with a live log; cancel kills the process; retry restarts it.
- [ ] The chat panel can run "what runs next?" and gets the same answer as the conductor CLI.

M2
- [ ] Every field and action in v2's planner (including Rewrite and the structural commands split/merge/add overlay) works in the React panel and produces the same `plan.json` as v2's page for the same input.
- [ ] Every picker action (candidates, pick, refetch, sources, jobs) works in the React panel, and picking writes `assets_progress.jsonl` as v2 does.
- [ ] Selecting shot N in the planner selects it on the timeline, and vice versa.

M3
- [ ] After the final render pass, the editor shows the native OpenCut project with no `/esta-seed` step. Clip count, track mapping and media match `from_openreel.py`'s mapping for the same session.
- [ ] Re-running render updates the open timeline without a page reload.
- [ ] In the chat panel, "make shot 3 two seconds" resizes the correct clip live (verified on a crossfaded session).
- [ ] `get_frame` from chat returns a composited frame of the current timeline.
- [ ] Editing `plan.json` from the terminal while the planner is open: with no local edits it reloads silently; with local edits the Keep mine / Take theirs banner appears.
- [ ] An exported video's source references are originals, not proxies (checked via ffprobe resolution against the originals).

M4
- [ ] `PARITY.md` lists every v2 `apps/studio` feature with a status, and every "dropped" entry is approved by the user.
- [ ] Every "port" entry is usable in the editor (a manual check per row, ticked in `PARITY.md`).

Global
- [ ] Typecheck passes for `apps/editor` and `server/`, and lint passes for the code ESTA owns (`apps/editor/src/esta/`, ESTA routes, `server/`, `scripts/`); vendored OpenCut code keeps its upstream lint baseline (see `PORTING.md`). Commands recorded in CLAUDE.md.
- [ ] An end-to-end run of `standard-vo` on a short test topic reaches an exported video entirely from the UI, without touching the terminal.
- [ ] The same end-to-end run using the `found-audio-collage` template reaches the Edit stage.
