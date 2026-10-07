# Usage, speed and free vision models: results

Branch `perf-vision`, worktree `D:\ESTA-v3-perf`, 2026-10-07. Spec: `SPEC.md` Part 8 (M11). Plan it executes: `reports/HANDOFF-limits-speed-vision.md` (written against the M1 code; re-based here on M10).

## 1. Where the usage went (measured, not estimated)

`python tools/usage/report.py --transcripts` over every Claude Code transcript of the v3 repo (2,584 files, 2026-10-01 to 10-07). Shares weight tokens by API list price, only to rank the items.

| What | Calls | Tokens (M) | Share |
|---|---|---|---|
| **One interactive Opus 5.5 conversation**: 821 turns over 7 days, avg ~390k context tokens per turn, peak 967k, compacted twice | 1 session | 314 cache-read, 6.9 cache-write, 0.6 out | **~89%** |
| `tools/assets/llm.py` Haiku: YouTube frame search | 569 | 18.9 in, 0.6 out | 5.5% |
| `llm.py` validate (stock / Pinterest / YouTube segments) | 194 | 6.5 in | 1.8% |
| Lean `claude -p` (autopick judge, rewrites, describe) | 92 | 0.5 in, 0.6 out | 1.6% |
| `llm.py` pick-videos + find-moment (text) | 169 | 5.5 in | 1.6% |
| **Calls that hit the session limit** (10-06 and 10-07) | **1,507** | 0 | (no tokens, but see below) |

What that means:

- **The main conversation is the limit problem.** Every turn re-reads the whole context. Past ~300k tokens each turn costs more than the whole vision pipeline does per shot. No code change fixes this. See section 5 for what does.
- **The `llm.py` calls were ~12x heavier than needed.** Each was a full Claude Code session: system prompt, tool schemas, both MCP servers, hooks, CLAUDE.md, the skill listing, plus Haiku thinking. That is ~33k input tokens and 15-19 s (median) per check.
- **The limit approved clips.** Once the limit hit, 1,507 checks got "You've hit your session limit" back. `validate_frames` turned any failure into `{"matches": true, "confidence": 50}`, so those candidates were approved unchecked, and the gather kept firing a doomed call per candidate.

## 2. What changed (committed on `perf-vision`)

| Change | Effect (measured) |
|---|---|
| `llm.py`: lean `claude -p` (stream-json, frames inline and downscaled to 768 px, `--strict-mcp-config --setting-sources "" --tools ""`, no session file, thinking off) | Validate: **2.6k tokens, 5 s** (was ~33k, 15.7 s median). Text calls: 1.1k tokens, 2.4 s. About **6x cheaper and 3x faster** per check. |
| Fail closed: failed/limited check returns `None` (unvalidated) | No clip is approved by a failure. Medium/high-specificity shots still need a real match (B2). |
| Limit breaker shared by `llm.py` and `describe.ask` (judge, rewrite, describe) | After the first limit/auth reply, no more `claude` spawns in that process. |
| Usage ledger `<session>/usage.jsonl` + `tools/usage/report.py` | Every headless call's tokens, cost and seconds, per session. `--transcripts` mode reproduces section 1 for any project. |
| `describe.ask` thinking off (`match.describe.thinking: true` restores it) | Judge calls 6.3 s instead of 19.2 s median (section 3 shows no accuracy cost). |
| `server/planner.ts` Rewrite/Command/Requery: lean flags | Same ~30k-token overhead removed per click. |
| `UserPromptSubmit` hook: path check before `conda env list` | 60 ms instead of 1.4 s on every prompt you send. |
| Plan skill + `tools/plan/append_shot.py` | Shots stream as one appended line each, and `plan.json` is assembled by script, instead of re-writing the whole accumulated file after every shot (output grew with the square of the shot count). |
| `kaggle_lane.wait_dataset_ready` | No longer gives up on Kaggle's transient "error" status right after an upload (it broke this run's first push). |
| `assets.moment_finder: clip` (opt-in, default stays `claude`) | Local CLIP replaces the 3-call Haiku binary search. Not recommended yet: see section 3. |

