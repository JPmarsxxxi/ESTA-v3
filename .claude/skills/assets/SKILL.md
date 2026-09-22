---
name: assets
description: Parallel asset search and download across Pexels, Pixabay, Giphy, Wikimedia, Archive.org, and YouTube. Three modes — `bulk` (fire all shots in background), `bulk + review` (fire then walk results conversationally and retry flagged shots from natural-language feedback), or `per-shot` (narrate each pick before fetching, for debugging or high-care videos). Streams shots from plan_progress.jsonl as they arrive — shot 1 downloads while shots 2-N are still being generated. Produces assets/ folder and assets.json.
---

# Assets Skill

You fill every shot in the plan with a downloaded media file.

## Modes — pick before invoking

| Mode | When | Flow |
|---|---|---|
| **picker** (browser) | The user wants to choose the footage themselves | Serve candidate grids at `/_picker`; the user picks. Fast, zero vision tokens. **This is the preferred path when the user cares about the visuals** — taste isn't automatable, and a human pick beats a validated one. |
| `bulk` | Fast pipeline, trust the plan | Fire all shots in background. Summary at end. No per-shot pauses. |
| `bulk + review` (**default for auto**) | Normal auto video work | Fire all shots in background. After it completes, walk the user through results and accept natural-language feedback to retry flagged shots. |
| `per-shot` | Debugging, high-care, first run with a new style | One shot at a time. Narrate the pick → fetch → pause → accept feedback or advance. |

Read the user's signal to pick:
- *"let me pick"* / *"show me options"* / *"I'll choose the clips"* → **picker**
- *"just fetch everything"* / *"go"* → `bulk`
- *"let me check each one"* / *"one at a time"* → `per-shot`
- Anything ambiguous → `bulk + review`

## The picker (human-as-validator)

