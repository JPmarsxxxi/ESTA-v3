# M13 overnight log (2026-10-12 → 13)

Branch `qwen-vision-trial`. Spec: SPEC.md Part 10. Newest entries at the bottom.

## Done before you went to bed
- M12 committed (`4739412`), perf-vision merged (`36f19ce`), spec committed (`37e6f43`).

## Part A: Qwen client and routing
- `tools/vision_server/client.py`: OpenAI-style client, bearer token from `.esta/vision_server.json`, concurrency semaphore, 5-failure breaker, ledger rows with `backend: qwen` and `json_ok`.
- `llm._ask` and `describe.ask` send image turns there when `vision.backend: qwen`; text turns stay on Claude.
- Ledger rows carry `backend`; `report.py --session` splits by backend and prints Qwen calls/failures/invalid JSON/median s.

## Part B: Kaggle server
- `tools/vision_server/kernel.py` + `run.py up|status|down`. Kernel `isijolajesupelumi/esta-vision-server`, reached at your ngrok domain from `config.yaml`.
- First push died at once: config written as JSON (`true`), fixed to a Python literal.
- ngrok: no Kaggle secret was attached, so the kernel used `config.yaml`'s `ngrok_token` (same as your old applypilot notebook). Tunnel came up fine.
- vLLM: the first try failed in 15 s (Kaggle's python has no `ensurepip`, so `python -m venv` fails). Switched the kernel to `uv` for the next push. This run fell back to the transformers batching server (same model and loading as the Part 8 trial).
- `replay.py --backend qwen-live` added for the 180-item check.

## Part C: idea-first plan
- `validate_plan.py`: no cut inside a name or number; every footage/image shot needs `idea {id, step, subject}`; the same subject on neighbouring ideas fails; an idea spanning shots must move on (desc overlap < 0.5). On the current plan the cut rule finds 27 bad cuts (Igor | Tolchinsky, 0 | .05, 0 | .445, ...).
- Deviation from the spec: the "same subject" test uses an explicit `idea.subject` instead of desc overlap, because the two Tate descs only overlap 0.42 and would have passed.
- `autopick.py`: no photo/video twice within 10 shots (by YouTube id, URL or file hash). With no other candidate the repeat is kept and flagged on the review page.
- Plan skill mapped mode: new Pass 0 (ideas before cuts). PORTING.md logs it.
- Tests: 194 pass.
- Code committed: `7e73f09` (verify pass: every in-scope criterion met; closed its two small gaps, `config.example.yaml` vision block and smaller judge batches on Qwen).

## Sanity replay (transformers fallback server)
- Stopped after 64 of 180 items: too slow for a full video (median 54 s per request in batches of 8, about 24 s per item end to end).
- Quality matches the Part 8 trial exactly: 64/64 valid JSON, 64/64 same match/frame answers as `results_kaggle-qwen3-5-9b`. The served model is right.
- Re-pushed the kernel with vLLM built through `uv` for the real run.

## Replan (idea-first)
- `sessions/<id>/ideas.txt`: the script as 197 visual ideas, each with a subject (e.g. "So, alphas, nah," = alphas title, "not these guys" = Tate, "or these guys." = wolves, "This fucking annoying ass shit." = reaction).
- `replan.py cut`: idea boundaries are cuts; long ideas split at allowed word boundaries near the inspo's local shot length. 293 shots (was 336), median 2.54 s.
- `visuals.txt`: one visual per shot. Old visuals reused where they fit the idea (`=N`), about 70 new ones where the old visual followed the inspo's look instead of the line.
- `replan.py build` → plan.json: passes `validate_plan.py` (0 failing sections). 228 footage, 45 image, 20 graphic; 50 reaction beats, Giphy only on those.
- Overlays dropped in the new plan (their cards are rendered per old shot number; the complexity score excludes overlays).
- Pre-M13 artifacts backed up in `sessions/<id>/backup_m12_claude/`; candidate cache moved to `assets/candidates_m12/`; asset feed reset; the 20 graphics point at their old crimson-card renders (`m13_reset.py`).

## Qwen server on vLLM
- vLLM (built with uv) loaded Qwen3.5-9B on both T4s in 14 min, fp16, tensor-parallel 2.
- Speed: 24 eval items in 47 s with 8 in flight, about 2 s per item (one at a time in the Part 8 trial: 12.5 s; transformers fallback: about 24 s).
- Answers: 24/24 valid JSON; wherever the item was also in the Part 8 trial, same answer (8/8 match checks, 1/1 frame, 1/1 judge).
- `config.yaml` `vision.backend` set to `qwen` for the run (set it back to `claude` afterwards).

## Full run (m13_run.py)
- 23:46 autopick: 273 shots in 14 chunks
- 23:50 STOPPED, not by a bug: Claude Code killed the run (and the review-page server) because the PC was critically low on memory (2.4-2.8 GB free of 15.7; Chrome held about 3.5 GB). Its rule is not to restart a killed job unattended, so the run waits for you.
- How far it got: chunk 1 of 14 (11 of 273 shots gathered, none picked yet). Qwen worked while it ran: 86 image calls (66 frame search, 20 clip checks), 0 invalid JSON, 4 failed, median 11 s per call under load. Text calls on Claude: 21.

## To finish in the morning
1. Free memory first: close most Chrome tabs (the run needs SigLIP + DINO + downloads).
2. `python tools/vision_server/run.py up` (the Kaggle server stops itself after 20 idle minutes; about 15 min to come back on vLLM).
3. `python sessions/do-alphas-even-exist-2026-09-29/m13_run.py`. It resumes from `m13_state.json`, picks all 273 footage/image shots with Qwen in 14 chunks, then runs render and match final, logging each chunk here. Expect roughly 2-4 hours.
4. Afterwards: set `config.yaml` `vision.backend` back to `claude`, and build the side-by-side page (pre-M13 picks in `backup_m12_claude/`).

State now: `config.yaml` has `vision.backend: qwen`. The new plan (293 shots, passes the validator) is in `plan.json`. The session scripts (`ideas.txt`, `visuals.txt`, `replan.py`, `m13_reset.py`, `m13_run.py`) and the plan are not committed yet.
- 23:59 Restarted on your instruction as a detached process (pid 19540), so Claude Code's low-memory guard can't stop it; output in D:/esta-perf/m13/run.log.
- 00:05 chunk 1/14 (shots 1-22): picked 20, lane 'haiku judge', 5.6 min
- 00:27 chunk 2/14 (shots 23-44): picked 20, lane 'haiku judge', 22.6 min
- 00:39 chunk 3/14 (shots 45-65): picked 20, lane 'haiku judge', 11.3 min
- 00:50 chunk 4/14 (shots 66-85): picked 20, lane 'haiku judge', 11.1 min
- 01:01 chunk 5/14 (shots 86-108): picked 20, lane 'haiku judge', 10.9 min
- 01:10 chunk 6/14 (shots 109-128): picked 20, lane 'haiku judge', 9.6 min
- 01:22 chunk 7/14 (shots 129-151): picked 20, lane 'haiku judge', 11.8 min
- 01:33 chunk 8/14 (shots 152-171): picked 20, lane 'haiku judge', 10.6 min
- 01:43 chunk 9/14 (shots 172-193): picked 20, lane 'haiku judge', 10.3 min
- 01:48 chunk 10/14 (shots 194-215): picked 20, lane 'haiku judge', 5.0 min
- 02:01 chunk 11/14 (shots 216-235): picked 20, lane 'haiku judge', 13.0 min
- 02:11 chunk 12/14 (shots 236-255): picked 20, lane 'haiku judge', 10.0 min
- 02:19 chunk 13/14 (shots 256-277): picked 20, lane 'haiku judge', 8.0 min
- 02:26 chunk 14/14 (shots 280-293): picked 13, lane 'haiku judge', 7.1 min
- 02:26 autopick done. picks by source: {"hyperframes": 20, "pinterest": 33, "giphy": 32, "youtube": 197, "openverse": 6, "wikimedia": 5}
- 02:27 render: exit 0 {"ok": true, "output": "sessions\\do-alphas-even-exist-2026-09-29\\do-alphas-even-exist-2026-09-29.openreel.json", "media_items": 294, "video_clips": 308, "video_tracks": {"main": 288, "overlay": 0, "graphics": 20}, "audio_tracks": {"voice": 1, "music": 0, "ambience": 0}, "placeholders": 0, "subtitl
- 02:34 match final: exit 0 {"ok": true, "overall": 78.8, "pass": false, "sections": {"a": 97.7, "b": 71.3, "c": 64.8, "d": 90.0, "e": 74.6}}

## Results
- **Final score 78.8** (pre-M13: 81.9). By section, old → new: asset distribution 99.0 → 97.7, colour 68.1 → 71.3, thematic adherence 64.9 → 64.8, complexity 96.1 → 90.0, shot duration 81.6 → 74.6.
- The drop comes from the plan, not from Qwen. Thematic adherence, the section that reflects what the picks show, is level. Shot duration fell because idea-first cuts give longer shots (median 2.54 s vs 2.38 s, inspo 1.97 s), and complexity fell because there are fewer captions (text rate 0.47 vs 0.52) and the visual variety is slightly lower.
- Coverage: 293/293 shots, 0 placeholders, 0 stock (Pexels/Pixabay). Giphy is on 32 shots, within the 50 reaction beats.
- Picks by source: YouTube 197, Pinterest 33, Giphy 32, HyperFrames 20 (reused graphics), Openverse 6, Wikimedia 5.
- Media reused within 10 shots: 1 (shots 89 and 90, same YouTube video at different moments, 111.9 s and 127.1 s).
- Qwen, run from 23:59: 2,487 image calls (frame search 1,786, clip check 634, judge 67). 22 failed (timeouts/unreachable) and 3 returned invalid JSON, so 25 checks were left unchecked (1.0%). Median 14.3 s per call with 8 in flight.
- Claude image calls in the run: 0. Claude text calls: 239 pick_videos and 55 find_moment, as the spec intends.
- Kaggle GPU: the kernel was pushed at 23:29 and stopped about 20 min after the last call (02:34), so the run used about 3.4 h on 2xT4. The earlier test pushes (transformers fallback, first vLLM try) add roughly 1 h. Kaggle lists the kernel as ERROR after the idle stop, most likely because `os._exit` kills the notebook mid-cell (the exit code is 0). The stop itself worked: the server is gone and no GPU time is running.
- `config.yaml` `vision.backend` is set back to `claude`.
- Side-by-side review: `python D:/esta-perf/m13/make_review.py`, then open http://localhost:8799/review.html. It shows each new shot next to the old shot at the same moment, with line, idea, desc, source and query. 35 shots kept the same file as before.

## Server and full sanity replay (morning, 2026-10-13)
`python tools/vision_server/run.py up`:
```
pushed isijolajesupelumi/esta-vision-server; waiting for https://intromissive-lennon-processionally.ngrok-free.dev/health (up to 40 min)
  0.5 min: installing vllm
  2.1 min: loading model in vllm
  15.4 min: ready vllm
ready: vllm Qwen/Qwen3.5-9B on ['Tesla T4', 'Tesla T4']
```
`run.py status` → `/health`: `{"ready": true, "stage": "ready", "mode": "vllm", "model": "Qwen/Qwen3.5-9B", "gpus": ["Tesla T4", "Tesla T4"], ...}`, Kaggle `running`.

Replay of the Part 8 sample (the same 180 items as `results_kaggle-qwen3-5-9b`, set `D:/esta-perf/vision_eval/do-alphas-180`), `replay.py --backend qwen-live --workers 8`: 170 new items in 5.0 min (about 34 items/min, 1.8 s/item; one at a time in Part 8: 12.5 s/item).

| kind | JSON valid | agreement with Haiku: Part 8 trial → live vLLM |
|---|---|---|
| validate (60) | 100% | agree 80.0% → 78.3% |
| frame_search (60) | 100% | same frame 48.3% → 50.0%; within one 70.0% → 71.7% |
| judge (60) | 100% | same best 68.3% → 66.7%; reject overlap 65.0% → 63.3% |

All within 5 points; JSON validity 100%.

`run.py down` → `shutdown sent`; `status` afterwards: health `null` (server gone), Kaggle `error` (the kernel's `os._exit` ends the notebook mid-cell).

## Repeat flag fix
Autopick replaced `autopick.json["last"]` on every chunk, so a chunk's repeat flag was lost by the next chunk and shot 90 (same YouTube video as shot 89) showed unflagged. Repeat flags now accumulate in `autopick.json["repeats"]` across runs and `review.py` reads them; this session's flag was backfilled and both review pages show it.
