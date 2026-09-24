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
| `tools/opencut/from_openreel.py` | Video and audio elements carry `clipId` (the OpenReel clip id). | The main track's `transitions` name clips by id; without it the emitter can't tell which neighbouring pair a crossfade belongs to. |

## Backend (`server/`, replaces `asset-server.mjs` + `chat-bridge.mjs`)

Every v2 route is kept with its v2 behaviour, on one port (8787). Differences:

- **One port.** The chat routes moved from :8788 onto :8787.
- **`/_sessions/create`** still creates a bare folder for v2's `{topic}` body. When the requirements fields are sent (the v3 form), it also validates them with `tools/requirements/validators.py` and writes `requirements.json` (the `schema.py` fields), `conversation.jsonl`, and `script_uploaded.txt` for an uploaded script.
- **`/_sessions/list`** is unchanged. `?all=1` also lists sessions that haven't been rendered yet, for the session list page.
- **`/_plan` and `/_picker` HTML pages are not served.** Their APIs are unchanged; the pages become React panels in M2.
- **Chat:** v2 opened a chat by holding `/chat/stream` open. `/chat/stream` still works; the UI uses `POST /chat/open` plus the multiplexed `/_events?chat=<id>` stream. Added `/chat/status` (liveness) and kept v2's `/chat/interrupt`.
- **Live edit:** `/_cmd` also broadcasts on `/_events` (channel `cmd`). `delivered` counts both kinds of subscriber.
- **Media:** files are served under both `/api/sessions/<id>/...` (v2's URL form) and the bare `/<id>/...` path the asset-server saw behind Vite's proxy.
- **CORS** also allows the `X-Esta-Client` header. The editor tags its own writes with it, so file-change events can tell a tab's own save from an external write.
- **New routes:**
  - `/_events` (the one multiplexed SSE stream per tab)
  - `/_pipeline/:id` (state, plus `approve`, `force`, `template`, `flow`, `run`)
  - `/_jobs` (list, log, cancel, retry; live updates on `/_events`)
  - `/_files/:id` (SSE) and `/_files/:id/list`
  - `/_sessions/import`
  - `/_preflight`
  - `/_opencut/:id[?originals=1]`: runs `from_openreel.py` into `.esta/opencut/` and returns its intermediate, with each media file's size and mtime (or `missing`)
- **Jobs** are spawned detached, so a Kaggle run survives a backend restart. On restart, a job whose process died is marked `interrupted`. One still running is tracked as detached, and resolves to done or interrupted from disk when it exits.

## Pipeline state

- **Approvals and overrides** are stored under a new `ui` key in `pipeline.json` (`ui.approvals.<checkpoint>`, `ui.overrides.<step token>`). `conductor.py` round-trips unknown keys.
- **Approving requirements with a template** runs `conductor.py build` (this is how the UI replaces the conductor skill's template choice). Approvals already given survive a template switch. Custom orders go through `validate_flow.py` and are rejected with its message.
- **Import from v2:** the checkpoints whose artifacts already exist (`requirements.json`, `script.md`, `script.tagged.md`, `plan.json`) are recorded as approved with `by: "import"`, because v2 passed them in conversation. A v2 session without `pipeline.json` gets the canonical `standard-vo` rails (`conductor.py build`) at import, so those approvals have somewhere to live.
- **`skip_scriptwriter: true`** marks the scriptwriter step skipped even if `pipeline.json` wasn't `mark`ed, matching CLAUDE.md ("skip skills explicitly disabled by earlier steps").
- **Voice profiler:** it re-enters the flow when `example_scripts` becomes a list after `pipeline.json` was built (SPEC edge case).
- **Stage skill buttons** run `claude -p` with the user's default model, not Haiku. Haiku is reserved for the planner's Rewrite and structural commands, as in v2. Skills like plan and scriptwriter need the stronger model. Each job gets a headless preamble: no questions, foreground commands, stop at approvals.

## Vendored OpenCut (`apps/editor/`)

Source: `C:\Users\User\opencut-classic` at `cf5e79e` (upstream `github.com/opencut-app/opencut-classic`), `apps/web` only. `rust/` and `apps/desktop` are not vendored: the web app uses the published `opencut-wasm` npm package. Root `eslint.config.mjs`, `eslint/`, `biome.json`, `tsconfig.json` and `bun.lock` were copied alongside it.

### Mount points (OpenCut files changed to host ESTA)

| File | Change |
|---|---|
| `src/app/page.tsx` | OpenCut's marketing landing page is replaced by the ESTA session list (`@/esta/home`). |
| `src/app/esta/[session]/page.tsx` | New route: the stage workspace (`@/esta/workspace`). |
| `src/app/layout.tsx` | Removed the BotID client, the dev-only React Scan overlay (it covered the chat panel) and the Databuddy analytics script. The app is local-only and single-user. |

### Other changes

| File | Change | Why |
|---|---|---|
| `package.json` | Renamed `@esta/editor`; added `remark-gfm` (chat markdown tables) and `bun-types` (the missing dependency of `@types/bun`). | |
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
- `src/components/providers/esta-cmd-bridge.tsx`: the live-edit dispatcher moves into `src/esta/` with the editor integration in M3.

## M2 surfaces

- **Planner panel** (`src/esta/panels/planner-panel.tsx`): a port of `tools/planner/index.html`. Same fields, same endpoints, same autosave-on-leave, Ctrl+S, Rewrite and split/merge/overlay commands, and v2's line-identity anchoring so a split doesn't move the user off their shot. The beacon on hard close is a `keepalive` fetch rather than `sendBeacon`: the backend is a different origin, and a beacon can't carry the JSON content type through preflight.
- **Picker panel** (`picker-panel.tsx`): a port of `tools/picker/index.html`, including the full source bank with the plan's prescription starred, background fetch jobs, the generated-graphic override notice, pick-and-advance, and v2's rule that at most one `<video>` exists at a time (created on hover).
- **Script panel** (`script-panel.tsx`, `line-editor.tsx`): a port of v2 `apps/studio`'s `WritingStageView` + `LineEditor` for `script.md` and the talking points in `script_metadata.json`.
- **Tagged-script review** (`tagged-panel.tsx`): new in v3. It gives the audio skill's approval step a surface: the delivery markup with its tags as chips, tag-check, approve, and per-line redo through `expressive --only`.
- **Requirements panel** (`requirements-panel.tsx`) edits `requirements.json` in place through a new `POST /_sessions/:id/requirements`, which runs v2's validators and preserves fields the form doesn't own.
- **Timeline strip and preview** (`shots-panels.tsx`): plan-derived, sharing one selected shot with the planner and picker. The OpenCut timeline joins that shared selection in M3, when the native project exists.

## M3 editor integration

- **Native emitter** (`src/esta/opencut/emit.ts`): the TS module SPEC allows in place of `tools/opencut/emit.py`. It takes `from_openreel.py`'s intermediate from `/_opencut/:id`, so the track mapping, proxy choice and caption chunking stay v2's code, and builds the native project with OpenCut's own builders (`buildElementFromMedia`, `buildTextElement`, `upsertPathKeyframe`, `mediaTimeFromSeconds`). It saves the project as `esta-<session>` and its media into OpenCut's per-project store. A rebuild downloads only files whose size or mtime changed and drops media the new revision no longer uses. The project's background and timeline view survive a rebuild.
  - Trim: `trimStart = inPoint`, `trimEnd = sourceDuration - outPoint`. `speed` becomes `retime.rate`.
  - Volume: OpenReel's linear gain becomes OpenCut's dB (`20·log10`, 0 -> -60 dB).
  - Video lanes keep render's `muted` on the track and turn off `isSourceAudioEnabled`, so clip audio never competes with the voiceover.
  - Keyframes: `scale.x/y`, `position.x/y`, `rotation`, `opacity` map to OpenCut's `transform.*` and `opacity` paths, linear.
  - Crossfades: OpenCut has no transitions. As in v2's spike, alternate clips move to a `Main B` video lane above the main track. The earlier clip of each pair runs on past the cut by the fade length (clamped to the source it has left), and whichever of the two is on top fades. Cut points stay where the plan put them. Track order, top first: Captions, Graphics/Overlay, Main B, main.
  - Clips whose media file is missing on disk are left out and listed in the panel.
- **Editor project panel** (`panels/editor-panel.tsx`, in the Edit preset): Build project (proxies, for editing), Build for export (originals, what `from_openreel.py --originals` did), and Open editor (`/editor/esta-<session>`). The render skill's `--emit` into the OpenCut clone and its `/esta-seed` step map to these buttons (see CLAUDE.md).

## Known baseline issues (not introduced by v3)

- `bun run typecheck` fails on `src/changelog/` and `src/app/changelog/` until `next dev` has generated `.content-collections` once (upstream's content-collections setup).
- `bun run lint:all` reports OpenCut's own lint errors: 112 in 73 upstream files, 87 of them `no-unsafe-type-assertion`. Unmodified upstream `apps/web` reports 136. `bun run lint` covers the code v3 owns and is clean.