Tests: `python -m pytest tools/usage/tests tools/match/tests -q` (137 pass, no network). `bun run lint` clean; server typecheck clean; the editor typecheck shows only the known upstream changelog baseline.

## 3. Free vision models: the eval

**The eval set** comes free from the transcripts: Claude Code stores the exact images each `claude -p` call sent and Haiku's reply. `tools/vision_eval/extract.py` turned this run into **1,295 replayable decisions** at `D:\esta-perf\vision_eval\do-alphas`:

- validate: 194 (Haiku said 72 match, 122 mismatch)
- frame_search (pick 1 of 5 frames): 563
- autopick judge, one item per shot (inspo frame + 2-3 candidates): 538

Haiku's original answer is the baseline, **not** ground truth: nobody has labelled these yet (section 4).

**Results** on the same fixed sample (60 per kind, seed 7) unless noted. "Agree" = same answer as the original Haiku call.

| Backend | Validate agree | Says match where Haiku said mismatch | Frame search: same frame / within 1 | Judge: same pick | JSON valid | Median s |
|---|---|---|---|---|---|---|
| Haiku lean, thinking off (new default) | 85% | 2.4% | 53% / 77% | 80% | 100% | 6-8 |
| Haiku lean, thinking on (control) | 85% | 4.9% | 63% / 80% | 72% | 99% | 13-19 |
| CLIP ViT-B/32, local (all 563) | - | - | 35% / 62% | - | 100% | 0.3 |
| SigLIP 2 base, local (all 563) | - | - | 40% / 64% | - | 100% | 1.0 |
| Qwen3.5-9B on Kaggle 2xT4 | 80% | 7.3% | 48% / 70% | 68% | 100% | 9-18 |
| Qwen3-VL-4B, local 4 GB GPU | 3 items only (see 5) | | | | | 35 |

Chance for frame search is 20% same frame, ~52% within one.

What the numbers say:

