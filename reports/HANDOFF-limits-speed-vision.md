# Handoff: usage limits, speed, and a free vision model

Written 2026-10-07 in a cloud session on branch `ccr-a2aac3f9-sli3sp`, for a local session to pick up.
Companion files in the same branch:

- `reports/Free Claude quality vision models.md`: the full sourced research report on free vision models
- `research_notes/Free Claude quality vision models/*.md`: raw notes behind it (open model quality, free hardware, free hosted APIs, Apple)

Nothing in `tools/`, `server/` or `.claude/skills/` was changed. This file is analysis plus a to-do list.

---

## 1. TL;DR

1. A full run burned two usage windows mainly because of **waste**, not because visual judgment is inherently expensive. There are two big leaks:
   - `tools/assets/llm.py` spawns a **full Claude Code session per candidate check**. Each one loads CLAUDE.md, 35 skills, both MCP servers and the PowerShell hooks.
   - The `plan` skill makes Claude **rewrite the entire `plan_progress.jsonl` after every shot**, so output grows with the square of the shot count.
2. Fixing those two is cheap and comes first. It should cut both usage and wall-clock time a lot.
3. For a free vision model, the target to beat is **Haiku 4.5, not Opus**: `llm.py` already runs every vision check on `claude-haiku-4-5-20251001`. That makes a free replacement far more realistic:
   - an open Qwen model run as a batch on Kaggle's free 2xT4 (Qwen3.5-9B up to Qwen3.6-27B / 35B-A3B / Qwen3.8-27B)
   - plus a small 4B Qwen on the local 4 GB GPU as a pre-filter
4. Apple can't help on a Windows PC. Its Vision, Foundation Models and MLX all need Apple hardware, and FastVLM/MobileCLIP2 weights are research-only (no commercial use).
5. Decide by measurement. The currently running local session's Haiku picks are the starting dataset (section 4). Human labels are the ground truth. The rule: switch only if the open model's false-match rate on hard negatives is within a few points of Haiku's.

---

## 2. Where the usage and time go (code findings)

### 2.1 Every vision check is a full `claude -p` session. This is the biggest leak.

- **Where:** `tools/assets/llm.py:52-75` (`_call`, `_call_with_images`) runs:
  `claude -p "<prompt> @frame0.jpg ... @frame3.jpg" --output-format json --model claude-haiku-4-5-20251001`
- **When it runs (`tools/assets/run.py:551-571`):**
  - every Pexels/Pixabay candidate on medium- or high-specificity shots
  - every Pinterest candidate on all shots
  - 4 at a time in parallel
- **YouTube adds more calls (`tools/assets/search.py`):** `pick_best_videos` (:820), `find_moment_in_transcript` (:619), `find_best_frame_at_timestamps` (:903) and `_validate_segment` (:656).
- **What each call loads.** None of the calls pass `--bare`, `--system-prompt`, `--tools`, `--strict-mcp-config` or `--setting-sources`, so each one starts a whole interactive-equivalent session:
  - the full Claude Code system prompt and tool schemas
  - `CLAUDE.md` (17.5 KB)
  - the listing of 35 skills, including 22 unrelated `ss-*` StyleSeed UI skills
  - both MCP servers from `.mcp.json`, spawned fresh each time: `colab-proxy-mcp` (Python) and `esta-opencut` (Node)
  - both `UserPromptSubmit` hooks from `.claude/settings.json`: a PowerShell `conda env list` (slow on Windows) and `python tools/check_colab_mcp.py`
- **How big that overhead is.** One public writeup measured up to ~150k tokens loaded by `claude -p` in a big repo before any work. That figure is unverified for this repo: measure it in step P0.2.
- **Images are sent at full resolution.**
  - `search.py:1062-1067` JPEG-encodes raw frames with no downscale. At ~w*h/750 tokens, a 1080p frame is about 2.7k tokens, so 4 frames are about 11k tokens per check before any overhead.
  - `validate_image_url` (`llm.py:260`) sends the full original image.
- **A failed check approves the clip.**
  - `validate_frames` returns `{"matches": True, "confidence": 50}` on any exception or timeout (`llm.py:254-257`).
  - Timeouts are 30-45 s, and the session startup above makes them likely.
  - So slow startups silently approve unchecked footage, the opposite of the prompt's "default to MISMATCH".
- `server/planner.ts:107,182` (plan-editor Rewrite/Command) does pass `--system-prompt`, but still loads hooks and MCP.
- `server/actions.ts:59-65` (skill buttons) runs full skill sessions. That is intended, but those sessions also pay for MCP, hooks and the 22 `ss-*` skills.

