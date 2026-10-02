---
name: match
description: Inspo match (v3, M5). Measures the whole inspo videos shot by shot, scores the plan (mode plan) or the rendered edit (mode final) against them in five sections (asset mix, colour, theme, complexity, shot duration), and nudges only the failing sections until the score passes. Runs after plan and again after the final render. System python; inspo shots are described by Haiku, auto-pick judging runs on Kaggle (until M6.3).
---

# Match Skill

Makes the video follow its inspo measurably. Local models do the looking and the arithmetic; this step only runs the tools and reports.

## Preflight

1. `sessions/<id>/plan.json` and `style_analysis.json` exist (mode final also needs `<id>.openreel.json`). If not, say which step is missing and stop.
2. The system python runs these tools (`python`, not `conda run -n esta`): `esta` pins transformers 4.33, which predates DINOv3 and SigLIP 2. The `claude` CLI must be on PATH (the describe lane); the Kaggle CLI must be authenticated (`~/.kaggle/kaggle.json`) for auto-pick judging.

## Invocation

```bash
python tools/match/run.py --session sessions/<id> --stage profile # after style-analysis, before plan
python tools/match/run.py --session sessions/<id> --stage plan    # after plan
python tools/match/run.py --session sessions/<id> --stage final   # after the final render
```

It runs in the background (describing an inspo takes ~3-5 minutes and ~$0.40-0.60 of Haiku the first time it is seen; it is cached after). What it does:

`--stage profile` stops after step 1: it exists so the plan skill's mapped mode (`tools/match/slots.py`) has the inspo shots to cut against. The plan and final stages reuse the cached profile.

1. `inspo.py profile`: resolves `inspo.json` (from style-analysis output for older sessions), downloads each inspo (whole video up to 10 minutes), cuts it with TransNetV2, measures colour, embeds keyframes (DINOv3, SigLIP 2), transcribes it, and has Haiku describe each shot from its keyframe and the words spoken over it (description, kind, content, sourcing hint, subtitle-blind text and overlay flags; `tools/match/describe.py`). Cached in `cache/inspo/<hash>/`.
2. `score.py`: writes `match_plan.json` / `match_final.json` with sections a-e, the overall score and pass/fail (overall >= 80 and every section >= 70; weights in `config.yaml` `match`).
3. `adjust.py`: while failing, fixes sections in order e (split/merge), a (retype toward the inspo's mix), d (overlays), c (reword off-theme shots), b (colour grades at final, written to `match_grades.json` and applied by Build). Wording is one batched Haiku call per round. A round that gains under 1 point or drops a passing section is reverted and the loop stops; otherwise it runs until pass or 8 rounds. Locked (hand-edited) shots are never touched.

At the final stage, changed shots are re-picked by `tools/match/autopick.py` and the project is re-rendered before re-scoring.

## After it finishes

Show the overall score and each section's number against the inspo in one line each (the score card in the Plan stage shows the same), what each kept round changed, and anything pending (describe failed or `claude` missing: tag-dependent sections show pending). Then announce the next step (`conductor.py next`).

Re-score without adjusting: `python tools/match/score.py --session sessions/<id> --stage plan|final --force`.
