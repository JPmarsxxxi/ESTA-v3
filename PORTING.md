# PORTING

Every deviation from a verbatim copy of ESTA-v2, and every change to vendored OpenCut code outside `apps/editor/src/esta/`. If it isn't listed here, it's a straight copy.

## Copied from ESTA-v2

| What | Status |
|---|---|
| `tools/**` | Verbatim. `diff -r` against v2 shows only the excluded `asset-server.mjs`, `chat-bridge.mjs`, `planner/`, `picker/` (and `__pycache__`). No integration fixes needed so far. |
| `.claude/skills/**` | All 14 ESTA skills verbatim, merged with the StyleSeed skills already in v3. v2's `humanizer` replaced v3's; the leftover files of v3's clone (`.git/`, `LICENSE`, `README.md`, `WARP.md`) were moved out so the folder matches v2 exactly. |
| `.claude/settings.json` | Verbatim (the `esta` env and Colab MCP prompt hooks), so terminal Claude Code behaves as in v2. |
| `.mcp.json` | Verbatim. `tools/opencut/mcp-server.mjs` didn't move, and the backend keeps port 8787, so no path or URL changes. |
| `config.example.yaml`, `environment.yml`, `setup.ps1`, `requirements.txt`, `editing-principles.md`, `motion-design.md`, `sound-design.md`, `voice_samples/`, `characters/`, `profile/`, `notebook/` | Verbatim. |
| `config.yaml` | Also copied (gitignored). SPEC lists only the example, but the tools read their API keys from the real file. |
| `CLAUDE.md` | v2's Skills, Pipeline rules, Conductor, Conda, Background steps, Session folder, User profile and LLM provider sections merged verbatim under "Pipeline (from ESTA-v2)". v2's "Browser surfaces" and "Setup" sections are replaced by v3's commands and a rule mapping v2 server/URL references to v3. |

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

### Not carried over from v2's OpenCut spike

- `src/app/esta-seed/` and `public/esta-import.json`: replaced by the native emitter in M3.
- `src/components/providers/esta-cmd-bridge.tsx`: the live-edit dispatcher moves into `src/esta/` with the editor integration in M3.

## Known baseline issues (not introduced by v3)

- `bun run lint:all` reports OpenCut's own lint errors: 112 in 73 upstream files, 87 of them `no-unsafe-type-assertion`. Unmodified upstream `apps/web` reports 136. `bun run lint` covers the code v3 owns and is clean.
