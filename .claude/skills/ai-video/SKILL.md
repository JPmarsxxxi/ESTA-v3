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

`python tools/genvideo/run.py presets` lists both presets and models.

| Model | Use it when |
|---|---|
| `ltx` (default) | Normal case. Fast, T4-safe, does both text- and image-to-video. |
| `ltx-distilled` | Many slots at once — ~8 steps instead of 40, several times faster, slightly softer motion. |
| `hunyuan` | The shot has to actually land — hero B-roll, anything with a person or a readable subject. HunyuanVideo-1.5 (8.3B) is the best model that still fits a free T4: fp16-native, step-distilled to 12 steps. Budget ~2–3x an LTX slot in GPU minutes. |
| `hunyuan-hq` | One or two shots where quality beats throughput. Same model undistilled with real CFG at 30 steps — roughly 5x `hunyuan`. Never a whole video's worth. |
| `svd` | LTX is misbehaving. Image-to-video only, no text prompt, so it **requires** `--seed-from-assets`. |
| `wan5b` | Kept for comparison only. bf16, and neither Kaggle GPU has native bf16, so it falls back to fp16 and crawls. |

**Why not the frontier model.** MiniMax H3 / Hailuo 3 is a genuinely better
video model and its weights are public — but it's a 33B transformer whose
license excludes the US, EU, UK and Korea, and Kaggle's GPUs are US
datacentre. It does not fit this lane on either count. Same story for Wan
2.5+: closed weights since 2.2. HunyuanVideo-1.5 is the ceiling of what a free
16 GB T4 can actually run.

**Measured by other people on 16 GB cards** (r/StableDiffusion, Nov 2025 -
Aug 2026), since our own numbers are LTX-only so far:

- 4060 Ti 16 GB, 720p i2v, same prompt: Hunyuan cfg-distilled (cfg 1, 6 steps)
  **239 s**, Wan 2.2 **387 s**, Hunyuan fp16 (cfg 6, 20 steps) **587 s**.
- 5060 Ti 16 GB, 640x480, 81 frames, 4 steps, both on their 4-step LoRAs:
  Hunyuan **32 s** of sampler time vs Wan 2.2 **81 s** - "almost 3x faster".
- A 12 GB card OOMs Hunyuan at 120 frames but runs **81 frames** fine. We have
  16 GB and sequential offload so 121 should hold, but if a slot OOMs on Kaggle,
  `--frames 81` (3.4 s, which is about our average shot anyway) is the first fix.
- **If the motion looks like slow-mo**, that's a known Hunyuan failure and it
  comes from over-aggressive step reduction, not from the model. Reported fixes,
  in order: raise CFG off 1.0 (`--guidance 1.3` - users report 1.2-1.4 kills it),
  then raise steps. The community consensus on the distilled checkpoints is that
  cfg 1 is fine but **4 steps is not** - 6-8 is the floor. Our default is 12.
- Expect rerolls. One tester needed ~10 seeds to get a specific action to land,
  even at 480p with the distilled model. Budget seeds, not just minutes.

**Mixing models in one push isn't free.** `hunyuan` ships t2v and i2v as
separate checkpoints, so a run with some slots seeded and some not downloads
two denoisers. Split those into two pushes if quota is tight.

## Text-to-video vs image-to-video

Default is text-to-video: the model invents the shot from the prompt.

`--seed-from-assets` makes it **image-to-video** instead — it pulls the frame
already fetched for that shot out of `assets_progress.jsonl`, scales it to the
generation size, and embeds it as the first frame. The generated motion then
inherits the footage the user already picked rather than inventing a new
subject.

**Prefer image-to-video whenever assets has already run.** It is the single
biggest quality lever here, and it's what makes `parallax_2d` work — that
preset turns a still the user chose into something that reads as real footage.

## The 5-second window

These models are trained on a fixed frame count (LTX: 121 frames @ 24fps ≈ 5 s).
That's a training window, not a hard cap — ask for more and you get drift, not
an error.

`--chain N` beats it by feeding the last frame of each segment into the next as
an i2v seed. Drift accumulates per hop, so **2–3 segments is the honest
ceiling**. Only bother when a shot actually needs it: real plans in this repo
average 3.44 s per shot, with the large majority under 6 s, so most slots need
`--chain 1` (the default).

## Run it

Three steps. The GPU work happens between step 1 and step 3, detached.

```bash
# 1. Build the notebook and start the run (returns immediately)
python tools/genvideo/run.py push --session sessions/<id> --seed-from-assets

# 2. Poll — "queued" | "running" | "complete" | "error"
python tools/genvideo/run.py status --session sessions/<id>

# 3. Pull the clips in and publish them on the assets feed
python tools/genvideo/run.py apply --session sessions/<id>
```

Useful flags on `push`:

- `--dry-run` — build and report without pushing. **Always dry-run first** when
  the user is choosing presets; it shows the exact prompt per shot for free.
- `--shots 3,7,9` — force specific shots regardless of their `visual.type`.
  This is how you generate B-roll for a plan the plan-skill wrote before
  `AI_VIDEO` existed.
- `--preset <name>` — preset for shots that don't name their own.
- `--style cinematic|documentary|broadcast|gritty` — the look suffix.
- `--accelerator t4|p100`.
- `--model`, `--chain`, and raw overrides (`--frames`, `--width`, `--steps`, …).

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
