# M5.1 bake-off results

**Note on theme's empty table**: this is kernel v3's real output, not a bug still
in the results. Two of theme's three bugs (a dataset-mount path issue, and
SigLIP2/CLIP returning unpooled per-patch features instead of one embedding
per image) are already fixed in `kaggle.py` — a `push` + `apply` would very
likely fill this in for SigLIP2 and CLIP (DINOv3 stays gated regardless, see
below). Not re-run automatically: Qwen3-VL-8B alone cost 63 GPU-minutes and
Qwen3-VL-4B 50 in this run, so a full re-run costs roughly another 1.5-2 hours
of the shared 30 GPU-h/week Kaggle quota — a resource decision, not just a
code fix, left for you to trigger when you're ready:
```
python tools/match/bakeoff/kaggle.py push
python tools/match/bakeoff/kaggle.py status   # poll until complete
python tools/match/bakeoff/kaggle.py apply    # rewrites this file
```

**Gemma3-4b and DINOv3-small need your HuggingFace account to accept their
license** before they'll ever produce a score (403 gated-repo errors below,
not bugs) — visit these while logged in as the account tied to `config.yaml`'s
`hf_token`, then re-run push/apply:
- https://huggingface.co/google/gemma-3-4b-it
- https://huggingface.co/facebook/dinov3-convnext-small-pretrain-lvd1689m

**Florence-2-large** hit three separate transformers-version incompatibilities
across three runs (each fixed in turn — see `kaggle.py`'s comments); a fourth
may surface on the next run. Given `text_on_screen` already has a real winner
(qwen3-vl-4b) without it, I'd recommend just dropping Florence-2 rather than
chasing a fourth compatibility break.


{
  "kernel": "isijolajesupelumi/esta-bakeoff-main-kernel",
  "errors": {
    "cuts:autoshot": "no reachable AutoShot checkpoint (upstream is Baidu-only)",
    "tags:gemma3-4b": "You are trying to access a gated repo.\nMake sure to have access to it at https://huggingface.co/google/gemma-3-4b-it.\n403 Client Error. (Request ID: Root=1-6ab9bcc8-20db449a67874df968879c17;434e18bb-254d-475f-b094-7855cd2217e3)\n\nCannot access gated repo for url https://huggingface.co/google/gemma-3-",
    "tags:florence2-large": "'Florence2ForConditionalGeneration' object has no attribute '_supports_sdpa'",
    "theme:siglip2": "matmul: Input operand 1 has a mismatch in its core dimension 0, with gufunc signature (n?,k),(k,m?)->(n?,m?) (size 196 is different from 768)",
    "theme:clip-vit-b32": "matmul: Input operand 1 has a mismatch in its core dimension 0, with gufunc signature (n?,k),(k,m?)->(n?,m?) (size 50 is different from 768)",
    "theme:dinov3-small": "You are trying to access a gated repo.\nMake sure to have access to it at https://huggingface.co/facebook/dinov3-convnext-small-pretrain-lvd1689m.\n403 Client Error. (Request ID: Root=1-6ab9bcf2-248ea1fd1e059cff773e06c9;c44c3bbb-14a2-439b-bdcc-d61304bed318)\n\nCannot access gated repo for url https://hu"
  }
}

### Cuts (bar: F1 >= 0.9)

| candidate | F1 | sec/min video | GPU-min | status |
|---|---|---|---|---|
| transnetv2 | 0.928 | 10.7 | 0.44 | PASS **<- winner** |
| pyscenedetect | 0.792 | 3.4 | 0.00 | fail |

**Winner: transnetv2** — highest f1 (0.928) among candidates clearing 0.9
### Tags: kind (bar: macro_f1 >= 0.85)

| candidate | macro_f1 | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 0.456, n= | 1544.5 | 63.26 | fail |
| qwen3-vl-4b | 0.420, n= | 1231.8 | 50.45 | fail |

**Winner: none** — no candidate cleared the bar

Dropped (no candidate cleared the bar): qwen3-vl-8b, qwen3-vl-4b
### Tags: text_on_screen (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-4b | 0.935, n=77 | 1231.8 | 50.45 | PASS **<- winner** |
| qwen3-vl-8b | 0.922, n=77 | 1544.5 | 63.26 | PASS |

**Winner: qwen3-vl-4b** — highest accuracy (0.935) among candidates clearing 0.85
### Tags: panels (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 1.000, n=77 | 1544.5 | 63.26 | PASS **<- winner** |
| qwen3-vl-4b | 1.000, n=77 | 1231.8 | 50.45 | PASS |

**Winner: qwen3-vl-8b** — highest accuracy (1.000) among candidates clearing 0.85
### Tags: overlay (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-4b | 0.909, n=77 | 1231.8 | 50.45 | PASS **<- winner** |
| qwen3-vl-8b | 0.883, n=77 | 1544.5 | 63.26 | PASS |

**Winner: qwen3-vl-4b** — highest accuracy (0.909) among candidates clearing 0.85
### Tags: clips_in_shot (bar: accuracy >= 0.85)

| candidate | accuracy | sec/min video | GPU-min | status |
|---|---|---|---|---|
| qwen3-vl-8b | 1.000, n=77 | 1544.5 | 63.26 | PASS **<- winner** |
| qwen3-vl-4b | 1.000, n=77 | 1231.8 | 50.45 | PASS |

**Winner: qwen3-vl-8b** — highest accuracy (1.000) among candidates clearing 0.85
### Theme embeddings (bar: AUC >= 0.8)

| candidate | AUC | sec/min video | GPU-min | status |
|---|---|---|---|---|

**Winner: none** — no candidate cleared the bar

**Local timing (cuts, transnetv2):** 8.60 s/min of video, on cuda.
