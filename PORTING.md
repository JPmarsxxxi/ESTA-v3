# PORTING

Every deviation from a verbatim copy of ESTA-v2, and every change to vendored OpenCut code outside `apps/editor/src/esta/`. If it isn't listed here, it's a straight copy.

## Copied from ESTA-v2

| What | Status |
|---|---|
| `tools/**` | Verbatim except the integration fixes listed below. `diff -r` against v2 shows only the excluded `asset-server.mjs`, `chat-bridge.mjs`, `planner/`, `picker/` (and `__pycache__`) plus those fixes. |
| `.claude/skills/**` | All 14 ESTA skills verbatim, merged with the StyleSeed skills already in v3. v2's `humanizer` replaced v3's; the leftover files of v3's clone (`.git/`, `LICENSE`, `README.md`, `WARP.md`) were moved out so the folder matches v2 exactly. |
| `.claude/settings.json` | Verbatim (the `esta` env and Colab MCP prompt hooks), so terminal Claude Code behaves as in v2. |
| `.mcp.json` | Verbatim. `tools/opencut/mcp-server.mjs` didn't move, and the backend keeps port 8787, so no path or URL changes. |
| `config.example.yaml`, `environment.yml`, `setup.ps1`, `requirements.txt`, `editing-principles.md`, `motion-design.md`, `sound-design.md`, `voice_samples/`, `characters/`, `profile/`, `notebook/` | Verbatim. |
| `config.yaml` | Also copied (gitignored). SPEC lists only the example, but the tools read their API keys from the real file. |
| `CLAUDE.md` | v2's Skills, Pipeline rules, Conductor, Conda, Background steps, Session folder, User profile and LLM provider sections merged verbatim under "Pipeline (from ESTA-v2)". v2's "Browser surfaces" and "Setup" sections are replaced by v3's commands and a rule mapping v2 server/URL references to v3. |

### Integration fixes to `tools/`

| File | Change | Why |
|---|---|---|
| `tools/opencut/from_openreel.py` | Video and audio elements carry `clipId` (the OpenReel clip id); video elements also carry the clip's `transform`; each caption phrase carries its `words` ([start, end] from the phrase start) and render's `highlight` colour. | The main track's `transitions` name clips by id, so without it the emitter can't tell which neighbouring pair a crossfade belongs to. Without the transform, composite panels land full-frame and every clip loses render's cover fit. Without the word timings, render's karaoke captions can only be flat phrases. |
| `tools/opencut/mcp-server.mjs` | The never-acknowledged error reads `out.delivered` (it referenced an undefined `delivered`, so it threw instead of reporting). Its hints point at the session's Edit stage instead of `/esta-seed`. | A bug in v2, and the seed page no longer exists. |

## Backend (`server/`, replaces `asset-server.mjs` + `chat-bridge.mjs`)

Every v2 route is kept with its v2 behaviour, on one port (8787). Differences:

