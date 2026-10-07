# Running open VLMs for $0 on limited hardware (4 GB Windows GPU + Kaggle), as of October 2026

Research caveat: huggingface.co, ollama.com, discuss.vllm.ai, research.google.com (Colab FAQ), lemmy and gpuperhour.com were blocked by this environment's egress proxy, so several primary sources could only be read through search snippets. Those are marked "(snippet)". Speed numbers for exactly a 4 GB card are scarce; most figures are estimates or come from other hardware.

## 1. What fits in 4 GB VRAM, at what quantization and speed

### Takeaway
2B-4B VLMs at Q4_K_M (Qwen3-VL-2B/4B, Gemma 3 4B, Moondream, SmolVLM, MiniCPM-V class) fit fully in 4 GB with the mmproj vision encoder. 7-8B VLMs need partial offload. The MoE Qwen3-VL-30B-A3B can run with all experts on CPU (`--n-cpu-moe 999`) using ~2.5-3.2 GB VRAM. One user reports ~15 tok/s generation on a 4 GB / 16 GB RAM machine, but that may be a text-only model, and image prefill is the real bottleneck.

### Cited Findings
- Qwen3-VL-4B at Q4_K_M uses ~2.8 GB VRAM. llama.cpp runs it through `llama-mtmd-cli` / llama-server with a separate mmproj vision file. A quoted ~60 tok/s is for a stronger GPU, not a 4 GB card — [codersera](https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/) (snippet); [canirun.ai](https://canirun.ai/model/qwen3-vl-4b/)
- Generation speed is memory-bandwidth bound: models that fit fully in VRAM are far faster than ones that offload to system RAM — [codersera](https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/) (snippet)
- MoE CPU offload: with `-ngl -1 -ncmoe 999` (all expert layers on CPU) on a 4 GB VRAM / 16 GB RAM setup, one user reported ~15 tok/s with only ~2.5-3.2 GB VRAM used. The snippet concerns Qwen3.5-35B-A3B / Qwen3-30B-A3B class models, and whether the VL variant was tested is unclear. A modified llama.cpp running Qwen3.5-35B-A3B Q4_K_M (~21 GB GGUF) on a laptop RTX 2050 (4 GB) got only ~1.2 tok/s — [bestllmfor.com](https://bestllmfor.com/catalog/qwen3-vl-30b/), [lemmy comment](https://lemmy.4d2.org/comment/6479265) (snippets, conflicting figures)
- Raising `--n-cpu-moe` from 8 to 30 doubled Qwen3-35B-A3B decode from 17 to 34 tok/s on a 12 GB card, because keeping all experts on the GPU caused bandwidth thrashing — [aiweekly](https://aiweekly.co/alerts/qwen3-moe-cpu-expert-offload-doubles-decode-speed-on-12gb-vram)
- A Q4_K_M 30B-A3B GGUF is roughly 17-21 GB, so it needs at least 24 GB of system RAM to be comfortable. 16 GB RAM is marginal (inferred from the ~21 GB GGUF size above).
- llama.cpp offloads the multimodal projector (mmproj) to the GPU by default. `--no-mmproj-offload` keeps it on the CPU to save VRAM — [llama.cpp multimodal docs mirror](https://www.mintlify.com/ggml-org/llama.cpp/inference/multimodal)
- Reference speed for image handling: Gemma-3-4B-it GGUF on an M1 MBP measured 25 tok/s prompt processing and 63 tok/s generation, and roughly 15 s total per image — [llama.cpp multimodal docs / HN thread](https://hn.matthewblode.com/item/43943047) (snippet)
- Qwen3-VL image tokenisation: patch_size 16, merge_size 2, default max_pixels 1,310,720, min_pixels 4,095. Qwen3-VL moved to an IMAGE_MAX_TOKEN_NUM-style limit — [Qwen3-VL preprocessor config](https://huggingface.co/Qwen/Qwen3-VL-Reranker-8B/blob/main/preprocessor_config.json), [deepseek.csdn](https://deepseek.csdn.net/6a2f6239662f9a54cb7f29a1.html) (snippets)

### Inferences
- Token maths (from patch 16 x merge 2, so one token per 32x32 px): a 448x448 frame is about 196 visual tokens and a 1280x720 frame is about 900. At the default max, one image can be about 1,280 tokens. Four frames at 720p plus a 400-word (~550 token) prompt is about 4,000 prompt tokens. Downscaling frames to ~512-640 px on the long side cuts this to roughly 300-400 tokens per frame. This is the biggest speed lever.
- On a 4 GB Turing/Ampere laptop-class GPU (GTX 1650 / RTX 3050 4 GB), a fully resident 4B Q4 model plausibly prefills a few hundred to ~1,000 tok/s. So one call with 1-4 downscaled frames and a short JSON answer probably takes ~2-8 s. This is an estimate: no measured 4 GB benchmark was found.
- A 2B model (Qwen3-VL-2B, SmolVLM, Moondream) leaves VRAM headroom for higher image resolution or a larger context. It is likely fast enough (~1-3 s/call) but weaker at nuanced "does this shot fit the script" judgements.
- For 7-8B VLMs with partial offload, decode speed is fine for short JSON answers. Image prefill on the CPU-resident layers is slow, so expect tens of seconds per multi-frame call. This does not meet the few-seconds target.
- 30B-A3B with CPU experts: decode may reach ~10-15 tok/s, but prefill of 1-4k image+prompt tokens on CPU experts will be slow (likely 20-60+ s per call). It is better suited to the 20-40 style-description calls than to 600 judging calls. Unverified.

### Gaps
- No measured seconds-per-image numbers for Qwen3-VL-2B/4B, InternVL 2B/4B, MiniCPM-V 4.x, Moondream 3 or SmolVLM2 on an actual 4 GB NVIDIA card.
- Vision-encoder (mmproj) VRAM sizes per model were not confirmed: HF model pages were blocked.
- No confirmed measurement of Qwen3-VL-30B-A3B prefill speed with CPU experts.

## 2. Windows runtimes: which support which VLMs and features

### Takeaway
llama.cpp's `llama-server` (and the apps built on it: LM Studio, KoboldCpp) is the most capable native-Windows option. It has an OpenAI-compatible `/v1/chat/completions` with multiple `image_url` parts per message. Ollama is the easiest option and rebuilt its multimodal engine in 2026. vLLM needs WSL2/Linux and is overkill for 4 GB.

### Cited Findings
- llama.cpp multimodal goes through libmtmd. A vision GGUF is two files: the LM plus `mmproj-*.gguf`. You load them with `-hf` or with `-m model.gguf --mmproj file.gguf`. llama-server exposes an OpenAI-compatible API — [llama.cpp multimodal docs mirror](https://www.mintlify.com/ggml-org/llama.cpp/inference/multimodal), [llama-server docs](https://www.mintlify.com/ggml-org/llama.cpp/api/tools/llama-server)
- Multiple images per message are supported as standard OpenAI `image_url` parts (base64 data URI or URL). Each image goes before the text that refers to it — [llama.cpp multimodal docs mirror](https://www.mintlify.com/ggml-org/llama.cpp/inference/multimodal)
- Ollama vision models include LLaVA variants, Llama 3.2 Vision, Qwen2.5-VL, MiniCPM-V, Moondream, Granite 3.2 Vision, Gemma 3, Llama 4 and Mistral Small 3.1. Ollama's multimodal support was rebuilt into a dedicated engine (the snippet says May 2026). The API is `/api/chat` with a base64 `images` array — [promptquorum Ollama vision review](https://www.promptquorum.com/power-local-llm/ollama-vision-models-review) (snippet; ollama.com/library/qwen3-vl could not be fetched to confirm the Qwen3-VL tags)
- vLLM supports AWQ only in float16, and its AWQ kernels can be slower than unquantized models on some hardware — [Qwen AWQ docs](https://qwen.readthedocs.io/en/v3.0/quantization/awq.html) (snippet)

### Inferences
- For the ESTA pipeline the simplest local path is `llama-server -m Qwen3-VL-4B-Instruct-Q4_K_M.gguf --mmproj mmproj-...gguf -ngl 99 -c 8192` on Windows (CUDA build), called from `server/` with the OpenAI SDK format. With `--parallel N` it can serve concurrent slots (continuous batching), but on 4 GB the KV cache limits N to about 1-2.
- LM Studio and KoboldCpp both wrap llama.cpp and expose OpenAI-compatible servers, but they add nothing needed here. Ollama is a fine alternative if Qwen3-VL tags are available in the user's Ollama version.
- ExLlamaV2/V3 focus on text LLMs. VLM support was not confirmed and they are not recommended for this use.
- Video input: Qwen3-VL natively accepts video in vLLM/transformers. In llama.cpp/Ollama you send sampled frames as multiple images, which matches the pipeline's "1-4 frames" design anyway.

### Gaps
- I could not confirm from primary sources which exact Ollama version added Qwen3-VL, or whether LM Studio/KoboldCpp support Qwen3-VL mmproj as of Oct 2026.
- ExLlamaV3 VLM support is unverified.

## 3. Free cloud GPU options

### Takeaway
Kaggle (2xT4 or P100, ~30 GPU-h/week floating, detached kernels with an API) is the best $0 heavy lane, and the user already uses it. Colab free bans remote proxies and web UIs, so a tunnelled server is out. HF ZeroGPU's free quota (minutes/day) is far too small. Modal ($5/mo without a card, $30/mo with one) and Lightning AI (15 credits/mo ≈ 80 interruptible GPU-h) are real but smaller supplements, and Modal's larger tier needs a payment method on file.

### Cited Findings
- Kaggle: one P100 (16 GB) or two T4s (32 GB combined), with roughly 30 GPU-hours/week. As of Sept 2026, Kaggle docs give no official number and the quota floats. One source says 9-hour sessions, while the user and others observe 12-hour runs — [gpuperhour](https://gpuperhour.com/blog/free-cloud-gpus-and-credits), [aimultiple](https://aimultiple.com/free-cloud-gpu) (snippets; session length conflicts)
- T4 (Turing, sm_75) meets vLLM's minimum of compute capability 7.0. It has no bf16, so you must pass `--dtype float16`, and FP8 falls back to weight-only Marlin — [markaicode T4 guide](https://markaicode.com/benchmarks/cuda-production-benchmark-latency/) (snippet)
- vLLM issue #26297 (vLLM 0.11.0, Turing RTX 5000 x2): a Qwen3-VL quantized checkpoint failed with "Quantization scheme is not supported for the current GPU. Min capability: 80. Current capability: 75". FlashAttention 2 and FlashInfer sampling were also unavailable on sm_75. No workaround was posted and the issue went stale — [vLLM #26297](https://github.com/vllm-project/vllm/issues/26297)
- `kaggle-vllm` (PyPI) is a toolkit that delivers a validated upstream vLLM runtime on Kaggle's T4 without replacing Kaggle's torch/CUDA. It supports `tensor_parallel_size=2` on dual T4. Its compatibility-first defaults are `dtype="float16"`, `enforce_eager=True` and `disable_custom_all_reduce=True` — [kaggle-vllm on PyPI](https://pypi.org/project/kaggle-vllm/) (snippets; page body did not render)
- Colab: connecting to remote proxies is disallowed from all managed runtimes. Free-tier users who bypass the notebook UI with a web UI commonly get their runtime terminated. These restrictions lift only on paid plans with a positive compute-unit balance — [Colab FAQ](https://research.google.com/colaboratory/faq.html) (snippet)
- HF ZeroGPU (H200 slices): the documented free quota is about 5 GPU-min/day. Some sources say 3.5 min, and forum reports mention a 3-runs/day cap for free users that the official docs do not show. Quota resets 24 h after first use — [HF ZeroGPU docs](https://huggingface.co/docs/hub/spaces-zerogpu.md), [HF forum](https://discuss.huggingface.co/t/what-is-the-free-zerogpu-quota-for-1-space/178610), [HF forum](https://discuss.huggingface.co/t/free-account-zerogpu-quota-issue/175180) (snippets; figures conflict)
- Modal: $5/month free with no payment method, and $30/month free compute on the Starter plan once a card is added — [costbench](https://costbench.com/software/ai-gpu-cloud/modal/free-plan/), [Modal pricing](https://modal.com/pricing) (snippets)
- Lightning AI: 15 free credits/month, about 80 GPU-hours on interruptible machines — [aimultiple](https://aimultiple.com/free-cloud-gpu) (snippet)

### Inferences
- Running Qwen3-VL on Kaggle T4 with vLLM is doable but fragile. Use float16, an AWQ/GPTQ (not FP8 or compressed-tensors schemes that need sm_80+), eager mode, and TP=2. If vLLM refuses the checkpoint, the fallback is transformers + bitsandbytes 4-bit, or llama.cpp CUDA (works on sm_75, supports Qwen3-VL GGUF, splits across 2 GPUs with `--split-mode layer`).
- Sizing on 2xT4 (32 GB total, ~15 GB usable each):
  - Qwen3-VL-8B in fp16 (~17 GB) fits with TP=2.
  - Qwen3-VL-32B AWQ 4-bit (~20 GB weights) fits with TP=2, but the KV/activation headroom for image tokens is tight.
  - InternVL 38B 4-bit is similar or tighter.
  - Qwen3-VL-30B-A3B AWQ (~17 GB) fits and is much faster per token than a dense 32B.
  - A P100 (16 GB, no tensor cores) is slower than the T4 pair; avoid it.
- ZeroGPU is useless at this volume. 5 min/day cannot cover hundreds of calls, and calling someone else's public Space via gradio_client still spends your own quota.
- Exposing a Kaggle kernel via ngrok/cloudflared: Colab explicitly bans it, and no Kaggle statement was found. The batch kernel pattern (section 4) avoids the question entirely and fits the user's existing `kernels push/status/output` workflow.

### Gaps
- No primary Kaggle policy text on tunnelling or long-running servers was found.
- No measured vLLM throughput for Qwen3-VL-8B/32B on 2xT4 was found.
- Exact HF ZeroGPU free quota and whether free accounts can use the Space API could not be confirmed (HF docs were blocked).
- Oracle free tier ARM (CPU only, 4 OCPU / 24 GB was the historical Always Free offer) was not re-verified for 2026.

## 4. Batch pattern: push all frames to a Kaggle kernel, run a big VLM, return JSON

### Takeaway
This is feasible and the best fit for "Claude-quality-ish" judging at $0. Push one dataset of downscaled frames plus a prompts JSONL, then run vLLM offline `LLM.generate` with batching over 500 items. Expect roughly 10-40 minutes of GPU time for a 30B-A3B or 8B model, and longer (~0.5-1.5 h) for a dense 32B AWQ, plus ~5-10 min of setup and model download. These are estimates.

### Cited Findings
- For VLM throughput, use big-batch processing with vLLM/SGLang and raise the prefill budget, since images generate a large number of prompt tokens. Reported rates are roughly 0.58-1 image/s on higher-end GPUs for Qwen2.5-VL — [search summary of vLLM forum / r/LocalLLaMA](https://discuss.vllm.ai/t/why-is-inference-for-qwen-2-5-vl-so-slow-when-we-send-an-image/1438), [reddit snapshot](https://reddit.sentinel-team.org/posts/1pun4kk/snapshots/2025-12-25T01%3A27%3A59.745693Z) (snippets)
- Qwen2.5-VL inference is markedly slower than text-only inference because of image token overhead — same source.
- Multi-GPU image-captioning batch pattern write-up — [Medium: Image captioning on multiple GPUs](https://medium.com/@geronimo7/image-captioning-on-multiple-gpus-0a50cecbdcc4)

### Inferences
- Workload estimate: 500 calls x (2 frames x ~300 tokens at 512 px + ~550 prompt tokens) ≈ 575k prefill tokens, and 500 x ~60 output tokens ≈ 30k decode tokens. On 2xT4 fp16 with continuous batching, prefill for an 8B/A3B model at perhaps 1-3k tok/s puts the job in the 5-15 minute range. A dense 32B AWQ is likely 3-5x slower. These are order-of-magnitude estimates only.
- Use the shared ~400-word rubric as a common prefix so vLLM prefix caching skips re-prefilling it. Put the images after the rubric.
- Run the 500-item batch for one video in a single kernel. Each video costs roughly 0.5-1.5 GPU-h, so the 30 h/week quota covers ~20+ videos even after the other Kaggle jobs. It is not interactive, though: kernel queue plus boot plus model load adds ~5-15 minutes of latency.
- A hybrid fits well: a local 2-4B model for fast first-pass filtering, plus a Kaggle batch with a 30B-A3B/32B for final picks and the style-description calls.

### Gaps
- No public Kaggle notebook was found that benchmarks Qwen3-VL batch inference on 2xT4.

## 5. Existing projects doing VLM b-roll / stock-footage selection on free GPUs

### Takeaway
I found no open-source project that does VLM-based stock/b-roll judging in batch on Kaggle/Colab. The visible tools are commercial (InVideo, VideoGen, AutoCut AutoB-Rolls) or small READMEs.

### Cited Findings
- Hooked AI Video Editor: uses LLMs for b-roll suggestions and CV for video analysis (Notion README) — [Hooked README](https://valley-passive-e5f.notion.site/README-for-Video-Editing-11e515dbae99816ca779dc780c1bdd87)
- Commercial script-to-b-roll matchers: [InVideo](https://info.invideo.io/blog/automatic-b-roll-selection-video-script-invideo), [VideoGen](https://videogen.io/ai-b-roll-generator), [AutoCut AutoB-Rolls](https://www.autocut.com/autobroll/)

### Inferences
- ESTA would be building this pattern itself. The closest reusable pieces are the `kaggle-vllm` toolkit and the Medium multi-GPU captioning pattern.

### Gaps
- GitHub code search for "b-roll" + "qwen-vl"/"vlm" + "kaggle" was not run within the tool budget, so niche repos may exist.
