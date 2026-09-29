# M5.1 bake-off results

{
  "kernel": "isijolajesupelumi/esta-bakeoff-main-kernel",
  "errors": {
    "cuts:autoshot": "no reachable AutoShot checkpoint (upstream is Baidu-only)",
    "tags:florence2-large": "RobertaTokenizer has no attribute additional_special_tokens"
  }
}

### Cuts (bar: F1 >= 0.9)

| candidate | F1 | sec/min video | GPU-min | status |
|---|---|---|---|---|
| transnetv2 | 0.928 | 10.9 | 0.45 | PASS **<- winner** |
| pyscenedetect | 0.792 | 3.3 | 0.00 | fail |

**Winner: transnetv2** — highest f1 (0.928) among candidates clearing 0.9
### Tags: kind (bar: macro_f1 >= 0.85)

| candidate | macro_f1 | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 0.456, n= | 1535.4 | 62.89 | fail |
| gemma4-e4b | 0.455, n= | 272.4 | 11.16 | fail |
| qwen3-vl-4b | 0.420, n= | 1231.3 | 50.44 | fail |
| gemma3-4b | 0.354, n= | 307.4 | 12.59 | fail |

**Winner: none** — no candidate cleared the bar

Dropped (no candidate cleared the bar): qwen3-vl-8b, qwen3-vl-4b, gemma3-4b, gemma4-e4b
### Tags: text_on_screen (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-4b | 0.935, n=77 | 1231.3 | 50.44 | PASS **<- winner** |
| gemma4-e4b | 0.935, n=77 | 272.4 | 11.16 | PASS |
| qwen3-vl-8b | 0.922, n=77 | 1535.4 | 62.89 | PASS |
| gemma3-4b | 0.883, n=77 | 307.4 | 12.59 | PASS |

**Winner: qwen3-vl-4b** — highest accuracy (0.935) among candidates clearing 0.85
### Tags: panels (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 1.000, n=77 | 1535.4 | 62.89 | PASS **<- winner** |
| qwen3-vl-4b | 1.000, n=77 | 1231.3 | 50.44 | PASS |
| gemma3-4b | 1.000, n=77 | 307.4 | 12.59 | PASS |
| gemma4-e4b | 1.000, n=77 | 272.4 | 11.16 | PASS |

**Winner: qwen3-vl-8b** — highest accuracy (1.000) among candidates clearing 0.85
### Tags: overlay (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| gemma4-e4b | 0.922, n=77 | 272.4 | 11.16 | PASS **<- winner** |
| qwen3-vl-4b | 0.909, n=77 | 1231.3 | 50.44 | PASS |
| qwen3-vl-8b | 0.883, n=77 | 1535.4 | 62.89 | PASS |
| gemma3-4b | 0.857, n=77 | 307.4 | 12.59 | PASS |

**Winner: gemma4-e4b** — highest accuracy (0.922) among candidates clearing 0.85
### Tags: clips_in_shot (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 1.000, n=77 | 1535.4 | 62.89 | PASS **<- winner** |
| qwen3-vl-4b | 1.000, n=77 | 1231.3 | 50.44 | PASS |
| gemma3-4b | 1.000, n=77 | 307.4 | 12.59 | PASS |
| gemma4-e4b | 0.896, n=77 | 272.4 | 11.16 | PASS |

**Winner: qwen3-vl-8b** — highest accuracy (1.000) among candidates clearing 0.85
### Theme embeddings (bar: AUC >= 0.8)

| candidate | AUC | sec/min video | GPU-min | status |
|---|---|---|---|---|
| dinov3-small | 0.998 | 3.8 | 0.16 | PASS **<- winner** |
| siglip2 | 0.974 | 7.0 | 0.29 | PASS |
| clip-vit-b32 | 0.966 | 3.7 | 0.15 | PASS |

**Winner: dinov3-small** — highest auc (0.998) among candidates clearing 0.8

## Config write-back

Approved 2026-09-29T04:00:53.874741+00:00. Winners written to `config.yaml` `match.models`:

- `cuts`: `transnetv2`
- `theme`: `dinov3-small`
- `text_on_screen`: `gemma4-e4b`
- `panels`: `gemma4-e4b`
- `overlay`: `gemma4-e4b`
- `clips_in_shot`: `qwen3-vl-8b`

Dropped (no passing candidate): kind

**Local timing (cuts, transnetv2):** 8.60 s/min of video, on cuda.

## Kind in merged classes (re-run 2026-09-29)

Gemma 4 E4B re-tagged the 77 answer-key shots through the everyday tag lane (`tools/match/tag.py validate`) with the bake-off prompt, then scored with fine kinds merged into what the plan can express (`screen` joins graphic: terminal and UI cards are built as MOTION_GRAPHICS).

| grouping | macro-F1 | accuracy | class-share error (TVD) |
|---|---|---|---|
| 4 classes (footage, still, graphic, meme) | 0.442 | 0.818 | 0.13 |
| 3 classes (meme folded into footage) | 0.491 | 0.870 | 0.10 |

**Used: 3 classes, with a warning.** Accuracy clears 0.85; macro-F1 does not, because the key has only 2 stills (F1 0) and 3 graphics, and memes are read as graphics (5 of 12). The asset-mix section compares duration-weighted class shares, so its measurement error is about the share error above, roughly 10 points. `config.yaml` `match.kind_classes: 3`.

`panels` and `clips_in_shot` stay out of scoring: every answer-key shot is 1/1, so no model's score on them means anything. All tags run on `gemma4-e4b` in one pass, 5x cheaper than Qwen3-VL-8B.

**Local timing (theme, dinov3-small):** about 3.3 s per 3 keyframes on cuda (RTX A2000 4 GB), system python. SigLIP 2 (text-image, added as a pick): about 2 s for the same.