- **One port.** The chat routes moved from :8788 onto :8787.
- **`/_sessions/create`** still creates a bare folder for v2's `{topic}` body. When the requirements fields are sent (the v3 form), it also validates them with `tools/requirements/validators.py` and writes `requirements.json` (the `schema.py` fields), `conversation.jsonl`, and `script_uploaded.txt` for an uploaded script.
- **`/_sessions/list`** is unchanged. `?all=1` also lists sessions that haven't been rendered yet, for the session list page.
- **`/_plan` and `/_picker` HTML pages are not served.** Their APIs are unchanged; the pages become React panels in M2.
- **Chat:** the headless session gets the `esta-opencut` MCP server through `--mcp-config` and pre-allows its tools (`--allowedTools mcp__esta-opencut`): `--print` runs skip project `.mcp.json` servers that were never approved. v2 opened a chat by holding `/chat/stream` open. `/chat/stream` still works; the UI uses `POST /chat/open` plus the multiplexed `/_events?chat=<id>` stream. Added `/chat/status` (liveness) and kept v2's `/chat/interrupt`.
- **Live edit:** `/_cmd` also broadcasts on `/_events` (channel `cmd`). `delivered` counts both kinds of subscriber.
- **Media:** files are served under both `/api/sessions/<id>/...` (v2's URL form) and the bare `/<id>/...` path the asset-server saw behind Vite's proxy.
- **CORS** also allows the `X-Esta-Client` header. The editor tags its own writes with it, so file-change events can tell a tab's own save from an external write. The tab owns exactly the file state its write produced (mtime and size, recorded right after the write), so a terminal or chat write a moment later is still reported as external.
- **New routes:**
  - `/_events` (the one multiplexed SSE stream per tab)
  - `/_pipeline/:id` (state, plus `approve`, `force`, `template`, `flow`, `run`)
  - `/_jobs` (list, log, cancel, retry; live updates on `/_events`)
  - `/_files/:id` (SSE) and `/_files/:id/list`
  - `/_sessions/import`
  - `/_preflight`
  - `/_opencut/:id[?originals=1]`: runs `from_openreel.py` into `.esta/opencut/` and returns its intermediate, with each media file's size and mtime (or `missing`). It adds `pending`: the early render pass's stream-pending shots (`media-shot-N` with no file), which `from_openreel.py` drops. Each one that has landed since render ran is filled in from `assets.json` plus `assets_progress.jsonl`, merged the way render's `_load_asset_shots` merges them, with the same proxy preference.
- **Jobs** are spawned detached, with their output written to `.esta/jobs/<id>.out` rather than piped to the backend, so a Kaggle run survives a backend restart (every edit under `server/` in dev). The live log is rendered from that file. On restart, a job whose process died is marked `interrupted`; one still running has its log rebuilt from the file and followed, and resolves to done or interrupted from disk when it exits.

## Pipeline state

- **Approvals and overrides** are stored under a new `ui` key in `pipeline.json` (`ui.approvals.<checkpoint>`, `ui.overrides.<step token>`). `conductor.py` round-trips unknown keys.
- **Approving requirements with a template** runs `conductor.py build` (this is how the UI replaces the conductor skill's template choice). Approvals already given survive a template switch. Custom orders go through `validate_flow.py` and are rejected with its message.
- **Import from v2:** the checkpoints whose artifacts already exist (`requirements.json`, `script.md`, `script.tagged.md`, `plan.json`) are recorded as approved with `by: "import"`, because v2 passed them in conversation. A v2 session without `pipeline.json` gets the canonical `standard-vo` rails (`conductor.py build`) at import, so those approvals have somewhere to live.
- **`skip_scriptwriter: true`** marks the scriptwriter step skipped even if `pipeline.json` wasn't `mark`ed, matching CLAUDE.md ("skip skills explicitly disabled by earlier steps").
- **Voice profiler:** it re-enters the flow when `example_scripts` becomes a list after `pipeline.json` was built (SPEC edge case).
- **Stage skill buttons** run `claude -p` with the user's default model, not Haiku. Haiku is reserved for the planner's Rewrite and structural commands, as in v2. Skills like plan and scriptwriter need the stronger model. Each job gets a headless preamble: no questions, foreground commands, stop at approvals.

## Vendored OpenCut (`apps/editor/`)

Source: `C:\Users\User\opencut-classic` at `cf5e79e` (upstream `github.com/opencut-app/opencut-classic`), `apps/web`. `apps/desktop` is not vendored.

`rust/` (the compositor, effects and masks behind the `opencut-wasm` package) is vendored from the same commit since M4, because new effects need new shaders compiled into it. The root `Cargo.toml` is a trimmed copy of upstream's workspace without `apps/desktop`; `Cargo.lock` is upstream's. `bun run build:wasm` (`scripts/build-wasm.ts`, needs `rustup target add wasm32-unknown-unknown` and `cargo install wasm-pack`) builds it into `packages/opencut-wasm/`, which is committed and linked as a bun workspace package (`"opencut-wasm": "workspace:*"` in the root and editor `package.json`), so running ESTA needs no Rust toolchain. An unmodified build reproduces the published 0.2.10 package (3,035,379 vs 3,037,899 bytes after `wasm-opt -O`, a different binaryen build). Root `eslint.config.mjs`, `eslint/`, `biome.json`, `tsconfig.json` and `bun.lock` were copied alongside it.

### Mount points (OpenCut files changed to host ESTA)

| File | Change |
|---|---|
| `src/app/page.tsx` | OpenCut's marketing landing page is replaced by the ESTA session list (`@/esta/home`). |
| `src/app/esta/[session]/page.tsx` | New route: the stage workspace (`@/esta/workspace`). |
| `src/components/providers/editor-provider.tsx` | `EditorRuntimeBindings` is exported, so the workspace's embedded editor reuses OpenCut's shortcut, ripple and unsaved-changes wiring instead of copying it. |
| `src/timeline/components/timeline-element.tsx` | Each clip's root node carries `data-element-id`. | Selecting a shot from the planner or picker scrolls its clip into view; OpenCut only auto-scrolls during playback. |
| `src/components/editor/export-button.tsx` | The export popover calls `exportBlock` (`src/esta/opencut/export-guard.ts`) and shows why export is blocked instead of the export controls. | Covers every export path: the full-page editor's header and the Edit stage's Editor project panel both use this popover. |
| `src/components/editor/export-button.tsx`, `src/export/index.ts`, `src/core/managers/renderer-manager.ts`, `src/services/renderer/scene-exporter.ts` | The export popover opens with ESTA's Preset picker (`src/esta/opencut/export-preset-section.tsx`); a preset hides OpenCut's Format and Quality sections and passes its size, fps and video/audio bitrates. `ExportOptions` gains optional `width`, `height`, `videoBitrate` and `audioBitrate`; the exporter scales each rendered frame to the output size when it differs from the project's, and uses the given bitrates over its quality ladder. | Export presets (M4). OpenCut always exported at the project size with a fixed bitrate per quality level. |
| `src/effects/definitions/color.ts`, `src/effects/definitions/index.ts` | New Color effect (brightness, contrast, saturation, hue) registered next to Blur. | PARITY P1: matching stock clips from different sources. Renders with the `color-adjust` shader below. |
| `src/effects/definitions/grade.ts`, `src/effects/definitions/index.ts`, `src/effects/types.ts`, `src/effects/components/effects-tab.tsx`, `src/services/renderer/compositor/frame-descriptor.ts` | New Grade effect. An effect pass may name a lookup-table texture (`EffectPass.lut`); a definition may bring its own editor (`EffectDefinition.panel`, shown under its param fields); the frame descriptor adds the textures its passes name (`src/esta/opencut/grade-textures.ts`). | Colour grading and LUTs (M4); see below. |
| `src/components/editor/panels/assets/index.tsx` | The Transitions tab (an upstream "coming soon" stub) renders ESTA's `TransitionsView`. | OpenCut has no transitions; see M4 below. |
| `src/services/renderer/resolve.ts`, `src/services/renderer/nodes/text-node.ts` | The resolved text state keeps its `localTime`; the text node draws through ESTA's `drawStyledText` (`src/esta/opencut/text-style.ts`) instead of calling `drawMeasuredTextLayout` once: OpenCut's background, then ESTA's shadow and outline, then the fill, word by word for captions carrying `esta.karaoke` timings. | Karaoke captions and text outline/shadow (M4). OpenCut draws text on a 2D canvas in TypeScript, so this needs no wasm change. |
| `src/params/registry.ts`, `src/components/editor/panels/properties/registry.tsx` | Text elements get ESTA's outline and shadow params (`src/esta/opencut/text-style-params.ts`), listed in the Text tab after OpenCut's background fields. The Audio tab of an audio clip also shows ESTA's `DuckingSection` under the volume fields. | Text outline and shadow, and auto-ducking (M4). |
| `src/app/layout.tsx` | Removed the BotID client, the dev-only React Scan overlay (it covered the chat panel) and the Databuddy analytics script. The app is local-only and single-user. |

### Other changes

| File | Change | Why |
|---|---|---|
| `package.json` | Renamed `@esta/editor`; added `remark-gfm` (chat markdown tables) and `bun-types` (the missing dependency of `@types/bun`); `opencut-wasm` points at the workspace package built from `rust/`. | |
| `tsconfig.json` | `"types": ["bun"]` | TypeScript 6 no longer loads `@types/*` automatically, so the `bun:test` imports failed to typecheck. |
| `src/types/css.d.ts` | `declare module "*.css"` | TypeScript 6 checks side-effect imports (`import "./globals.css"`). |
| `src/export/defaults.ts` | Export quality `very_high` | Carried over from v2's OpenCut spike, where exports are finals for a monetised channel. |
| `src/services/storage/migrations/runner.ts`, `v1-to-v2.ts`, `src/stickers/providers/index.ts` | Positional calls changed to the object-param signatures (`new IndexedDBAdapter({...})`, `adapter.set({ key, value })`, `registry.register({ key, definition })`). | Upstream's half-finished refactor: these calls failed typecheck and would break storage migrations at runtime. |
| `src/actions/keybindings/persistence.ts` + its test | Deleted. | Dead upstream code: nothing imports it, and it imports helpers that no longer exist. The app uses `keybindings-store.ts`. |
| `src/timeline/__tests__/update-pipeline.test.ts`, `src/timeline/placement/__tests__/resolve.test.ts` | Compare against `MediaTime` values instead of bare numbers. | Upstream type errors. These tests still fail at runtime, as they do upstream, because wasm doesn't initialise under `bun test`. |
| `eslint.config.mjs` | Paths `apps/web` -> `apps/editor`; `next.rootDir`; a Node block for `server/` and `scripts/`. | |
| `apps/editor/.env.local` | Generated with placeholder values by `scripts/dev.ts` when missing. | OpenCut validates auth/DB/Redis env at import time; ESTA never uses them. |
| `next.config.ts` | Rewrites `/api/sessions/*` to the backend. | Session media loads from this origin, so big files don't eat the ~6 connections Chrome allows the backend's host (v2 hit the same limit). |
| `package.json` | Added `remark-gfm`. | The chat panel renders Claude's markdown tables. |

### Not carried over from v2's OpenCut spike

- `src/app/esta-seed/` and `public/esta-import.json`: replaced by the native emitter (below).
- `src/components/providers/esta-cmd-bridge.tsx`: replaced by `src/esta/opencut/bridge.tsx` (below).

## M2 surfaces

- **Planner panel** (`src/esta/panels/planner-panel.tsx`): a port of `tools/planner/index.html`. Same fields, same endpoints, same autosave-on-leave, Ctrl+S, Rewrite and split/merge/overlay commands, and v2's line-identity anchoring so a split doesn't move the user off their shot. The beacon on hard close is a `keepalive` fetch rather than `sendBeacon`: the backend is a different origin, and a beacon can't carry the JSON content type through preflight.
- **Picker panel** (`picker-panel.tsx`): a port of `tools/picker/index.html`, including the full source bank with the plan's prescription starred, background fetch jobs, the generated-graphic override notice, pick-and-advance, and v2's rule that at most one `<video>` exists at a time (created on hover).
- **Script panel** (`script-panel.tsx`, `line-editor.tsx`): a port of v2 `apps/studio`'s `WritingStageView` + `LineEditor` for `script.md` and the talking points in `script_metadata.json`.
- **Tagged-script review** (`tagged-panel.tsx`): new in v3. It gives the audio skill's approval step a surface: the delivery markup with its tags as chips, tag-check, approve, and per-line redo through `expressive --only`.
- **Requirements panel** (`requirements-panel.tsx`) edits `requirements.json` in place through a new `POST /_sessions/:id/requirements`, which runs v2's validators and preserves fields the form doesn't own.
- **Timeline strip and preview** (`shots-panels.tsx`): plan-derived, sharing one selected shot with the planner and picker. The OpenCut timeline joins that shared selection through `opencut/shot-sync.tsx` (M3).

## M3 editor integration

- **Native emitter** (`src/esta/opencut/emit.ts`): the TS module SPEC allows in place of `tools/opencut/emit.py`. It takes `from_openreel.py`'s intermediate from `/_opencut/:id`, so the track mapping, proxy choice and caption chunking stay v2's code, and builds the native project with OpenCut's own builders (`buildElementFromMedia`, `buildTextElement`, `upsertPathKeyframe`, `mediaTimeFromSeconds`). It saves the project as `esta-<session>` and its media into OpenCut's per-project store. A rebuild downloads only files whose size or mtime changed and drops media the new revision no longer uses. The project's background and timeline view survive a rebuild.
  - Trim: `trimStart = inPoint`, `trimEnd = sourceDuration - outPoint`. `speed` becomes `retime.rate`.
  - Placement: OpenCut draws a clip at scale 1 fitted inside the canvas and positions it in pixels from centre. Render's transform (position in frame fractions from centre, scale, `fitMode`) maps onto that; `cover`, render's default, becomes a scale factor from the clip's real aspect, and render's scale keyframes (Ken Burns, zoom) get the same factor. Composite panels (`contain`) keep their exact position and scale.
  - Volume: OpenReel's linear gain becomes OpenCut's dB (`20·log10`, 0 -> -60 dB).
  - Video lanes keep render's `muted` on the track and turn off `isSourceAudioEnabled`, so clip audio never competes with the voiceover.
  - Keyframes: `scale.x/y`, `position.x/y`, `rotation`, `opacity` map to OpenCut's `transform.*` and `opacity` paths, linear.
  - Crossfades: OpenCut has no transitions. As in v2's spike, alternate clips move to a `Main B` video lane above the main track. The earlier clip of each pair runs on past the cut by the fade length (clamped to the source it has left), and whichever of the two is on top fades. Cut points stay where the plan put them. Track order, top first: Captions, Graphics/Overlay, Main B, main.
  - Clips whose media file is missing on disk are left out and listed in the panel.
  - Pending shots: a landed one is added under render's own media id (`media-shot-N`, so the final pass reuses the download), with its source duration probed in the browser because render hasn't ffprobed it yet. The rest become a "Shot N: fetching" card, generated in the browser. Both join the lane render put the clip on, and the crossfade split. Only `media-shot-N` shots hydrate early. Composite slots and `<n>-overlay` graphics appear when render next runs, because render only adds those clips once their files exist.
  - Downloads go through OpenCut's upload probe (`processMediaAssets`), so clips get thumbnails as they would from a manual import.
- **Live refresh** (`opencut/host.tsx`): once a session has been built, the project follows render. A file event for `<id>.openreel.json`, `assets_progress.jsonl` or `assets.json` from anything but this tab rebuilds it (debounced 1.5 s, one build at a time, with a trailing rebuild if more arrives mid-build) and reloads it in place, keeping the playhead. Opening the workspace rebuilds too if those files changed since the last build. If the timeline has edits since the last build (OpenCut's undo history, cleared on every load), nothing is overwritten: the Editor project and Editor timeline panels show Keep mine / Take render's. A build is recorded per session in localStorage with the source files' newest mtime.
- **Editor project panel** (`panels/editor-panel.tsx`, in the Edit preset): Build project (proxies, for editing), Build for export (originals, what `from_openreel.py --originals` did), and a link to OpenCut's own full-page editor (`/editor/esta-<session>`). The render skill's `--emit` into the OpenCut clone and its `/esta-seed` step map to these buttons (see CLAUDE.md).

- **Embedded editor** (`opencut/host.tsx`, `panels/opencut-panels.tsx`): OpenCut's preview, timeline, media and properties panels are dockable workspace panels ("Editor ..."), and the Edit preset is Stage/Editor project/Jobs, Preview/Timeline, Properties/Media/Chat. The plan-derived panels are renamed "Shot strip" and "Shot preview". `OpenCutHost` loads `esta-<session>` into OpenCut's singleton `EditorCore` the first time one of these panels is shown and keeps it loaded across stage switches. OpenCut's keyboard shortcuts only listen on the Edit stage, so keys in the planner or script editor never reach the timeline. Rebuilding while the project is open flushes pending autosave, pauses it, rebuilds, and reloads the project in place. Not carried over from OpenCut's editor page: the onboarding dialog, the storage migration dialog, the changelog toast, and paste-to-import.

- **Live edit** (`opencut/bridge.tsx`): the dispatcher for `tools/opencut/mcp-server.mjs`, mounted whenever the session's project is loaded (on any stage). Commands arrive on the `/_events` `cmd` channel; results go back through `/_ack` and `/_frame`. Every 2 s, and 300 ms after any timeline change, it pushes the `/_state` snapshot `get_timeline` returns. That push is also the heartbeat the MCP server checks for a live editor. Snapshot: every track and clip with id, shot number, name, media, start, duration, end, source duration and trim in seconds, volume as linear gain, and which properties are animated.
  - "Shot N" is the Nth clip by start time across the main track and the `Main*` crossfade lanes, as in v2.
  - `update_clip`/`animate_clip` volumes are linear (as the tools describe) and converted to OpenCut's dB. `animate_clip` replaces the property's keyframes; `scale` keys both axes.
  - Edits go through OpenCut's undoable commands, so they are undoable, and they count as local edits for the render conflict banner.
  - `get_frame` renders with OpenCut's own scene builder and canvas renderer at the requested time, downscaled to 540 px on the long side.
  - One editor tab at a time: commands aren't addressed to a session, so two open workspaces would both apply them (v2 had the same limit).

- **Shared shot selection** (`opencut/shot-sync.tsx`): clips keep render's ids, so plan shot N is `clip-shot-N` on whichever lane it sits on, crossfade split included. Choosing a shot in the planner, picker or shot strip selects its clip, moves the playhead to its start (unless playing) and scrolls it into view. Selecting a single shot clip on the timeline selects that shot in the other panels.

- **Conflicts in the editable panels** (M3, SPEC decision 10). External change + no local edits reloads silently; external change + local edits shows Keep mine / Take theirs, and nothing is written either way until you choose.
  - Script, talking points, tagged script (`doc.tsx`): autosave is suspended while the banner is up, and a queued save is cancelled, so Take theirs can't be overwritten a moment later.
  - Planner: saves go per shot, so a change to other shots merges silently (the open form keeps its edits). Only a change to a shot with unsaved edits raises the banner. While it is up, leaving an edited shot holds its edits instead of saving them; Keep mine writes the held shots, Take theirs drops them. Fixed along the way: Take theirs could still save the discarded shot, because the discard flag was reset before the old form unmounted.
  - Requirements: a draft remembers the file it started from. If the file changes before Save, the banner appears and Save waits for a choice.
  - Line editor: the selection toolbar sits below the lines (sticky to the panel bottom). Above them, it pushed the rows down between the two clicks of a double-click, so double-click-to-edit hit the wrong row.

- **Export with originals** (`opencut/export-guard.ts`): each build records which media ids came from `assets/proxies/`. Export is blocked, with the reason and the fix, while any clip on the timeline still references one; Build for export (originals) clears the list. It reproduces v2's `from_openreel.py --originals` rule as a check instead of a step to remember. The Editor project panel carries OpenCut's own Export button, so a session exports without leaving the Edit stage.

## M4 editor parity

- **Transitions** (`opencut/transitions.ts`, `opencut/transitions-view.tsx`): OpenCut has no transition object, so a transition is the two clips of a cut overlapping on different lanes plus keyframes on them (opacity, `transform.positionX`). The keyframes carry a tagged id (`esta-tx|side|type|duration|run|n`), which is how a transition is read back, changed and removed; `run` is how far the outgoing clip was extended to overlap, and removing the transition gives it back. Types: crossfade, dip to black, slide, push. One planner serves the emitter (render's crossfades arrive as editable crossfades) and the Transitions tab, which lists every cut between consecutive shots with a type and a length. A change is one undoable command; an overlapping type moves the incoming clip to the `Main B` lane when both sit on one lane, and the overlap is capped by the outgoing clip's remaining source and the next clip on its lane.

- **Karaoke captions** (`opencut/karaoke.ts`): v2's karaoke look on render's captions. Spoken words take the highlight colour (render's `#fde047`), upcoming words the text colour, and the current word fills left to right at 1.05x, as in v2's `caption-animation-renderer`. The phrases stay `from_openreel.py`'s 3-word chunks; each carries its word timings in the `esta.karaoke` param, and the drawer places words on OpenCut's own measured lines. A caption edited so its words no longer match its timings is drawn plain.

- **Text outline and shadow** (`opencut/text-style.ts`): OpenCut text has only a background box. Text now also takes an outline (width, colour) and a drop shadow (colour, opacity, blur, offset), all keyframable and sized in percent of the font size so they follow font-size changes. Karaoke captions draw every word's outline before any fill, so a thick outline never covers a neighbouring word. Render's captions keep v2's look (a dark box, no outline); the outline and shadow are there to switch on in the Text tab.

- **Auto-ducking** (`opencut/ducking.ts`, `opencut/ducking-plan.ts`, `opencut/ducking-section.tsx`): select the music clip, and the Audio tab's "Duck under voice" dips it wherever another audio track (the one named Voice by default) has speech. Speech is found from the voice clips' own audio (20 ms RMS windows over the preset's threshold, mapped through each clip's trim, position and speed); passages closer than an attack plus a release stay ducked through the gap so the music doesn't pump between words. The dip is volume keyframes tagged `esta-duck|n`, one undoable change; Re-apply replaces them and Remove takes them out. A clip with its own volume keyframes is left alone rather than mixed with them. Presets are v2's `AudioDuckingSection` ones (Subtle, Moderate, Aggressive, Podcast). v2's section was a stub whose Apply saved nothing; in v2 ducking was only reachable through the chat's `animate_clip`, which still works here. `ducking-plan.test.ts` covers the speech finder and the keyframe plan.

- **Colour grading and LUTs** (`opencut/grade.ts`, `opencut/grade-panel.tsx`): v2's ColorGradingSection as one Grade effect: colour wheels (shadows, midtones, highlights, with lift, gamma and gain), RGB and per-channel curves, a loaded `.cube` LUT with a mix, and HSL over eight hue ranges, applied in v2's order (wheels, curves, LUT, HSL) with v2's maths. Each is a per-pixel colour mapping, so the whole grade is baked on the CPU into one 33-point 3D LUT (about 10 to 35 ms, cached by the effect's params) and applied by a single new `lut-3d` shader; Intensity stays a live uniform, so it can be keyframed. A loaded `.cube` (any size, with its domain) is resampled to 33 points and stored in the effect's `lut` param as the file name plus base64, so the project carries it. The grade itself is the `grade` param (JSON). `grade.test.ts` covers the bake, the `.cube` parser and the cache; the shader was checked on known pixels through WebGPU (identity lossless, an inverting LUT exact, half intensity mid-grey, alpha kept). In the editor, the LUT reached the shader correctly (a constant LUT gives its exact colour, swap and invert LUTs transform the input as expected), but this sandbox's WebGL fallback samples every effect's input at one point, upstream's Blur included, so the final look needs checking on a machine with WebGPU.

- **Export presets** (`opencut/export-presets.ts`): v2's platform presets that a browser can encode (YouTube 4K/4K60/1080p/Shorts, TikTok, Instagram Reels/Feed/Story, X, Facebook, LinkedIn, Web HD/Optimized, WebM VP9, and 1080p/4K masters as MP4). The ProRes, H.265 and MOV presets are left out: WebCodecs has no ProRes, and H.265 encoding depends on the machine. The picker lists only presets with the project's shape (a 9:16 project sees Shorts, TikTok, Reels and Story); the frame is scaled to the preset, never cropped. v2's per-platform maximum durations are left out because the platforms have since raised them, so a warning would be wrong.

### Changes to vendored `rust/`

| File | Change | Why |
|---|---|---|
| `crates/effects/src/pipeline.rs` | Effect shaders come from a table; each declares which uniforms fill the shared `scalars` slot and whether it takes `u_direction`. Uniform packing reads that table instead of blur's three names. Unit tests cover blur's packing (unchanged), the new shader's and the errors. | Upstream hard-coded blur's uniforms, so no second effect could pass values. |
| `crates/effects/src/shaders/color_adjust.wgsl` | New: brightness, contrast, saturation, hue rotation on straight alpha. | The Color effect. Checked on known pixels through WebGPU (identity, luminance greys, +51 brightness, 120° hue maps red to green). |
| `crates/effects/src/shaders/lut_3d.wgsl`, `crates/effects/src/pipeline.rs`, `crates/effects/src/types.rs` | New `lut-3d` shader (a 3D LUT stored as side-by-side slices, blue mixed by hand). Every effect pipeline gains a group 2 texture slot; a pass fills it with its `lut` texture, others with a 1x1 placeholder. A test parses and validates every effect shader with naga. | The Grade effect. |
| `crates/compositor/src/frame.rs`, `crates/compositor/src/compositor.rs`, `wasm/src/effects.rs` | Effect pass descriptors take an optional `lut` texture id, resolved from the uploaded textures (a missing one is `MissingTexture`). Standalone effect previews pass none. | The Grade effect. |
| `crates/compositor/src/frame.rs`, `crates/compositor/Cargo.toml` | Upstream fix: the `sceneEffect` item's field is read as `effectPassGroups`. `rename_all` on the enum renamed only the variants, so every standalone effect layer (OpenCut's own Blur included) failed the frame with "missing field `effect_pass_groups`". A test reads the frame shape the renderer sends (`serde_json` as a dev-dependency). | Found while testing the Grade effect as an effect layer. |

## Known baseline issues (not introduced by v3)

- `bun run typecheck` fails on `src/changelog/` and `src/app/changelog/` until `next dev` has generated `.content-collections` once (upstream's content-collections setup).
- `bun run lint:all` reports OpenCut's own lint errors: 112 in 73 upstream files, 87 of them `no-unsafe-type-assertion`. Unmodified upstream `apps/web` reports 136. `bun run lint` covers the code v3 owns and is clean.