### 2.2 The plan skill's output grows with the square of the shot count

- **Where:** `.claude/skills/plan/SKILL.md:94`. After each shot, Claude calls Write on `plan_progress.jsonl` with "full accumulated content so far".
- **Cost:** writing shot N re-emits shots 1..N. At ~500 tokens per shot, 60 shots come to about 915k output tokens, against about 30k for writing each shot once (estimate).
- **Why it matters:** output tokens are the slowest part of a run. At typical generation speeds this is easily an hour or more of pure typing.
- `plan.json` is then written out in full again at the end (`SKILL.md:251`).
- Plenty of what Claude writes per shot follows fixed rules and belongs in code, for example source routing (`SKILL.md:165-172`: the meme -> giphy override, aesthetic -> pinterest, the per-type source lists).

### 2.3 Other costs, smaller but real

- **motion-graphics:** the skill itself records ~482k tokens for 6 slots before the kit redesign. It still runs on whatever main model is selected.
- **style-analysis phase 2:** 8 frames per reference video are read in the main conversation (`.claude/skills/style-analysis/SKILL.md:62`). That is modest, about 1-3k tokens per frame depending on resolution.
- **Main-thread context:** every turn re-sends the whole conversation (cached reads still count). The long pipeline in one conversation keeps growing that. Running skills in forked or subagent contexts, pinned to Sonnet, would help.

### 2.4 Speed, besides the two leaks

- **faster-whisper:** `BatchedInferencePipeline` with `batch_size=8` roughly halves CPU time (upstream benchmark: small model 1m42s -> 51s). Check whether `tools/timestamps/run.py` uses the GPU (`config.yaml` has `gpu_available: false`).
- **Validation calls** should be direct HTTP calls to a resident model server that run concurrently, not process spawns.
- **Style analysis** could go to a video-native open model (Qwen takes mp4 directly at 1-2 fps) in the same Kaggle batch.

---

## 3. Free vision model research (summary)

Full detail and sources are in `reports/Free Claude quality vision models.md`. Treat every number below as provisional: the research tools could not open most official pages, so many figures come from search snippets.

**The target is Haiku 4.5.** The current validator model is Haiku (`llm.py:18`), so the comparison that matters is open model vs Haiku on ESTA's own clips. The benchmark gaps to Opus quoted below are an upper bound on the difficulty.

