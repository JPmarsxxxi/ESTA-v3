# Describe bake-off and nudge trial (M5 match)

Experiment, not pipeline code. It replaces only the inspo `kind` tag (tools/match/tag.py, Gemma on Kaggle) with a
per-shot plain description plus likely sources from Claude Haiku, then runs score.py and adjust.py unchanged on
the first 60 s of `do-alphas-even-exist-2026-09-29`, with `inspo/videoplayback-2.mp4` as the style inspo.
`inspo/trading-strategies-27.mp4` is the session's earlier inspo, kept for comparison runs.

Open `bakeoff.html` for everything with pictures: nudge before/after per shot, match cards, every inspo shot with
its keyframe, description, sources and text/overlay answers.

## Run

System python (TransNetV2, SigLIP/DINO embedder, faster-whisper, `claude` CLI on PATH). The session folder must exist
locally under `sessions/` (it is on this branch except `assets/`; the final-stage score needs the assets).

    python prep.py               # TransNetV2 cuts + 384px keyframes (skips if shots.json exists)
    python speech.py             # words spoken per shot (inspo via faster-whisper, ours from timestamps.json)
    python haiku.py              # describe + sources + text_on_screen + overlay_extra, 10 shots per call
    python harness.py haiku      # full match, plan + final -> match_haiku.json
    python harness.py haiku nudge   # adjust.py at plan stage on a scratch copy -> nudge_haiku.json
    python page.py               # bakeoff.html

## Results (2026-10-01/02)

Describe lane, 225 shots (208 inspo + our 17):

| Run | Cost | Wall time | Kind right (our 17) | Source top-1 / top-3 |
|---|---|---|---|---|
| Haiku, image only | $0.43 | 3.2 min | 14/17 | 7/17, 11/17 |
| Haiku, image + speech | $0.63 | 5.3 min | 17/17 | 8/17, 8/17 |
| Gemma 4 E4B on Kaggle | - | cancelled after ~30 min queued/running | - | - |

- `claude -p` cost is 7x lower with `--strict-mcp-config --setting-sources ""`: without them every call carries
  ~29k tokens of MCP tool definitions and skills.
- Haiku guesses "youtube" for ~80% of inspo shots and calls clean Pexels stock "youtube". Kind (footage/still/
  graphic) is reliable; exact source is not. Hence: score asset mix by kind, use sources only to guide search.

Match, first 60 s vs videoplayback-2 (pass: 80 overall, 70 per section):

| | a mix | b colour | c theme | d complexity | e duration | overall |
|---|---|---|---|---|---|---|
| plan, before nudge | 64.0 | n/a | 68.5 | 40.9 | 65.5 | 60.9 |
| plan, after nudge (best run) | 95.2 | n/a | 70.5 | 38.6 | 79.9 | 72.8 |
| final, no nudge | 64.0 | 66.4 | 67.8 | 40.9 | 65.5 | 61.7 |

Nudge cost ~$0.15-0.19 of Haiku per run; scores vary ~2 points run to run from the wording step.

## Next actions

In order. 1-4 are cheap and testable on this harness; 5-8 are pipeline changes that need `/spec` first.

1. **Like-for-like text check (d).** Ours counts every shot as text because subtitles are burned in; the inspo's
   `text_on_screen` counts any visible text. Ask "text other than speech subtitles" on both sides and stop counting
   our subtitles. This is the main blocker: d sits at ~39 and nothing in adjust can move it.
2. **Splits: lock the half that keeps the clip.** The half whose words fit the existing clip keeps it (SigLIP image
   vs each half's words) and the other refetches - done here. Still to do: the kept half's desc gets rewritten by a
   later theme pass in the same nudge (shot 3); lock it. When the fit margin is under ~0.01, default to the first half.
3. **Damp the youtube pull in source guidance.** Override the writer's lead source only when >=3 of the 5 nearest
   inspo shots agree; otherwise keep the writer's choice (generic reactions belong on Pexels).
4. **Duplicate check in the nudge.** Neighbouring shots end up with near-identical descs (3/5 bed shots, 19/20 money
   counter). Send each rewrite its neighbours' descs; reject near-duplicates.
5. **Coverage hard checks.** The plan ends at 764.66 s but the voice runs to 843.4 s (~79 s of no visuals) and there
   are 44 gaps (~22 s of black) between shots. Fail match outright on any gap/overlap > 0.1 s or uncovered voiceover.
6. **One pacing source.** Plan reads `avg_shot_duration` 4.84 s from style-analysis (OpenCV); match measures the
   inspo at 2.4 s mean (TransNetV2). Plan against the TransNetV2 shot-length distribution and score its shape, not
   mean+median. The plan skill is one sentence = one shot today, so pacing follows sentence length.
7. **Fold the describe lane into tools/match.** Replace tag.py's kind question with describe+sources (+speech),
   via `claude -p` with the lean flags; add the same flags to adjust.write_wording. faster-whisper on system python
   falls back to CPU (cublas64_12.dll missing): 190 s for the 8-min inspo, seconds on GPU.
8. **Final-stage nudge** (refetch the stale halves through auto-pick, re-render, re-score) is untried.

Housekeeping: `tools/kaggle_lane.wait_dataset_ready` gives up on the first transient "error" status right after an
upload (a retry succeeded); two orphan Kaggle kernels from the cancelled Gemma run (`esta-vlm-gemma-job*`) can be
deleted. The export of the full video from the Edit stage was started but never confirmed finished.
