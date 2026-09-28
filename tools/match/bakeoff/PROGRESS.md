# M5.1 bake-off — status

## Update 2026-09-28 (cloud session)

The first results raised four problems; all are fixed in code, none re-run yet:

1. **Tagging was too slow** (about 45 s a shot, 50-63 GPU-min for 77 shots). Models
   ran in bf16, which the T4 only emulates, on full-resolution frames. Now: fp16
   (bf16 fallback if a model's first answers are garbage), frames capped at 448 px,
   80 new tokens instead of 150. Expect several times faster.
2. **1.000 scores on panels / clips_in_shot were probably meaningless**: if every
   shot in the key has the same answer, always guessing it scores 100 %. Scoring is
   now balanced accuracy next to the always-guess baseline, and a field with one
   value in the key is reported untestable. Check with `kaggle.py labels`.
3. **kind** now uses five classes (screen and ai fold into footage), three frames
   per shot and a measured motion hint. Gemma 4 E4B is in the tagger list.
4. **Theme / partial re-runs**: the kernel records raw predictions only; `apply`
   scores them locally with `scoring.py` and merges with earlier runs. The SigLIP 2
   / CLIP fix now reads the projected `pooler_output` instead of averaging patches.

Next run:
```
python tools/match/bakeoff/kaggle.py labels          # label counts in the key
python tools/match/bakeoff/kaggle.py push --only tags,theme
python tools/match/bakeoff/kaggle.py status
python tools/match/bakeoff/kaggle.py apply
```
`--models gemma4-e4b` (or any candidate names) narrows a run further. Cuts are
already decided (TransNetV2) and don't need re-running. DINOv3 needs its licence
granted first; until then it errors on its own without affecting the rest.

M5.2: requery now also refetches the shot's clip in the background (the assets
skill's `shot` fetch, as a tracked job) once the assets stage has run, and clears
`queries_stale` when it lands. Still to be clicked through in a browser on a real
session.


## Earlier: overnight build

## What's done

**Part A** — `extract.py`, `candidates.py`. Meta + contact sheets for both
answer-key videos; a Kaggle kernel ran real TransNetV2 + PySceneDetect (AutoShot
skipped — its only checkpoint is Baidu Pan, no reachable mirror). 93 raw cut
candidates found across both videos.

**Part B** — `key_build.py`. Visual review of all 93 candidates plus a
contact-sheet scan for missed cuts → **77 confirmed shots** (63 + 14). You
spot-checked 13 shots directly in chat and caught 7 real mislabels (5
reaction/meme clips mislabeled `graphic`/`footage`, 2 genuine still images
mislabeled `graphic`) — corrected. Negative-style pool built (15 YouTube
thumbnails, calm/cinematic query, opposite style to both answer-key videos).
Key frozen with your explicit shortfall exception (77 vs the ~80 target; thin
`still`/`screen`/`ai` ground-truth support) recorded in `key/frozen.json`.

**Part C** — `kaggle.py`. Ran three times; each run's failures were real and
specific (the per-candidate try/except design worked exactly as intended —
nothing ever crashed the whole kernel). Bugs found and fixed along the way:
- Kaggle's dataset upload silently skips subdirectories without `--dir-mode`
  (undocumented) — worked around by flattening the frames dataset to
  `<slug>__shot_NNN.jpg` naming rather than touching the shared `kaggle_lane.py`.
- With 2+ datasets attached to one kernel, Kaggle mounts them under
  `/kaggle/input/datasets/<owner>/<slug>/`, not `/kaggle/input/<slug>/` — fixed
  with a recursive-search directory resolver.
- Qwen3-VL-8B's `load_in_4bit=True` shorthand isn't accepted by this model
  class — switched to explicit `BitsAndBytesConfig`.
- SigLIP2/CLIP's `get_image_features()` returned unpooled per-patch features
  (shape (196, hidden), not (hidden,)) — added mean-pooling.
- Florence-2-large hit two separate transformers-version incompatibilities
  (both fixed); a third (`_supports_sdpa`) is fixed but **not yet re-run** —
  see below.
- Gemma3-4b and DINOv3-small are genuinely gated on HuggingFace — real 403s,
  not bugs. Need your HF account (the one behind `config.yaml`'s `hf_token`) to
  accept the license at these two pages, then a re-run will pick them up:
  - https://huggingface.co/google/gemma-3-4b-it
  - https://huggingface.co/facebook/dinov3-convnext-small-pretrain-lvd1689m

**Part D** — `local_check.py`. Ran for real against the actual cuts winner
(TransNetV2, 8.60 s/min on this machine's GPU) — result is in `results.md`.

**Current real results** (`tools/match/bakeoff/results.md`, from the 3rd/latest
Kaggle run):
- **Cuts winner: TransNetV2** (F1 0.928, clears the 0.90 bar; PySceneDetect 0.792, fails).
- **Tags**: `text_on_screen` → qwen3-vl-4b (0.935), `panels` → qwen3-vl-8b (1.000),
  `overlay` → qwen3-vl-4b (0.909), `clips_in_shot` → qwen3-vl-8b (1.000). `kind`
  has **no winner** — both Qwen models scored well under the 0.85 bar (0.46, 0.42)
  on this 7-class problem with thin per-class support; correctly dropped per the
  spec's own AC #4, not a bug.
- **Theme: no winner yet.** The pooling bug above is fixed in `kaggle.py` but
  **not re-run** — Qwen3-VL-8B alone cost 63 GPU-minutes and 4B cost 50 in the
  last run, so a full re-run costs roughly another 1.5-2 hours of the shared
  30 GPU-h/week Kaggle quota. That's a resource call for you, not something I
  spent autonomously. To pick up the theme fix (and possibly Florence-2's):
  ```
  python tools/match/bakeoff/kaggle.py push
  python tools/match/bakeoff/kaggle.py status   # poll until complete
  python tools/match/bakeoff/kaggle.py apply    # rewrites results.md
  ```

## What's actually left
1. **Your call on the theme re-run** above (costs real GPU quota).
2. **Your call on Gemma3/DINOv3** — accept their licenses if you want them in
   the comparison, or leave them dropped.
3. **You review `results.md` and tell me which winners to accept.** This is the
   spec's own explicit checkpoint — `kaggle.py approve` never runs on its own;
   it only writes `config.yaml`'s `match.models` once you've named winners:
   ```
   python tools/match/bakeoff/kaggle.py approve --cuts transnetv2 \
     --tags text_on_screen=qwen3-vl-4b,panels=qwen3-vl-8b,overlay=qwen3-vl-4b,clips_in_shot=qwen3-vl-8b \
     --drop-tag kind [--theme <winner, once you have one>]
   ```
4. Once approved, M5.1 is done and M5.2 is next per the spec order you chose
   (see the separate M5.2 status below — already built).

## M5.2 (queries follow the shot) — built in parallel while M5.1's Kaggle jobs ran

Per the spec text (`tools/plan/ops.py` explicitly **not** modified — the backend
calls requery after `split` returns):
- `server/planner.ts`: new `POST/GET /_plan/api/requery` (mirrors
  `planRewrite`/`planRewriteStatus`, but auto-applies to `plan.json` directly
  rather than staging a reviewable proposal — this is a mechanical follow-up,
  not something the spec asks the user to review each time). Split's success
  path now fires requery for both new halves automatically. `REWRITE_SYSTEM`
  now also returns `search_sources` when it changes `desc`/`type`, and respects
  `queries_pinned`.
- `apps/editor/src/esta/panels/planner-panel.tsx`: type-dropdown changes
  trigger requery (unless pinned) on save; manually editing the queries
  textarea sets `queries_pinned` on save; an Unpin control and a live
  "requerying…" status appear in the Search section; `queries_stale`/
  `queries_pinned` show in the shot-list sidebar tags.
- `tools/plan/schema.py` updated to match the real runtime shape
  (`search_sources`, `specificity`) plus the three new fields — logged in
  `PORTING.md` with the reason (it's a v2-copied file).
- Verified: `bun run typecheck`, `bun run lint` both clean. **Not** verified:
  actually exercised in a browser — the dev server was killed by the harness's
  memory-pressure reaper mid-session and I was told not to restart it without
  being asked. Please try it live and tell me if anything's off; I caught and
  fixed two real logic bugs (a dead `half` parameter, and `queriesEditedByHand`
  never resetting so Unpin would get immediately re-pinned) through code review
  alone, but static checks can't substitute for actually clicking through it.

## Not started
M5.3 (inspo profile), M5.4 (scoring + score card), M5.5 (auto-adjust) — per
your "just build all you can," I chose to stop expanding into unverified
surface area here rather than start a third large piece with no ability to
test any of it live, given the real bugs already found in M5.1/M5.2 by
careful review. Ready to continue whenever you want to pick it up.
