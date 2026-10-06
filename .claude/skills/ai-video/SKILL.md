---
name: ai-video
description: Generates AI B-roll with Higgsfield-style camera moves (crash zoom, orbit, FPV drone, 2.5D parallax) on Kaggle's free GPU. Reads plan.json, fills shots typed AI_VIDEO or carrying a `generate` block, and streams results into assets_progress.jsonl exactly like the assets and motion-graphics skills — render picks them up with no special handling. Three scriptable steps (push / status / apply); the GPU work runs detached on Kaggle so the pipeline keeps moving. Stock stays as the per-slot fallback, so a failed or quota-blocked run never blocks render.
---

# AI Video Skill

You fill plan shots with **generated** footage instead of stock. The plan says
what each shot must show; you turn that into a prompt plus a camera move and
hand it to a video diffusion model running on Kaggle's free GPU.

This is the "close to Higgsfield, totally free" lane. Be honest with the user
about what that means: the moves and the look are comparable, the *reliability*
is not. Some presets need a reroll.

## Why Kaggle

The local GPU is a 4 GB RTX A2000 Laptop — every credible open video model
wants 12–40 GB, so generation has to be offloaded. Kaggle beats Colab for this
on four counts, and the whole design leans on them:

- **A real API.** `kernels push/status/output` makes this a headless background
  job. No browser MCP, no pasting cells, no scraping stdout. (Contrast
  `tools/assets/youtube_colab.py`, which needs all three.)
- **30 GPU-hours/week of guaranteed quota.** Colab free can just refuse a GPU.
- **12-hour detached sessions.** Nothing to babysit.
- **Datacenter internet**, so multi-GB weights pull in seconds.

## Preflight

1. `sessions/<session-id>/plan.json` exists. If not: *"No plan yet — run the plan skill first."* Stop.
2. Kaggle API token at `~/.kaggle/kaggle.json`. Check with
   `python -m kaggle kernels list --mine`. If it fails, tell the user to grab a
   token from kaggle.com → Settings → API → Create New Token. Stop.
3. The Kaggle account must be **phone-verified** — unverified accounts get
   neither GPU nor internet on kernels, and the run will fail with no useful
   error. If a pushed run dies instantly, this is the first thing to check.
4. No conda env needed to push. `--seed-from-assets` uses
   `conda run -n esta ffmpeg` for frame extraction (same binary render uses).

## Picking the model

`python tools/genvideo/run.py presets` lists both presets and models. Both are Wan 2.2
image-to-video, picked by the 2026-10 bake-off on a free T4 (`tools/genvideo/bakeoff/`,
SPEC.md Part 6): the same styled and real-photo keyframes through each candidate.

| Model | Use it when | Measured on a free T4 |
|---|---|---|
| `anisora` (default) | Normal case. Index-AniSora V3.2, bilibili's animation fine-tune of Wan 2.2 A14B, as Q4 GGUF. Acts the prompt (a student puts his head in his hand, nurses lift a baby), keeps real faces, hands and animals photographic. | ~14 min per 3.5 s clip on real photos, ~18 on styled keyframes; 12 GB peak |
| `wan5b` | Quota is tight, or the shot only needs its camera move. Wan 2.2 TI2V-5B in fp16. Most faithful to the start image and the planned move; adds less action and can warp animals. | ~11-12 min per 3.5 s clip; 14.6 GB peak, at the card's limit |

Gone, and why: LTX-Video melted or faded to black on 2 of 5 styled shots; SVD is weaker
than both; HunyuanVideo 1.5 never finished on a T4 in five attempts (host RAM, then
offload and decode memory).

**Budget.** At these speeds one T4 makes ~3-5 clips an hour, so 30 GPU-hours a week is
roughly 100-150 clips. AI shots are hero shots, not a whole video. `push` splits 4+
slots across Kaggle's two GPU slots (below), which halves the wait, not the quota.

## Start images (every shot is image-to-video)

Both models animate a start image; there is no text-to-video. `push` gives every AI shot
one, in this order (SPEC.md Parts 4-6):

1. the character's LoRA keyframe (`genchar render --session`), else its `ref.png`;
2. a keyframe drawn by SDXL on the same Kaggle run: styled by the session's look refs
   when there are any, plain SDXL from the prompt when there aren't;
