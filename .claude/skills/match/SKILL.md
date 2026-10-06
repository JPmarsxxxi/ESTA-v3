---
name: match
description: Inspo match (v3, M5). Measures the whole inspo videos shot by shot, scores the plan (mode plan) or the rendered edit (mode final) against them in five sections (asset mix, colour, theme, complexity, shot duration), and nudges only the failing sections until the score passes. Runs after plan and again after the final render. System python; inspo shots are described and auto-pick candidates judged by Haiku; no Kaggle.
---

# Match Skill

Makes the video follow its inspo measurably. Local models do the looking and the arithmetic; this step only runs the tools and reports.

## Preflight

1. `sessions/<id>/plan.json` and `style_analysis.json` exist (mode final also needs `<id>.openreel.json`). If not, say which step is missing and stop.
2. The system python runs these tools (`python`, not `conda run -n esta`): `esta` pins transformers 4.33, which predates DINOv3 and SigLIP 2. The `claude` CLI must be on PATH (the describe lane and the auto-pick judge).

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

Auto-pick treats stock (Pexels/Pixabay) as a capped last resort (SPEC.md Part 7): a non-stock candidate always wins; a shot with nothing outside stock gets up to 3 Haiku query rewrites on every non-stock source of its kind; only then may it take stock, while fewer than 15% of the plan's shots (`config.yaml` `assets.stock_cap`, `pipeline.json` `ui.stock_cap` overrides) hold a stock pick. Past that it becomes a word-card graphic in the session kit (`retype_reason: "stock_cap"`), or is listed in `stock_overflow.json` for the motion-graphics skill when there is no kit yet. Its report (`autopick.json` `last.stock`) gives the budget, the count used and the retyped shots.

Shots queued in `assets/chrome_queue.json` (Google Images blocked headless) wait for the Chrome pass: run it as described in the assets skill's "Google Images through Claude in Chrome", then re-run auto-pick for those shots before the final score.

## After it finishes

Show the overall score and each section's number against the inspo in one line each (the score card in the Plan stage shows the same), what each kept round changed, and anything pending (describe failed or `claude` missing: tag-dependent sections show pending). Point the user at the Match card's **Open side-by-side** (`match_review.html`): every shot next to the inspo shot it copies, with validator failures, low-theme shots, ref swaps and short clips flagged. Then announce the next step (`conductor.py next`).

Re-score without adjusting: `python tools/match/score.py --session sessions/<id> --stage plan|final --force`.