| Option | Fits where | Quality vs Claude (reported) | Role |
|---|---|---|---|
| Qwen3-VL-4B / Qwen3.5-4B, Q4_K_M (~2.8 GB VRAM) | Local 4 GB GPU via `llama-server` (Windows CUDA build, OpenAI-compatible, multi-image) | Clearly below. Small VLMs are "less predictable and consistent" and tend to agree with the prompt | Pre-filter only: reject obvious junk, never approve |
| MiniCPM-V 4.6 (1.3B) | Local, in Ollama since Jun 2026 | Claims Qwen3.5-2B level | Alternative pre-filter |
| Qwen3.5-9B | Kaggle 2xT4 (fp16 fits) | OCRBench 89.2 (beats Opus 4.5's 86.5); MMMU-Pro 70.1 | Likely Haiku-class judge. Test first, it's cheap |
| Qwen3.6-35B-A3B (MoE) | Kaggle 2xT4, AWQ | Near Opus 4.5 on paper, fast | Main judge candidate (speed) |
| Qwen3.6-27B / Qwen3.8-27B (dense) | Kaggle 2xT4, AWQ 4-bit (tight) | MMMU 82.9 / MMMU-Pro 75.8 / Video-MME 87.7 (3.6-27B) | Main judge candidate (quality) |
| Gemma 4 31B / 26B-A4B | Kaggle, AWQ | MMMU-Pro 76.9 (31B); OCR loops at low token settings reported | Backup judge |
| Gemini Flash-Lite free tier (~500 RPD, unverified) | Hosted, $0 | Good | Optional overflow only. Free tier may train on prompts, and Google cut Flash ~250 -> 20 RPD without notice in Dec 2025 |
| Apple Vision / Foundation Models / MLX | Mac or iPhone only | On-device model is around small open VLMs; server model trails Llama-4-Scout/GPT-4o | Not usable on this PC |
| FastVLM / MobileCLIP2 | Run on Windows | Weaker; research-only license | Not usable for monetised videos |

**Where open models are equal or better:**

- **Reading on-screen text** (scoreboards, headlines).
- **Native short-clip input:** Qwen takes an mp4 at 1-2 fps, while Claude only sees stills.
- **Naming public figures:** Qwen is trained to recognise celebrities. Claude generally avoids identifying people by face; that was not sourced, so test it.

**Where they are weaker:**

- **Defaulting to "mismatch"** when unsure.
- **Weighing many weak clues** together.
- **Run-to-run consistency.**
- **Open-ended preference:** the best open model was ~50 Elo behind the top on LMArena Vision in Mar 2026.

**Biggest technical risk: Kaggle T4.**

- The T4 is sm_75: fp16 only, no FlashAttention 2.
- vLLM issue #26297 shows a quantized Qwen3-VL checkpoint refused with "Min capability: 80. Current capability: 75".
- Use AWQ/GPTQ checkpoints (not FP8/compressed-tensors) with `--dtype float16 --enforce-eager --tensor-parallel-size 2`. The `kaggle-vllm` PyPI package ships those defaults.
- Fallback: llama.cpp CUDA GGUF split across both T4s.

**Estimated Kaggle cost:** about 0.5-1.5 GPU-hours per video for ~500 checks plus style calls. That includes 5-15 min of model load and queueing per kernel. It is unmeasured, and the weekly ~30 h is shared with IndexTTS2 and ai-video.

---

## 4. Using the running local session's Haiku picks as the test set

**Do not interrupt the running session.** Do all of this from a separate git worktree (section 6). Editing `tools/assets/*.py` does not affect an assets process that is already running: Python has loaded the modules. Still, don't touch the main working tree while it runs.

### 4.1 What already exists on disk for that session

| File | What it gives you |
|---|---|
| `sessions/<id>/plan.json` | Per shot: `visual.desc`, `visual.type`, `specificity`, per-source queries, `instance_markers` (the prompt inputs) |
| `sessions/<id>/assets_progress.jsonl` / `assets.json` | The **picked** candidate per shot: `file` (in `assets/source_pool/`), `in_point`/`out_point`, `source`, `visual_verdict`, `visual_confidence`. These are Haiku's accepted picks |
| `.esta/jobs/<job-id>.log` (if run from the UI) or the Bash output of the assets job | One line per checked candidate: `[assets] shot NN: <source> <type> validation: match/mismatch (NN%)`. This is Haiku's verdict on **losers too**, but with **no URL**, so the frames can't be recovered from the log alone |
| `sessions/<id>/timestamps.json` | Shot audio text (`audio_txt` in the prompt) |

**Gap:** losing candidates are downloaded to a temp dir that gets deleted (`search.py:1050`), and frames are never saved. So the current session gives you:

- **Positives (Haiku "match"):** fully reconstructable. Re-extract 4 frames from the `source_pool` file at the validator's positions, `(i + 0.5) / 4` of the clip (`search.py:1062-1064`), and for YouTube from the segment.
- **Negatives (Haiku "mismatch"):** only counts per shot. To get their frames, re-run the search for those shots (Pexels/Pixabay results are mostly stable for the same query) or use the capture shim below on the next run.

### 4.2 Capture shim, so every future run produces eval data for free

Add an opt-in `ESTA_VISION_CAPTURE=1` to `validate_frames` in `tools/assets/llm.py`. It should copy the frames it already writes to `tmpdir` into `sessions/<id>/vision_eval/<hash>/` and append one JSONL record to `sessions/<id>/vision_eval/records.jsonl`, with these fields:

- `id`, `shot_number`, `source`, `candidate_url`, `query`, `shot_desc`, `audio_txt`, `instance_markers`
- `frame_files`
- `model`, `raw_result`, `parsed`, `error`, `latency_s`

Notes:

- `validate_frames` doesn't know the session dir or the candidate URL today. Thread them through from `validate_stock_candidate` / `_validate_segment` (`search.py`), or read a `ESTA_SESSION_DIR` env var that `run.py` sets.
- Log the integration change in `PORTING.md`: `tools/` is a verbatim v2 copy.

### 4.3 Ground truth

Haiku's verdict is the baseline, not the truth. Build 150-300 labelled items, weighted towards:

- **Hard negatives:** right topic but wrong moment, wrong player or wrong scoreboard; celebration vs under pressure; close-up vs wide.
- Lesser-known people.
- On-screen text cases.

Labelling: a contact sheet (4 frames + desc) and a key for match/mismatch. That could be a tiny page served by the v3 backend or a plain HTML file. Store the labels in `vision_eval/labels.jsonl`.

### 4.4 Metrics

For each backend (Haiku baseline, local 4B, Kaggle 9B, Kaggle 27B/35B-A3B):

- **False-match rate on human-labelled negatives.** This is the one that matters: it means bad footage shipped.
- **False-reject rate on positives.**
- Agreement with Haiku.
- JSON validity rate.
- Latency per call (local) or total kernel wall time and GPU-hours (Kaggle).
- **Consistency:** run each item 3 times at temperature 0.01 and count the flips.

**Decision rule:**

- Adopt the open judge if its false-match rate is within ~3 points of Haiku's and its JSON validity is >= 99%.
- Adopt the 4B pre-filter only if it rejects < 2% of true positives.

---

## 5. To-do list (in order)

Repo rules apply:

- `/spec` before nontrivial work.
- Log every `tools/` and `.claude/skills/` change in `PORTING.md`.
- Never commit to `main` without being told.
- Run `/verify` before calling it done.

### P0: stop the bleeding (small, low risk)

- [ ] **P0.1 Failed checks must not approve.**
  - In `llm.py:257` return `{"matches": False, "confidence": 0, "what_i_see": "validation failed", "error": ...}`. Better: return `None`, which the callers already treat as "unvalidated" (`run.py:563`).
  - Check `_score_candidate` and the B2 gate (`run.py:579-586`) so that unvalidated candidates aren't promoted.
- [ ] **P0.2 Usage ledger.**
  - Have `_call` / `_call_with_images` parse `usage` and `total_cost_usd` from the `--output-format json` result.
  - Append to `sessions/<id>/usage.jsonl` with: step, call type, model, input/output/cache tokens, wall time.
  - Do the same for skill jobs in `server/jobs.ts`: the stream-json `result` event carries usage.
  - This turns the estimates in section 2 into numbers.
- [ ] **P0.3 Lean `claude -p` for the validator and the planner endpoints.** Candidate flags, all from the Oct 2026 CLI reference:
  - `--system-prompt "<short judge prompt>"`: replaces the default prompt.
  - `--tools ""` and `--disallowedTools "mcp__*"`.
  - `--strict-mcp-config` with no `--mcp-config`, so no MCP servers.
  - `--setting-sources ""` or `--safe-mode`, which skips CLAUDE.md, skills, plugins, hooks and auto memory but keeps subscription auth.
  - `--no-session-persistence`.
  - `--bare` is **not** an option on a subscription: it ignores OAuth and needs `ANTHROPIC_API_KEY`.
  - **Must verify:** that `@path` image attachments still get inlined with `--tools ""` and `--safe-mode` on the installed version. If not, keep `--tools Read` only.
  - Verify the token drop with P0.2.
- [ ] **P0.4 Downscale frames before sending.** Resize to <= 768 px on the long edge in `search.py` (frame extraction) and `validate_image_url`. That is about 4x fewer image tokens and also helps open models.
- [ ] **P0.5 Plan skill: no full rewrites.** Change `.claude/skills/plan/SKILL.md:94` to append one line per shot, for example Bash `>>` with a heredoc, or a tiny `tools/plan/append_shot.py`.
  - Then have `plan.json` assembled by a script from `plan_progress.jsonl` instead of Claude re-typing it.
  - Keep the per-line JSON schema unchanged: assets streams from it.
- [ ] **P0.6 Trim per-session context.**
  - Move the 22 `ss-*` StyleSeed skills out of `.claude/skills/` (they are UI-dev tools, not pipeline skills), or gate them.
  - Shorten `CLAUDE.md` towards the recommended ~200 lines by moving per-skill detail into the skills.
  - Make the `UserPromptSubmit` hooks cheap: cache the conda check result.

### P1: measure the free vision options

- [ ] **P1.1 Capture shim** (section 4.2), then run one normal assets pass to collect records with Haiku verdicts.
- [ ] **P1.2 Reconstruct positives from the current session** (section 4.1) into the same `vision_eval/` format.
- [ ] **P1.3 Label 150-300 items** (section 4.3).
- [ ] **P1.4 Replay harness** `tools/vision_eval/replay.py --backend {claude-haiku,llama,kaggle} --session sessions/<id>`.
  - Use the **same prompt text** as `validate_frames`, and the same frames.
  - Output `results_<backend>.jsonl` plus a metrics summary (section 4.4).
- [ ] **P1.5 Local backend spike.**
  - Install a llama.cpp Windows CUDA release and fetch `Qwen3-VL-4B-Instruct` Q4_K_M plus its mmproj GGUF.
  - Run `llama-server -m <gguf> --mmproj <mmproj> -ngl 99 -c 8192 --port 8080`, then point the replay harness at `http://localhost:8080/v1/chat/completions`.
  - Set temperature 0.01 and repeat penalty ~1.2, and use JSON-schema-constrained output (`response_format` / grammar).
- [ ] **P1.6 Kaggle spike (1 hour, before building anything).**
  - Write a kernel that installs `kaggle-vllm`, loads an AWQ checkpoint of Qwen3.5-9B, then Qwen3.6-35B-A3B, then a 27B, on 2xT4 (`dtype=float16, enforce_eager=True, tensor_parallel_size=2`), and runs `LLM.generate` offline over a dataset of the eval frames and prompts.
  - Record: does it load at all (sm_75), wall time per 100 items, GPU-hours.
  - If vLLM refuses, retry with llama.cpp CUDA GGUF split across the GPUs.
  - Reuse the push/status/output pattern from `tools/kaggle_lane.py` / `tools/genvideo/run.py`.
- [ ] **P1.7 Optional:** Gemini Flash-Lite free tier as a third comparison point, only if you accept its data terms for public stock frames.

### P2: switch backends (only if P1 passes)

- [ ] **P2.1** Add `vision_backend: claude | llama | kaggle` (plus `vision_url`) to `config.yaml`, with one OpenAI-compatible client in `llm.py` and a fallback chain.
- [ ] **P2.2 CLIP/SigLIP pre-rank.** CLIP is already in the `esta` env for style-analysis. Score every candidate's frames against `visual.desc` for free, and send only the top 2-3 per shot to the judge.
- [ ] **P2.3 Batch mode for Kaggle.** Restructure assets so candidate gathering finishes, then one kernel judges every shot's candidates, then verdicts are written to `assets_progress.jsonl`.
  - The early render keeps placeholders meanwhile.
  - The local 4B pre-filter runs during gathering.
  - Keep `claude -p` Haiku as an optional capped fallback for low-confidence items only.
- [ ] **P2.4 YouTube moment-finding** (`find_moment_in_transcript`, `pick_best_videos`) is text-only. Move it to the same local/Kaggle model, or batch it.

### P3: the rest of the speed pass

- [ ] **P3.1** `tools/timestamps/run.py`: use `BatchedInferencePipeline(batch_size=8)` and the GPU if available (`small` int8_float16 fits 4 GB).
- [ ] **P3.2 style-analysis on Kaggle:** feed the reference clips as mp4 at 1-2 fps to the same Qwen kernel to get the per-sequence descriptions. Claude then only synthesises `style_analysis.json` from text.
- [ ] **P3.3 Pin heavy generative skills to Sonnet** (skill `model:` frontmatter, or run them as forked/subagent skills) and keep the main thread small.
- [ ] **P3.4 Plan skill: compact spec.** Claude emits only the judgment fields per shot (desc, type, queries, overlay/sfx intent). A Python expander applies the fixed source-routing rules and fills the schema.

---

## 6. How the local session should pick this up

Because another session is running in the main working tree, use a **separate worktree**. The running session's files stay untouched, while `sessions/` (gitignored) is still reachable by absolute path:

```powershell
cd C:\Users\User\ESTA-v3
git fetch origin ccr-a2aac3f9-sli3sp
git worktree add ..\ESTA-v3-perf origin/ccr-a2aac3f9-sli3sp -b perf-vision
cd ..\ESTA-v3-perf
claude
```

Then give the new session this prompt (replace `<id>`):

> Read `reports/HANDOFF-limits-speed-vision.md` and `reports/Free Claude quality vision models.md`. Another Claude session is running in `C:\Users\User\ESTA-v3`: do not touch that working tree or its running jobs. The test data is that session's folder, `C:\Users\User\ESTA-v3\sessions\<id>\`, plus its job logs in `C:\Users\User\ESTA-v3\.esta\jobs\`. Its Haiku asset selections are the baseline, read-only. Start with P0.1, P0.2 and P0.3, then P1.1-P1.5 (capture shim, rebuild positives from that session, label set, replay harness, local llama-server spike). Write a short SPEC.md entry first, log every `tools/` change in PORTING.md, and stop after the local spike results so I can decide on the Kaggle spike.

---

## 7. Open questions and unverified items

- The real per-call overhead of the current `claude -p` validator on this repo. P0.2 answers it.
- Whether `--safe-mode` / `--tools ""` keep `@image` attachments working in `-p` on the installed Claude Code version.
- Whether Qwen3.5/3.6/3.8 vision runs under vLLM on Kaggle T4 (sm_75). Untested; P1.6 answers it.
- Kaggle's weekly GPU quota (~30 h, not officially published) and whether sessions last 9 h or 12 h.
- All free hosted API quotas, which come from aggregator snippets.
- Whether Claude refuses face-based identification in this prompt. The eval set should include named-athlete cases to see what Haiku actually does.
- All seconds-per-image and GPU-hour figures, which are estimates from token arithmetic.