3. with `--seed-from-assets`, the frame already fetched for the shot rides along as the
   keyframe's backup, used only if the keyframe fails.

`push` refuses a run where any slot would have no start image.

## Clip length

Each slot generates just enough frames to cover its shot, in the `4k+1` counts Wan's VAE
needs: 17 frames minimum, up to the model's trained window (AniSora 81 frames at 16 fps,
Wan 5B 121 at 24 fps, both 5 s). Short shots cost less GPU time. `--chain N` covers
shots longer than 5 s by feeding the last frame of each segment into the next; drift
accumulates per hop, so 2-3 segments is the honest ceiling.

`generate.hd: true` on a shot renders it at 1280x720 instead of 832x480. It is untested
on a T4; on out-of-memory the slot retries at 832x480 and its result says `hd_fallback`.

## Run it

Three steps. The GPU work happens between step 1 and step 3, detached.

```bash
# 1. Build the notebook(s) and start the run (returns immediately)
python tools/genvideo/run.py push --session sessions/<id> --seed-from-assets

# 2. Poll — "queued" | "running" | "complete" | "error" (overall, plus each half)
python tools/genvideo/run.py status --session sessions/<id>

# 3. Pull the clips in, check them, publish them on the assets feed
python tools/genvideo/run.py apply --session sessions/<id>
```

**Two runs.** With 4 or more slots, `push` splits them into two halves of near-equal
work and pushes `esta-gen-<session>` and `esta-gen-<session>-b` (Kaggle allows two GPU
runs at once). If the second hits the two-run limit, the first still runs; push the
other half later with `push --half b`. `apply` merges whatever both halves finished and
lists the slots of a half that didn't. `--split 1` keeps one run.

**The clip check.** `apply` looks at every clip over its shot's own length. A clip that
goes dark, or whose picture stops resembling its first frame (it melted into something
else), is not published: its keyframe goes in as a still, render gives it the shot's
planned camera move, and the review page flags it `gen_check`. Thresholds were
calibrated on the bake-off clips: every AniSora and Wan 5B clip passes, LTX's black and
melted clips fail.

Useful flags on `push`:

- `--dry-run` — build and report without pushing. **Always dry-run first** when
  the user is choosing presets; it shows the exact prompt per shot for free.
- `--shots 3,7,9` — force specific shots regardless of their `visual.type`.
  This is how you generate B-roll for a plan the plan-skill wrote before
  `AI_VIDEO` existed.
- `--preset <name>` — preset for shots that don't name their own.
- `--style cinematic|documentary|broadcast|gritty` — the look suffix, used only when the
  session has no `look_style` (a session look replaces it).
- `--model anisora|wan5b`, `--chain`, `--split 1|2`, `--half a|b`, and raw overrides
  (`--width`, `--steps`, `--guidance`, …).

Between push and apply, **do not block**. Announce the run and move on to
whatever the conductor says is next; come back when the user asks or when the
next step needs `gen_video.json`.

## How a shot asks for generation

Either marker works, so the plan skill can adopt this incrementally:

```jsonc
// by type
"visual": { "type": "AI_VIDEO", "desc": "..." }

// or by carrying a generate block on any shot
"visual": {
  "type": "REAL_FOOTAGE",
  "desc": "...",
  "generate": { "preset": "crash_zoom_in", "prompt": "optional override" }
}
```

Preset resolution is **explicit > implied by `fx` > `--preset` default**. A shot
whose `fx` already says `zoom_in` becomes `push_in` on its own, so existing
plans stay meaningful.

## Characters (SPEC.md Part 4)

A shot with `"generate": {"character": "<name>"}` shows a character designed in genchar (`characters/<name>/`). Keep it on-model this way:

1. Once per character (not per video): `python tools/genchar/run.py explore --name <name> --desc "..." --look <requirements.look> --look-style "<requirements.look_style>"`, `pick`, `sheet`, `contact`, `cull`, `train` (the LoRA). Each is a Kaggle run; `status`/`fetch` between them.
2. Per session, before `push`: `python tools/genchar/run.py render --name <name> --session sessions/<id>` renders one keyframe per shot naming the character, with its LoRA, then `status --mode render` and `fetch --mode render`.
3. `push` seeds each character shot from its keyframe (`characters/<name>/render/<session>__s<n>.png`), else the picked design (`ref.png`), else a keyframe drawn from a prompt that leads with the character's description. The push output's `seeding.characters` says which per shot.