1. **Thinking off costs nothing measurable.** Lean Haiku agrees with the original equally often with thinking on or off (85% on validate). It is ~2x faster and ~4x fewer output tokens.
2. **Haiku is its own noise floor.** Re-asked the same question, Haiku flips ~40% of its own "match" verdicts to "mismatch" (with or without thinking), but almost never the other way (2-5%). The frame search agrees with itself only 53-63% of the time. So "agreement with Haiku" cannot go above roughly these numbers for any model. That makes human labels essential before deciding anything.
3. **CLIP/SigLIP are not a frame-search replacement yet.** 35-40% same frame vs Haiku's 53-63% self-agreement. They are fine as a free pre-rank (autopick already does this with SigLIP + DINO before the judge).
4. **Qwen3.5-9B (free, Kaggle) is close to Haiku but a step behind on every axis.** It loaded and ran fine on the T4s (fp16, transformers, thinking off; the sm_75 risk from the handoff did not bite for this model), with 100% valid JSON. It agrees with Haiku 80% on validate (Haiku with itself: 85%), 48% on frame search (53-63%), 68% on the judge (72-80%), and it is a little more willing to say "match" (7.3% vs Haiku's 2.4-4.9%), which is the costly direction. With 60 items per kind these gaps are inside the noise (about +-10 points), so only labels can settle it. Cost: 162 s model load plus 2,250 s for 180 items, 12.5 s per item one at a time: ~0.7 Kaggle GPU-hours for this sample. A full video's ~1,300 checks would be ~4.5 GPU-hours this way, so production use needs batching (vLLM) and the SigLIP pre-rank to cut the item count, and it shares the ~30 h weekly quota with voice and AI video.
5. **The local 4B test did not get a fair run tonight.** Your running session's autopick job was using the 4 GB GPU, so llama-server could only fit part of Qwen3-VL-4B on it (1.5 tok/s generation, ~35 s per item on the 3 items that ran). I stopped it so it would not slow your run. A watcher then waited for the GPU to free up, but Claude Code killed it (and the pollers) when the PC ran low on memory. Nothing was left running. The models and llama.cpp are on D:, ready: see section 4 step 5.

## 4. What you need to do for the decision

1. **Label** (the only thing I can't do for you). Open `D:\esta-perf\vision_eval\do-alphas\label.html` in a browser served from that folder: `cd D:\esta-perf\vision_eval\do-alphas; python -m http.server 8799`, then http://127.0.0.1:8799/label.html. Validate queue: `M`/`N`. Judge queue: `1`-`3` or `0` for none usable. `S` skips. 150-300 labels is enough, weighted to validate. Click **Download labels.jsonl** and drop it into that folder.
2. Re-score: `python tools/vision_eval/replay.py --set D:/esta-perf/vision_eval/do-alphas --score`. With labels it adds `false_match_rate` / `false_reject_rate` (validate) and `picked_when_human_said_none` (judge).
3. **Decision rule** (handoff): adopt an open judge only if its false-match rate on your labelled negatives is within ~3 points of Haiku's and JSON validity is >= 99%.
4. To grow the set on the next run: `ESTA_VISION_CAPTURE=1` before the assets/autopick job saves every vision call's frames and verdict under `sessions/<id>/vision_eval/`. Add them with `extract.py --captures sessions/<id>/vision_eval`.

5. **Local 4B spike, when the PC is otherwise idle** (no autopick/assets job, Chrome mostly closed): `python tools/vision_eval/local_spike.py 30` (from the worktree) waits for a free GPU, then runs Qwen3-VL-4B and Qwen3.5-4B through llama-server on 30 items per kind and yields if a pipeline job starts. Then re-score as in step 2. Expect it to work only as a junk pre-filter (handoff: "never approves").

## 5. Recommendations, in order of impact

1. **Cap the main conversation's context (biggest lever, your call).** Add `"autoCompactWindow": "300k"` to `.claude/settings.local.json` (or set `CLAUDE_CODE_AUTO_COMPACT_WINDOW=300k`). On this run that would have cut roughly **half of the main thread's tokens**, so ~45% of total spend (sawtooth estimate; compaction itself costs a summary pass). Even better is a fresh session per milestone/stage with a resume file, which you already do with `esta-resume.txt`: the run's one conversation spanned 7 days and M5-M10. Use the UI stage buttons for pipeline stages; they run as separate short `claude -p` jobs.
2. **Merge `perf-vision`.** The `llm.py` fix alone makes the asset checks ~6x cheaper and ~3x faster, and stops the limit from approving footage. Nothing in the pipeline's behaviour changes except fewer, faster, safer calls.
3. **Run `python tools/usage/report.py --session sessions/<id>` after the next run** to confirm the per-kind numbers on a full run.
4. **Free vision models: label first, then decide** (section 4). Until then, Haiku lean is the right default: it costs ~$0.003 per check.
5. **Not done, on purpose:**
   - faster-whisper batching (notebook-ground-truth constants; CPU-pinned by design; 3-5 min off the critical path);
   - hiding the 22 `ss-*` skills (~2-3k tokens in a ~300k context; you use them for UI work);
   - pinning skills to Sonnet or switching the judge (quality decisions for you, after the labels);
   - style-analysis on Kaggle (P3.2): it only reads ~8 frames per reference, a small share.

## Files

- `tools/usage/` ledger, report, tests. `tools/vision_eval/` extract, replay, label, kaggle. `tools/plan/append_shot.py`.
- Eval data, models and llama.cpp are on `D:\esta-perf\` (C: has ~25 GB free): `vision_eval\do-alphas\` (items, `results_*.jsonl`, `metrics.json`, `label.html`), `models\` (Qwen3-VL-4B and Qwen3.5-4B GGUFs), `llama\` (llama.cpp b11476 CUDA 12.4).
