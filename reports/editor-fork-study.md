# Editor fork study: OpenCut vs FilmCraft vs EffectCraft

M14 goal 5, research only. It compares the editor ESTA forks today with the two open-source Adobe recreations the user found, and estimates what moving would cost. It does not recommend a switch; that is the user's call.

Written 2026-10-13. All three projects change weekly, so the numbers below are a snapshot.

## Which repos were studied

| Name the user gave | Repository | How it was read |
|---|---|---|
| OpenCut (today's fork) | [opencut-app/opencut-classic](https://github.com/opencut-app/opencut-classic), vendored at `cf5e79e` as `apps/editor/` | Our own code, plus the GitHub page |
| FilmCraft | [storytold/filmcraft](https://github.com/storytold/filmcraft): "an open-source, clean-room reimplementation of Adobe Premiere Pro, rebuilt in pure Rust" | README, `ROADMAP.md`, `docs/web.md` and the GitHub page. A clone was blocked in this session, so its source was not read. |
| EffectCraft | [storytold/effectcraft](https://github.com/storytold/effectcraft): the After Effects counterpart | Shallow clone at `470ea7a` (v0.9.2, 2026-10-12): README, `ROADMAP.md`, `docs/architecture.md`, `docs/web.md`, `docs/agents.md` |

The names are unambiguous. Both come from the ArtCraft team's "Crafting Apps", seven Adobe recreations in the storytold org (PhotoCraft, VectorCraft, FilmCraft, LightCraft, PrintCraft, EffectCraft, DesignCraft). EffectCraft recreates After Effects, not Premiere, so it is a compositor rather than an NLE. That matters for every row below.

The research also turned up a fourth option. **opencut-classic was archived on 17 May 2026** and is now read-only. Its README points to [opencut-app/opencut](https://github.com/opencut-app/opencut), a from-scratch rewrite with a Rust core that is not yet taking outside contributions. Its README lists an Editor API, plugins, an MCP server and a headless mode as upcoming.

## The projects

| | OpenCut classic (ours) | FilmCraft | EffectCraft |
|---|---|---|---|
| Recreates | CapCut-style web editor | Premiere Pro | After Effects |
| Licence | MIT | MIT or Apache-2.0 | MIT or Apache-2.0 |
| Activity | Archived 2026-05-17; 1,567 commits; no upstream fixes from here on | 1,946 commits; 421 open issues, 160 open PRs; 11.8k stars | First commit 2026-10-01; v0.9.2 on 2026-10-12; 1,142 commits, 233 merged PRs |
| Size | Next.js app plus a Rust/wasm compositor (`opencut-wasm`) | 45 crates, about 343k lines of Rust, 2,520 tests | 32 crates, about 360k lines of Rust (crates + apps) |
| Stack | React 19 / Next.js, TypeScript; wasm compositor on WebGPU | Pure Rust, egui UI, wgpu compositor; desktop plus a wasm web build | Same as FilmCraft; shares its time model and codecs |
| UI model | DOM components we mount panel by panel | One egui canvas holding Premiere's whole panel layout | One egui canvas holding After Effects' panel layout |
| Maturity (its own estimate) | Production at opencut.app until the rewrite takes over | Alpha: about 86% of Premiere's features, about 56% ready for real work (2026-10-10) | Alpha: about 91% of features, about 45% ready for real work |
| Codecs | Browser (WebCodecs) | Own Rust H.264/HEVC/ProRes/AAC/VP9/AV1 decode; H.264 the only software export | FilmCraft's codecs plus its own VP9/AV1/HEVC/Opus encoders; no FFmpeg |
| Project file | IndexedDB project (our `emit.ts` writes it) | `.fcproj`; imports FCP7 XML, FCPXML, OTIO, EDL, AAF, OMF | `.ecproj` (versioned JSON); imports the same timeline formats into compositions |
| Automation | None upstream; ESTA added the live-edit bridge and MCP | 650+ engine commands; one registry behind the UI, CLI, a TCP JSON control channel and MCP; widget automation ids. Web: `window.filmcraft` | Same design. Web: `window.effectcraft` (`execute`, `request`, `renderFrame`, `addFile`, `screenshot`) |
| Known gaps | Upstream frozen | No `.prproj`; Lumetri and export render on the CPU; desktop-only on the web: render previews, proxies, mask tracking; web export runs one frame per step on the UI thread | No `.aep`; not yet compared with After Effects' output; macOS the most tested |

### Timeline, effects, compositor, export

- **OpenCut classic** has a simple multi-track timeline with keyframes and few effects. Everything ESTA needed beyond that we added in M4: a Color effect and LUT grade on a rebuilt wasm compositor (`rust/`, about 5k lines), transitions, karaoke captions, text styling, auto-ducking and export presets. Export is the browser's WebCodecs path.
- **FilmCraft** has a real NLE:
  - three-point editing, ripple/roll/slip/slide/rate-stretch tools, sync locks and nesting;
  - about 30 transitions and 93 video effects;
  - a Lumetri-style colour panel and eight built-in looks (code, not LUT files);
  - a 24-track mixer with automation and EBU R128 loudness;
  - caption tracks (608/708/SRT/VTT).

  Its compositor is wgpu in linear light. Export is H.264/ProRes/DNxHR, and hardware H.264/H.265 on desktop.
- **EffectCraft** has compositions, layers, keyframes with a graph editor, 306 effects, expressions, 3D cameras and lights, Lottie import and export, and a render queue (H.264, ProRes 4444 with alpha, HEVC, AV1, VP9 with alpha). It is built for motion graphics, not for cutting a 14-minute voiceover video of about 290 shots.

## How each would host our plumbing

Everything `src/esta/opencut/` does today, about 2.5k lines, plus the `rust/` compositor work and 22 OpenCut edits logged in `PORTING.md`. The rest of `src/esta/` (stage rail, planner, picker, script, chat, jobs: about 4.4k lines) and the backend (`server/`, about 3.1k lines) don't depend on the editor and carry over either way.

| Piece (today) | OpenCut classic (stay) | FilmCraft (web build in a panel) | EffectCraft (web build in a panel) |
|---|---|---|---|
| **Native project emit** (`emit.ts`, `host.tsx`: render output to an IndexedDB project, auto-build, follow render) | Done | Write OTIO or FCPXML (FilmCraft imports both), or `.fcproj` directly, and load it with `openProject`. Media through `importUrl` from `/api/sessions/...`. Follow-render becomes reopen plus a local-edits check (FilmCraft has unlimited undo, so "edited since build" maps over). | Same import formats, but each sequence becomes a composition with one layer per clip, so a 290-shot edit is a 290-layer comp. |
| **Shot sync and selection to Claude** (`shot-sync.tsx`, `selection.ts`) | Done (M14) | Clip ids must survive the import (OTIO metadata or `.fcproj` ids). Reading and setting the selection needs an engine command or `ui.inspect`. The README doesn't document a selection query: unverified, it may need an upstream PR. | The same question, at layer level. |
| **Live command bridge and MCP tools** (`bridge.tsx`, `tools/opencut/mcp-server.mjs`) | Done | The biggest win: FilmCraft already has an MCP server with 650+ commands. Its live (bridge) mode drives the **desktop** app, though. In the browser the bridge becomes calls to `window.filmcraft.execute` from our page, relayed from our MCP server, so a thinner `bridge.tsx` stays. | Same: `window.effectcraft.execute`, and `renderFrame` replaces our `get_frame`. |
| **Grade / LUT** (`grade.ts`, `grade-panel.tsx`, `rust/` color-adjust and lut-3d shaders) | Done; we maintain the shaders | Native Lumetri panel. `.cube` loading isn't mentioned in the README: unverified. Our grade code is dropped. | 306 effects including Lumetri-style colour. Our code is dropped. |
| **Auto-ducking** (`ducking*.ts`) | Done | Mixer automation exists, and a screenshot caption mentions a ducked bed. Automatic ducking from the voice track isn't documented: we'd keep `ducking-plan.ts` and write volume keyframes through commands. | Audio levels as keyframes; same approach. |
| **Karaoke captions** (`karaoke.ts`, `text-style*.ts`) | Done | Caption tracks exist, but nothing documents a per-word highlight. Likely either generated graphic clips per word (heavy) or an upstream feature. | Text animators with range selectors can do a word highlight natively, at the cost of one text layer per subtitle chunk. |
| **Transitions** (`transitions*.ts*`) | Done | Native (about 30). We only map render's transition names. | Opacity keyframes and overlapping layers (the way its FCP XML import already does it). |
| **Export presets and export with originals** (`export-presets.ts`, `export-guard.ts`) | Done | In the browser: H.264 only, one frame per step on the UI thread (slow for 14 minutes). Proxies are desktop-only on the web. Alternative: render server-side with `filmcraft-cli` from the backend, outside the browser. | Render queue with every codec; the CLI renders headless. |
| **Wasm compositor** (`rust/`, rebuilt `opencut-wasm`) | Ours to maintain, no upstream | Not needed: FilmCraft's own | Not needed |
| **Workspace layout** (stage rail plus dockable React panels around the editor) | The editor's preview, timeline, properties and assets are separate React panels we place freely | The editor is one canvas with its own docking, so our Simple/Detailed views become "which FilmCraft workspace". Focus, keyboard shortcuts and accessibility live inside the canvas. | Same |

**Desktop variant.** Instead of embedding the web build, ESTA could drive the desktop FilmCraft through its own MCP bridge (`--control` plus MCP `--bridge`). That gets the full desktop feature set (proxies, hardware export, previews) and FilmCraft's own agent tooling for free. The cost is ESTA's central promise: the editor leaves the one window.

## Pros and cons, ranked

Ranked by fit for ESTA's job: a chat-native, one-window pipeline whose output is a long voiceover edit.

| Rank | Option | For | Against |
|---|---|---|---|
| 1 | **Stay on OpenCut classic** | All plumbing exists and works (M3, M4, M14). Same-page React integration: selection, panels and live edit are plain JS calls. No migration risk. | Upstream archived: every bug fix and feature is ours, including the wasm compositor. A thin NLE (no ripple, roll or slip, few effects). The rewrite won't merge back. |
| 2 | **FilmCraft, web build in a panel** | A real Premiere-style NLE with colour, mixer and captions. An agent-first design (650+ commands, MCP, `window.filmcraft`) close to how ESTA already works. Permissive licence. Very active. | Alpha (about 56% ready by its own estimate). Web export is H.264 only and slow, with no proxies. Selection API and karaoke unverified. The editor becomes one opaque canvas inside our layout. A large wasm download. Moving fast enough to break integrations week to week. |
| 3 | **FilmCraft desktop, driven over MCP** | Full desktop features, and agent control we don't have to build. | Breaks "one window". Two apps to install and keep in step. The ESTA web UI loses the timeline it owns. |
| 4 | **Wait for the OpenCut rewrite** | Same family as today. Rust core. Editor API and MCP planned. | Not usable or open to contributions yet. No dates. |
| 5 | **EffectCraft as the editor** | Strongest effects, text animation and Lottie. Best for karaoke and motion-graphic polish. | A compositor, not an NLE: a 290-shot cut is a 290-layer comp. Under two weeks old. It fits better as a motion-graphics engine (next to or instead of HyperFrames), which is a separate question. |

## Migration cost estimate

Rough agent-hours for a working switch, at the level M3, M4 and M14 reached on OpenCut. The ranges are wide because FilmCraft's source wasn't read and two capabilities are unverified (selection query, karaoke).

| Work | FilmCraft web | FilmCraft desktop | EffectCraft as editor |
|---|---|---|---|
| Emitter (render output to OTIO/FCPXML/`.fcproj`, media import, follow render) | 25–45 | 20–35 | 35–60 |
| Host and bridge (mount the canvas, `window.*` relay, MCP tools remapped) | 30–60 | 15–30 (its MCP exists) | 30–60 |
| Selection to Claude and shot controls | 15–40 | 15–40 | 20–45 |
| Grade, ducking, karaoke, transitions, export presets | 40–90 | 30–70 | 40–80 |
| Export with originals | 15–30 (server-side CLI render) | 5–10 | 10–20 |
| Layout and UX (Simple/Detailed on a canvas, focus and shortcuts) | 20–40 | 10–20 | 20–40 |
| Testing on the fixture plus a real session, `PORTING.md`, `PARITY.md` | 20–40 | 15–30 | 25–45 |
| **Total** | **165–345** | **110–235** | **180–350** |

For scale: staying costs nothing to migrate. The open cost there is upkeep of an archived fork, which so far has been the 22 logged edits and the `rust/` compositor work.

What would narrow these ranges before any decision:

- Read FilmCraft's source for a selection query and per-word caption styling.
- Measure its web export speed and wasm size on a 14-minute timeline.
- Try an OTIO import of a do-alphas emit.

Each is a day or less.