`requirements.look_style` is appended to every generated prompt, so realistic and cartoon sessions use the same commands.

**Look references (SPEC.md Part 5).** When the session has images in `look_refs.json` (the requirements skill or the Look card), they steer the pixels, not just the words:

- Pass `--session sessions/<id>` to genchar `explore` (it's remembered for `sheet` and `render`). Design and sheet use the `character` refs; render uses `character` + `world`. A character can carry its own refs with `--style-refs <folder>` (kept in `characters/<name>/style_refs/`, they replace the session's character refs). `--ref-strength` (default 1.0, 0 = off) scales how hard they pull.
- `push` gives every AI shot that isn't seeded by a character a **keyframe**: SDXL draws its first frame on the same Kaggle run (styled by the `world` refs when the session has any, plain otherwise), then the video model animates it. The push output's `seeding.keyframes` lists them. `--ref-strength` applies here too. With `--seed-from-assets`, the stock frame rides along as each keyframe slot's backup (`seeding.backups`) and is used only if its keyframe fails.
- If the IP-Adapter fails to load on Kaggle the run continues without refs; genchar `fetch` shows `ref_error` and each generated clip's result carries its keyframe note.

**Talking shots.** A shot with `"talk": true` is lip-synced on the same Kaggle run: `push` cuts that shot's slice of `audio.wav` and ships it with the job; after generating, the notebook loops the clip to the line's length at 25 fps and runs LatentSync 1.5 (fits a 16 GB T4). `apply` publishes the synced clip (`gen_<n>_talk.mp4`) or, when sync fails (no face, setup error), the silent clip with the reason in the feed row's `lipsync`. `--lipsync off` skips it. Lines under 0.5 s are not synced.

## Choosing a preset

`presets.json` carries 22 of them with a `reliability` rating. Respect it:

- **high** (`push_in`, `pull_back`, `dolly_in/out`, `pan_*`, `tilt_*`,
  `handheld`, `static`, `parallax_2d`) — generate once, move on.
- **medium** (`crash_zoom_in/out`, `orbit_*`, `crane_*`, `fpv_drone`,
  `whip_pan`, `time_lapse`) — usually lands; budget one reroll.
- **low** (`bullet_time`, `rack_focus`) — spectacular or incoherent. Only when
  the user explicitly wants that shot, and warn them it may take several tries.

Match the move to the subject, not to the excitement level. `fpv_drone` loves
environments and hates close-ups of objects; `orbit_*` needs a clearly
separable subject or it degenerates into a pan; `whip_pan` is a transition tail,
so generate it and trim to the last ~0.4 s.

## Integration — nothing in render changes

`apply` writes generated clips to `assets/source_pool/gen_<key>.mp4` and appends
an ordinary line to `assets_progress.jsonl` with `"source": "genvideo"`. Render
already resolves that feed **later-line-wins**, so a generated clip supersedes
the stock pick for that shot automatically.

This is the same trick the motion-graphics skill uses, and it has the same two
consequences worth stating to the user:

- The **stock pick stays on disk** as the per-slot fallback. A failed slot, a
  blown quota, or a kernel that times out leaves the video renderable.
- Run `ai-video` **before the final render pass**, alongside `assets` and
  `motion-graphics`. If render already ran, just re-run it — the feed is the
  source of truth.

The kernel checkpoints `gen_results.json` after every slot, so a run that hits
the 12-hour wall still yields everything it finished. `apply` takes whatever is
there.

## Reporting back

Show the user, in plain language: how many slots generated, which preset each
got, and which failed with why. Name the failures explicitly — a slot that
silently kept its stock footage is exactly the kind of thing they need to know
about before they open the editor.

Then hand off to whatever the conductor names next
(`python tools/pipeline/conductor.py next --session sessions/<id>`), which in
the canonical flow is the final `render` pass.
