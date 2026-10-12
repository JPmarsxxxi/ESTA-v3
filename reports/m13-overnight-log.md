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
