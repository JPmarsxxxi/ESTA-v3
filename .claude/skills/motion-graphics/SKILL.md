---
name: motion-graphics
description: Generates motion graphics with HyperFrames (HTML/CSS/GSAP rendered deterministically to video) instead of fetching stock. Two flavors — full-frame MP4s for plan shots typed MOTION_GRAPHICS, and transparent VP9 WebMs for shots carrying an `overlay` block (the card floats over footage on the Graphics track). Reads plan.json + style_analysis.json, writes to assets/source_pool/, streams results into assets_progress.jsonl exactly like the assets skill — render picks them up with no special handling. Runs in parallel with the assets background fetch; assets' giphy picks remain the fallback when a generation fails.
---

# Motion Graphics Skill

You replace stock-fetched motion graphics with **generated** ones. The plan
says what each graphic must communicate; you author it as a small HTML/CSS/GSAP
composition and render it with HyperFrames into the session's source pool.

Two flavors, decided per slot by the plan:

| Flavor | Trigger in plan.json | Output | Lands on |
|---|---|---|---|
| **Full-frame** | shot with `visual.type: "MOTION_GRAPHICS"` | opaque MP4, explicit background | the shot's own slot (Graphics track, nothing underneath) |
| **Overlay** | shot with an `overlay` block | transparent VP9 WebM (`--format webm`) | Graphics track, floating over the shot's fetched footage |

## Preflight

1. `sessions/<session-id>/plan.json` exists (or `plan_progress.jsonl` is growing). If neither: *"No plan yet — run the plan skill first."* Stop.
2. `node_modules/.bin/hyperframes` exists at the repo root. If not: *"Run `pnpm install` first."* Stop.
3. Rendering Chrome is cached: `npx hyperframes browser ensure` (instant when already downloaded; ~100 MB one-time otherwise — tell the user before a first-time download).
4. No conda env needed for generation. ffprobe verification uses `conda run --no-capture-output -n esta ffprobe` (same binary render uses).

## Collect the slots

Read `plan.json`. Build the slot list:

- every shot with `visual.type == "MOTION_GRAPHICS"` → full-frame slot, key `<n>`
- every shot with an `overlay` object → overlay slot, key `<n>-overlay`