`tools/picker/` (served by `node tools/asset-server.mjs`) is the official surface for user-chosen footage. Instead of Claude validating stock with vision (slow, tokens, and a worse answer than two seconds of the user's taste), it downloads every plausible candidate and lets the user pick.

```bash
# gather candidates for one shot (no validation, no auto-pick) — feeds the grid
conda run --no-capture-output -n esta python tools/assets/run.py candidates --session sessions/<id> --n <shot> \
  [--queries "a | b | c"] [--sources "giphy, pexels_video"]
```

Then point the user at **`http://localhost:8787/_picker?session=<id>`**: a shot rail, a candidate grid per shot, editable queries + the full source bank as chips, refetch, and pick (which writes the feed line and deletes the losers). Picking one shot jumps to the next — they work through the list while other shots' candidates are still downloading. Generated motion graphics show as a pre-selected `GENERATED` tile so a stock override is a deliberate click. **YouTube keeps its vision moment-finder** even here — a 4-min movie can't be judged from a thumbnail grid, so finding the moment is real work, not a taste call.

Open: `http://localhost:8787/_picker?session=<id>` · run the server as `node tools/asset-server.mjs` directly (not `pnpm` — it orphans the child).

## Preflight

1. **Conda env check.** Confirm `esta` env exists. If not: *"Run `.\setup.ps1` first."* Stop.
2. Confirm `sessions/<session-id>/plan_progress.jsonl` exists OR `plan.json` exists. If neither: *"Plan hasn't started yet — run the plan skill first."* Stop.

## Invocation — bulk / bulk + review

Fire via Bash with `run_in_background: true`:

```bash
conda run --no-capture-output -n esta python tools/assets/run.py fetch \
  --session sessions/<id>
```

The process streams shots from `plan_progress.jsonl` as they arrive, searches all sources per shot, downloads the best candidate, appends to `assets_progress.jsonl`. When `plan.json` exists (plan complete), it drains remaining shots and exits.

## Invocation — per-shot

Fetch one shot at a time. Use this for `per-shot` mode AND for retries during `bulk + review`:

```bash
conda run --no-capture-output -n esta python tools/assets/run.py shot \
  --session sessions/<id> \
  --n <shot_number> \
  [--source <source>] \
  [--query "<override query>"]
```

`--source` and `--query` are optional overrides. Without them the shot uses its own `search_sources` from plan.json. With them, the override replaces the plan's source list for that shot.

### Per-shot narration script

Before each shot, write 3–5 lines (no more):

1. **Shot header.** `Shot N | start→end (duration) | one-line intent`
2. **Audio line + plan facts.** Quote the audio. Note `visual.type`, specificity, source order, query.
3. **Your read.** Read `visual.desc` carefully. If the plan's pick looks weak, propose a tighter source/query and explain why in one sentence.
4. **Your pick.** One line — source + query you're firing with.

Then run the `shot` command. Report the result concisely:
- Source picked, file written, validator verdict + confidence if YouTube
- Anything wrong (low quality, wrong fixture, mismatch)
- One question: keep / retry / next

## Bulk + review flow

After the bulk run completes, **don't go straight to render.** Walk the user through results first.

1. Open `assets.json`. Group shots:
   - `ok: false` (real failures) — list first with their `error` field
   - `ok: true` but validator `mismatch` (B2 fail) — second priority
   - `ok: true` but low quality (use ffprobe to spot-check video shots; flag any below 720p)
   - `ok: true` looking clean — group as "fine"

2. Show a compact table — one row per shot, columns: number, source, type, quality (if video), validator verdict (if present), error (if any).

3. Offer to walk through flagged shots one at a time. *"Want me to retry shot 8, or move on?"*

4. **Translate natural-language feedback into `shot` invocations:**

| User says | Translation |
|---|---|
| *"this match was a year ago"* | Update query to include current year. Re-fire `shot --n N --query "<new>"`. |
| *"try a different source"* | Pick alternative source from plan's source list. Re-fire `shot --n N --source <other>`. |
| *"this is the wrong [fixture / event / instance]"* | Tighten query with date / location / specific identifier. Re-fire `shot --n N --query "<more specific>"`. |
| *"this looks generic / stocky"* | Swap to YouTube or wikimedia (real source). Re-fire `shot --n N --source <real>`. |
| *"this is fine, move on"* | Accept. Advance to next flagged shot. |
| *"actually skip this shot"* | Mark as accepted-as-placeholder in conversation, move on. Don't retry. |

5. When the user signals done (silence, *"ok"*, *"that's enough"*, *"move on"*), run the **YouTube HD upgrade** step below (it's a no-op if there are no sub-720p YouTube shots), then run the **final render pass**:
   > "Running final render — should pull everything together on the timeline."

   ```bash
   conda run --no-capture-output -n esta python tools/render/run.py build \
     --session sessions/<id>
   ```

   Note: plan already fired an *early* render right after writing plan.json,
   so the user has been watching a live timeline (placeholders for shots,
   real voiceover + subs) since well before assets finished. This pass
   rewrites `<session-id>.openreel.json` with all real media in place. The
   editor's session-file-sync picks up the new revision automatically (loads
   it silently if the user hasn't manually edited; surfaces a "load update"
   banner if they have).

## YouTube HD upgrade via Colab

**Why:** locally, YouTube forces SABR streaming, so anonymous yt-dlp caps at ~360p (full investigation: `memory/project_youtube_sabr.md`). Google's Colab runtimes are not SABR-gated, so the plain `bestvideo+bestaudio` download returns real HD there. This step re-pulls the YouTube shots in HD on a connected Colab session and drops the files **in place** over the same `source_pool/yt_<id>.mp4` paths — so `assets.json`, render, and the editor need no changes, and the local 360p stays as fallback if Colab is unreachable.

Run this after assets are fetched (after the review/retries), before render. **It is additive and self-skipping** — projects with no sub-720p YouTube shots are untouched.

1. **Plan.** List the YouTube targets and get the Colab cell source:

   ```bash
   conda run --no-capture-output -n esta python tools/assets/youtube_colab.py plan \
     --session sessions/<id>
   ```

   Parse the JSON. If `count == 0` → **skip silently** and continue to render. Otherwise tell the user in one line:
   > "[N] YouTube clip(s) are at local quality (360p cap). I'll upgrade them to HD via Colab — opening a Colab tab now; sign in if it prompts."

2. **Connect.** Call the colab-proxy-mcp tool `open_colab_browser_connection`.
   - Returns **false** (user didn't connect within ~60s, or dismissed) → **graceful fallback**: leave the local 360p files as-is, tell the user:
     > "Couldn't reach Colab — the [N] clip(s) stay at local quality. Say *'upgrade youtube'* once a Colab tab is connected and I'll redo just this step."

     Then continue to render. **Do not block.**
   - Returns **true** → proceed.

3. **Run the cell on Colab.** Using the Colab notebook tools that colab-proxy-mcp exposes once connected (e.g. `add_code_cell`/`update_cell` + `run_code_cell`), put the `cell` string from step 1's output into a cell and execute it. The cell installs a current yt-dlp, downloads each id in HD, uploads each to filebin.net, and prints lines like `OK <id> 1080p <url>` then a final line:
   `ESTA_YT_RESULT::{"results": {...}, "errors": {...}}`

   Read the cell's stdout and extract the JSON after the `ESTA_YT_RESULT::` sentinel.

4. **Apply.** Write that JSON object to `sessions/<id>/youtube_hd_results.json` (the Write tool), then pull the HD files into place:

   ```bash
   conda run --no-capture-output -n esta python tools/assets/youtube_colab.py apply \
     --session sessions/<id> \
     --results sessions/<id>/youtube_hd_results.json
   ```

   This downloads each hosted file over `source_pool/yt_<id>.mp4`, re-probes, and annotates the affected shots in `assets.json` with `hd_height` / `hd_source: colab`.

5. **Report** one line: `[K] clip(s) upgraded to HD, [M] stayed at local quality`, then continue to render. Any id in `errors` (or in apply's `failed`) keeps its 360p file — render is never blocked.

6. **Release the Colab runtime — only when the user is done with all downloads.** A Colab VM is a shared/quota'd resource; free it once there's nothing left to fetch. After reporting, if the user signals they're finished (or you know this is the last asset run), run **one final cell** and stop:

   ```python
   from google.colab import runtime; runtime.unassign()
   ```

   This terminates the VM on Google's side instantly (verified: wipes `/tmp` + installed packages). **It MUST be the last cell you run** — executing any cell afterward makes Colab auto-allocate a fresh runtime, undoing the teardown. Note this only frees the **VM**; the MCP↔tab connection (`open_colab_browser_connection`) stays alive, so a later run does NOT need a human reconnect — running a cell auto-spins a fresh VM. So releasing between videos costs only a VM cold-start (~15–30s) + re-installing yt-dlp, not a manual reconnect. For back-to-back videos you can **leave it warm** to skip even that; otherwise release. If unsure, ask one line: *"Done with Colab, or more to fetch? I'll release the runtime if you're done."* (Colab also self-releases after ~90 min idle.)

**Re-run on demand:** if the user later says *"upgrade youtube"* / *"redo the HD step"*, run steps 1–5 again — `plan` re-scans assets.json and only targets shots still below 720p, so it's idempotent. If the runtime was released but the Colab tab is still connected, step 2's `open_colab_browser_connection` returns true instantly (no human step) and the first cell auto-spins a fresh VM; only a closed tab / restarted MCP needs a real reconnect.

## What runs per shot

Source order comes from the shot's `visual.search_sources` in plan.json. If absent (older plans), falls back to defaults by `visual.type` and `visual.specificity` (see `_DEFAULT_SOURCES` in `run.py`).

YouTube candidates go through three stages: video pick (LLM) → transcript moment finding OR visual binary search → Claude Vision validation. Pexels/Pixabay candidates are also Claude-Vision-validated (images by URL, video by sampled frames) for medium/high-specificity shots; Giphy/Wikimedia/Google still use keyword + dimension + duration scoring.

## Source media model (E1)

Sources are downloaded **full and untrimmed** into a shared pool — never cut at download time. Trim lives as metadata (`in_point`/`out_point`) and is applied by render/the editor, so a cut can be extended or held past the originally-detected moment because every frame is on disk. Shots that share an upload (same fixture/event) point at **one** file in the pool (deduped by source + id / YouTube video id), so render's media library naturally maps one media item → many timeline clips.

## Licensing stance

`run.py` reads `requirements.licensing` and gates sources automatically:
- `free_only` → skips `youtube` and `google_images` (the sources that surface
  copyrighted uploads / editorial press photos). Everything else
  (Pexels/Pixabay/Wikimedia/Archive/Giphy/Openverse) is royalty-free / CC / PD.
- `fair_use_ok` (or absent, for older sessions) → all sources allowed.

So when you craft a per-shot `--source`/`--query` override, respect the same
rule: don't hand a `free_only` project a `youtube` source — it'll be skipped with
a log line. Pick a royalty-free source instead.

## Output files

- `sessions/<id>/assets/source_pool/<key>.<ext>` — full untrimmed source media, shared across shots (`yt_<videoid>.mp4`, `pexels_<id>.mp4`, …)
- `sessions/<id>/assets/.cache/youtube/<videoid>.mp4` — worst-quality copies used only for vision validation (small; safe to delete)
- `sessions/<id>/assets_progress.jsonl` — one result per line as shots complete (growing)
- `sessions/<id>/assets.json` — summary written/rewritten after every shot. Each shot carries `file` (pool path), `in_point`/`out_point` (seconds into the source), and `visual_verdict`/`visual_confidence`. YouTube shots upgraded via Colab also carry `hd_height`/`hd_source`.
- `sessions/<id>/youtube_hd_results.json` — transient: the Colab cell's `{results, errors}` payload, consumed by `youtube_colab.py apply`. Safe to delete after.

## Code references

- `tools/assets/run.py` — CLI. `fetch` (bulk) and `shot` (per-shot) subcommands. Always call via `conda run --no-capture-output -n esta`.
- `tools/assets/search.py` — search functions per source. All return `[]` on failure (never raise).
- `tools/assets/youtube_colab.py` — YouTube HD upgrade via Colab. `plan` (collect sub-720p YouTube targets + emit the Colab download cell) and `apply` (pull hosted HD files over `source_pool` in place). Orchestrated by the SKILL, not run.py, because run.py can't call the MCP.
- `tools/assets/schema.py` — `ShotAsset`, `AssetsOutput` TypedDicts.
- `tools/assets/llm.py` — validator prompts (frame validation, transcript moment finding, video picking).