If there are zero slots, write `sessions/<id>/motion_graphics.json` as `{"slots": [], "generated": 0, "fallbacks": 0}` (the conductor's done-marker), say so in one line, and stop.

Read the style DNA before authoring anything:

- `motion-design.md` (repo root) — **the canon. Read it first, every time.** §0 decides what the graphics *are*; §1 is enforceable (M1's banned-defaults list is the difference between art direction and the average); §2 is judgment.
- `style_analysis.json` → `visual_style`, `energy_level`, `keywords` — drive reveal speed, how hard the surface gets broken, texture tolerance (motion-design §3)
- `requirements.json` → topic + tone; orientation is vertical 1080×1920 unless the user asked for landscape
- the shot's `audio` line, `text.caption` / `overlay.caption`, `overlay.desc` — the actual content

## The cost model — read this before touching a slot

Measured on the first real session: **~482k tokens / ~90 min for 6 slots.** The whole bill was authoring, and it came from one mistake — **every slot re-authored the entire surface from scratch.** Slots 5 and 17 built byte-identical terminal chrome independently, because each was a fresh sub-agent that couldn't see the others, handed the full surface spec copied verbatim.

The fix, and the only way to work in this skill: **author the surface ONCE as a session kit, then each slot is a thin config.** A deterministic builder (`tools/motiongraphics/build.py`) inlines the kit into a complete, standalone, lint-valid `index.html` per slot — zero tokens for the assembly, and every slot is guaranteed to share the exact surface.

**No sub-agents.** They existed only because slots couldn't see each other; the kit file *is* the shared context. Author the kit and the configs inline, in this thread, where you can see all of it. That alone deletes the per-brief surface-copying that was most of the token bill.

## 1. Author the session kit (once)

Apply motion-design §0: **identify the native surface this topic lives on** — the real interface or document where this information exists (trading terminal, broadcast scoreboard, filed document, the product's own UI). Build that; don't invent "a motion graphic." Per §J3 the slots are the *same place seen again* — one surface, revisited — which is exactly what the shared kit enforces.

Write two files:

```
sessions/<id>/assets/mg/_kit/surface.css   ← ALL surface chrome: fonts, palette,
                                              grid/anchor positions, textures
                                              (scanlines, bloom), the .label/.value/
                                              .caption element styles slots reuse
sessions/<id>/assets/mg/_kit/helpers.js    ← shared GSAP helpers slots CALL instead
                                              of re-implementing: countUp(tl,sel,
                                              target,at,dur), reveal(tl,sel,at,dur),
                                              typeOn(...), plotCurve(...) as needed
```

State the surface in chat first (surface / palette+accent / type / layout+anchor / motion / the break — motion-design §0 + M1 banned-defaults) so the user can redirect it in one line. Then commit it to `surface.css` + `helpers.js`. **This is the creative work, done one time.** Everything after is configuration.

## 2. Write a thin config per slot

One JSON file per slot in `_kit/slots/<key>.json`. It carries only what's *unique* to the slot — never the surface:

```json
{
  "key": "5",
  "flavor": "full_frame",
  "duration": 2.74,
  "body": "<div class='label'>SHARPE RATIO</div><div class='value' id='v'>0.00</div><div class='caption' id='cap'>every year.</div><div id='scan'></div>",
  "timeline": "countUp(tl, '#v', 3.71, 0.3); reveal(tl, '#cap', 1.4);"
}
```

- `key` — `<n>` for full-frame, `<n>-overlay` for overlay.
- `flavor` — `full_frame` (opaque bg, added by the builder) or `overlay` (transparent bg).
- `duration` — the **shot slot** duration; the builder adds the 1.0s hold tail.
- `body` — the slot's unique elements, using the kit's classes (`.label`, `.value`, …).
- `timeline` — GSAP statements against a `tl` the builder provides; call kit helpers.

A callback slot (J4) is trivially the same kit with different values — slot 17 re-states slot 5's `SHARPE RATIO 3.71` card and strikes it through. That's a 6-line config, not a re-derivation.

Composition non-negotiables (the builder handles 1, 2, 7's background; you own the rest in `body`/`timeline`):
1. ✅ builder: `class="clip"`, `data-*` timing, one root composition.
2. ✅ builder: GSAP timeline paused + registered as `main`.
3. Deterministic only — no `Date.now()`, `Math.random()`, or network in logic.
4. ✅ builder: duration = slot + 1.0s hold. Land all animation by `slot` seconds; the tail holds.
5. Easing never linear for reveals — `power2.out`/`power3.out`; count-ups snap. Exception (M5): a real machine motion the surface has (cursor blink, scanline, ticker) is linear because the real thing is.
6. Reveal/type text holds the full string's width from the start so it doesn't slide.
7. ✅ builder: opaque bg for full-frame, transparent for overlay. You must still keep overlay content inside the card area — never a full-bleed scrim.
8. Overlay cards inside the safe area (≥90px from edges, clear of the bottom ~400px where subtitles live).

## 3. Build + verify each slot

```bash
conda run --no-capture-output -n esta python tools/motiongraphics/build.py --session sessions/<id>          # all slots
conda run --no-capture-output -n esta python tools/motiongraphics/build.py --session sessions/<id> --key 5  # one
```

This writes `assets/mg/slot_<key>/index.html`, fully assembled. Then:

```bash
npx hyperframes lint sessions/<id>/assets/mg/slot_<key>                        # must be 0 errors
npx hyperframes snapshot sessions/<id>/assets/mg/slot_<key> --no-describe      # FREE look-check — iterate here
```

**Iterate on snapshots, not renders.** A snapshot is PNG keyframes (a few seconds, cheap); it caught the count-up value, accent, and glow in testing. Only render once the snapshot looks right. Edit the config → rebuild that one key → re-snapshot. Never re-render to check a tweak.

```bash
# render only when the snapshot is right (small comps ≈ 8s, not the 20-30s once assumed)
npx hyperframes render sessions/<id>/assets/mg/slot_<key> -o <path>/source_pool/mg_<key>.mp4          # full-frame
npx hyperframes render sessions/<id>/assets/mg/slot_<key> --format webm -o <path>/mg_<key>.webm       # overlay
```

Verify with ffprobe — all three must hold or the slot is a failure:

```bash
conda run --no-capture-output -n esta ffprobe -v error -show_entries "stream=codec_name,width,height:stream_tags=alpha_mode:format=duration" -of default=nw=1 <output file>
```

- duration within ±0.15s of `slot duration + 1.0`
- dimensions = project canvas (1080×1920 portrait)
- overlay flavor: `TAG:ALPHA_MODE=1` present (it's a container tag — `pix_fmt` will still read `yuv420p`; that's normal). Missing tag = the file is opaque and will black out the footage → fix the composition, re-render.

Then look at a real frame yourself (Read tool on a snapshot PNG, or `ffmpeg -c:v libvpx-vp9 -ss <mid> -i out.webm -frames:v 1 frame.png` — the `-c:v libvpx-vp9` decoder flag is required to keep alpha; the native decoder silently drops it). Typos, clipped text, and bad contrast are cheaper to catch here than after the user sees the timeline.

## Publish into the assets feed

After each verified slot, append one line to `sessions/<id>/assets_progress.jsonl` (and update the entry in `assets.json` if that file already exists — keep both views consistent):

```json
{"shot_number": <n or "<n>-overlay">, "ok": true, "source": "hyperframes", "asset_type": "video", "url": "", "file": "sessions/<id>/assets/source_pool/mg_<key>.<ext>", "search_query": "", "in_point": 0.0, "out_point": <slot duration>, "error": "", "visual_verdict": "match", "visual_confidence": 100}
```

- Full-frame slots reuse the shot's own `shot_number` — the line **overwrites** whatever giphy/stock pick assets fetched (later line wins in render's merge). That stock pick is the deliberate fallback: if your generation fails, the shot still has media.
- Overlay slots use the string key `"<n>-overlay"` — render emits the extra Graphics-track clip only when this entry's file exists.
- On a failed slot (render error, verification miss after one fix attempt): full-frame → write nothing (stock fallback stands), overlay → write nothing (shot simply ships without the floating card). Tell the user which slots fell back and why.

## Ordering and callbacks — no sub-agents needed

The old skill split slots across parallel sub-agents and paid a heavy tax to keep them consistent (copying the surface spec into every brief, sequencing "definer → dependent" waves so a callback slot could match an object it couldn't see). **The kit dissolves all of that.** The shared object *is* the kit: slot 5's SHARPE card is a `.value` element styled by `surface.css`; slot 17 restates the same markup and strikes it through. Both read from one file, so they're consistent by construction — no object spec to extract and pass around.

So: **author every config inline in this thread, in one pass.** A J4 callback is just a later config reusing the same classes/helpers with new values (see the slot-17 example above). You can see slot 5's config while writing slot 17's — that's the entire problem the wave-scheduling existed to solve, gone.

Batch the mechanical steps: build all slots at once (`build.py` with no `--key`), then lint + snapshot each, fix the configs that need it, rebuild, render the ones that pass. The only real ordering constraint is your own eyes on the snapshots.

This skill is conversation-driven (configs + kit, no long Python job), so it runs while the assets background fetch is still downloading — the two write to the same feed without conflict because assets keys are ints and overlay keys are strings, and full-frame overwrites are last-writer-wins by design.

## Hand off

When all slots are published (or accounted for as fallbacks):

0. Write `sessions/<id>/motion_graphics.json` — the summary + conductor done-marker:
   ```json
   {"slots": [{"key": "7", "flavor": "full_frame", "ok": true, "file": "..."}, {"key": "9-overlay", "flavor": "overlay", "ok": false, "error": "..."}], "generated": <K>, "fallbacks": <X>, "generated_at": "<ISO 8601 UTC>"}
   ```
1. If `assets.json` exists (assets pass finished) → fire the render pass so the timeline updates now:
   ```bash
   conda run --no-capture-output -n esta python tools/render/run.py build --session sessions/<id>
   ```
   If assets is still running → do nothing; its final render pass will pick the generated files up from the feed.
2. Report in 2–3 lines: `[K] generated ([F] full-frame, [O] overlays), [X] fell back to stock`, plus anything worth eyeballing in the editor.

## Notes

- HyperFrames is Apache 2.0 (no per-render fees) — safe for `free_only` licensing sessions; `source: "hyperframes"` needs no licensing gate.
- The editor compositing path (Chrome decode → canvas/WebGPU draw) preserves VP9 alpha end-to-end — verified 2026-06-10 with a real HyperFrames WebM over Pexels footage.
- Telemetry is disabled repo-side (`hyperframes telemetry disable`).
- Engine alternatives (PIL static cards, Remotion) are deliberately out of scope for v1 — add as fallback engines only if HyperFrames proves flaky in practice.

## Code references

- `tools/motiongraphics/build.py` — the kit inliner: `_kit/surface.css` + `_kit/helpers.js` + `_kit/slots/<key>.json` → `slot_<key>/index.html`. Handles bg per flavor, the 1.0s hold tail, and the composition/timing boilerplate.
- `tools/render/run.py` — overlay clip emission (search `"-overlay"`), track routing (`_video_track_for`), feed merge (`_load_asset_shots`).
- `tools/assets/schema.py` — `ShotAsset` shape the feed lines must match.
- `.claude/skills/plan/SKILL.md` — `overlay` block schema + when plan adds one.
- `npx hyperframes docs <topic>` — HyperFrames composition/gsap/data-attribute reference. (Slot dirs no longer scaffold their own `CLAUDE.md`; the builder writes a plain composition.)
