# Apple vision / AI tech as a free vision model for the ESTA pipeline (as of Oct 2026)

Bottom-line verdict (for the report writer): **No Apple option runs on the user's Windows PC except Apple's open research weights (FastVLM, MobileCLIP2), and those are research-only/non-commercial licensed.** Everything else (Vision framework, Foundation Models on-device model, Private Cloud Compute server model, MLX) needs a Mac (Apple silicon) or iPhone. If the user buys/owns an Apple-silicon Mac, the useful path is **MLX / mlx-vlm running open VLMs (Qwen3-VL etc.) as a LAN vision server** — not Apple's own models. Apple's own models are small and app-oriented; they can help with narrow subtasks (OCR of scoreboards/on-screen text, aesthetics filtering, similarity) but are not a substitute for a strong VLM judge of "does this frame match this detailed shot description".

## 1. Apple Vision framework (classification, OCR, saliency, aesthetics, detection, feature prints)

### Takeaway
Vision is a set of fixed-purpose, fast, on-device CV APIs, not a generative VLM. It can contribute OCR (scoreboards, on-screen text), aesthetics/utility scoring for filtering stock, and feature-print similarity — but it cannot answer "does this frame match this shot description" or identify specific people/venues. Apple-OS only.

### Cited Findings
- `CalculateImageAestheticsScoresRequest` returns an `ImageAestheticsScoresObservation`; `overallScore` is a float from -1 to 1 (higher = more aesthetically pleasing) and factors in blur, exposure, color balance, composition and subject matter — [createwithswift](https://www.createwithswift.com/scoring-the-aesthetics-of-an-image-with-the-vision-framework/); [Apple docs](https://developer.apple.com/documentation/vision/calculateimageaestheticsscoresrequest.md)
- `isUtility` flags images that are not poor quality but lack memorable content (e.g., screenshots, receipts) — [Apple docs: isUtility](https://developer.apple.com/tutorials/data/documentation/vision/vnimageaestheticsscoresobservation/isutility.md)
- WWDC26 "What's new in image understanding": Vision now ships pre-built tools for LLMs — a `BarcodeReaderTool` and an OCR tool for "dense or fine text in 30+ languages" — designed to be combined with Foundation Models image input; Apple positions Vision as fast enough for real-time video analysis, while Foundation Models handles open-ended descriptive tasks — [WWDC26 session 237](https://developer.apple.com/videos/play/wwdc2026/237)
- Vision is also exposed to non-Swift languages via Objective-C bindings (e.g., Rust `objc2-vision`), but still requires macOS/iOS at runtime — [docs.rs objc2-vision](https://docs.rs/objc2-vision/)

### Inferences
- Realistic contributions to ESTA (Mac required): (a) OCR on candidate frames to verify scoreboards / on-screen text against the shot description (cheap pre-check before a VLM); (b) aesthetics + `isUtility` filter to drop ugly/blurry/screenshot-like stock; (c) feature-print distance for near-duplicate detection or "looks like this reference frame" similarity.
- Not able to: recognise specific named people, specific venues, judge semantic match to a free-text description, or describe style. VNClassifyImageRequest is a fixed taxonomy (~1,000+ labels) — useful as tags only.
- The Windows pipeline already has CLIP (style-analysis uses OpenCV + CLIP), plus open OCR (e.g. PaddleOCR/EasyOCR) can do comparable OCR/similarity on Windows; Vision's advantage is mostly speed/quality of OCR on Apple hardware, not a new capability.

### Gaps
- I did not verify the exact VNClassifyImageRequest label count or OCR accuracy benchmarks vs PaddleOCR in 2026 sources.

## 2. Apple Foundation Models framework (on-device ~3B) and Private Cloud Compute server model

### Takeaway
As of WWDC26 (June 2026), the Foundation Models framework **does accept image input** (Prompt `Attachment(image)`), and Apple now offers its larger **PCC server model free to small developers**, plus a route to third-party models (Claude/Gemini) via the same Swift API. But: Apple-OS only, app-oriented (entitlement + App Store Small Business Program for PCC), per-user daily quotas, small on-device context (4K-8K tokens). The on-device 3B is roughly peer to small open VLMs (Qwen2.5-VL-3B / Gemma-3-4B class) per Apple's own 2025 report — not Claude-quality.

### Cited Findings
- 2025 (iOS/macOS 26): Foundation Models opened the ~3B on-device model to developers for text generation, extraction, guided generation, tool calling — but it **could not take an image as input** in 2025 — [implicator.ai via search](https://www.implicator.ai/apple-expands-xcode-and-foundation-models-for-wwdc-ai-developers/) (page blocked to fetch; snippet only)
- WWDC26 adds image input: `Prompt { "Generate a caption for this image"; Attachment(image) }`, plus images as tool arguments via `ImageReference` — [WWDC26 session 237](https://developer.apple.com/videos/play/wwdc2026/237)
- Apple's 2025 tech report: ~3B on-device model with KV-cache sharing and 2-bit quantization-aware training; image-text pretraining on >10B image-text pairs; on-device model "performs favorably against the larger InternVL and Qwen models and competitively against Gemma" on image understanding; server model outperforms Qwen-2.5-VL at < half the inference FLOPs but is **behind Llama-4-Scout and GPT-4o** — [Apple ML Research: Foundation Models 2025 updates](https://machinelearning.apple.com/research/apple-foundation-models-2025-updates) (summary via search; site blocked to direct fetch); [Tech report 2025](https://pr-mlr-shield-prod.apple.com/research/apple-foundation-models-tech-report-2025)
- PCC server model for developers (WWDC26 session 319): `LanguageModelSession(model: PrivateCloudComputeLanguageModel())`; 32K context vs 4K on-device (iOS 26.0) / 8K on newer devices on 27.0; reasoning levels light/moderate/deep; requires internet; **daily per-user (iCloud account) limit**, iCloud+ raises it; zero token cost to developer; no API keys — auth via OS/iCloud; requires Apple Intelligence-capable device; app must apply for the entitlement; apps with <2M downloads only. Image input on the PCC model was **not mentioned** in that session — [WWDC26 session 319](https://developer.apple.com/videos/play/wwdc2026/319/)
- Eligibility: app enrolled in App Store Small Business Program with <2M first-time downloads; access terminated above that — [search summary of theswift.dev / blakecrosley.com](https://blakecrosley.com/blog/foundation-models-private-cloud-compute); [aimadetools](https://www.aimadetools.com/blog/apple-foundation-models-free-cloud-ai-small-developers/)
- WWDC26 also: server-side integration letting developers call third-party models like Claude and Gemini through the same Swift API; Foundation Models framework to be open-sourced — [MacRumors, June 9 2026](https://www.macrumors.com/2026/06/09/apple-outlines-major-ai-and-developer-tool-updates/); [NYU Shanghai RITS](https://rits.shanghai.nyu.edu/ai/apple-open-sources-its-foundation-models-framework-adds-claude-and-gemini/) (both via search snippets; not fetched)
- Gemini/Siri: Apple's new Siri (iOS 26.4, ~March 2026) is powered by Gemini-based "Apple Foundation Models v10" (~1.2T params reported) on PCC; reported ~$1B/yr deal; Tim Cook confirmed it runs on PCC — [letsdatascience](https://letsdatascience.com/news/apple-integrates-google-gemini-to-power-siri-features-c2e705ab); [iphonesoft.fr](https://iphonesoft.fr/2026/01/30/tim-cook-confirme-siri-alimente-gemini-utilisera-private-cloud-compute) (parameter count and price are press reports, not Apple-confirmed)

### Inferences
- On-device 3B with image input is roughly a Qwen2.5-VL-3B / Gemma-3-4B-class VLM by Apple's own framing — fine for captions/tags, weak for fine-grained "is this the specific stadium/player/scoreboard state in the description" judging. Small context (4K-8K) also limits multi-frame clip understanding.
- The PCC server model is free only within Apple's app model: a Swift app with the entitlement, per-user daily quota, Apple Intelligence device. A personal Mac command-line tool calling it from a batch pipeline is not clearly supported, and quotas make bulk frame-judging (hundreds of frames per video) unreliable. Image support on PCC is unconfirmed.
- The Gemini-powered Siri model is not a developer API; it does not give third parties free Gemini vision access. The "third-party models via Swift API" path presumably uses the developer's own provider keys/billing (not verified) — not free.
- No video/clip input API was found; clip understanding would mean sampling frames.

### Gaps
- Could not fetch Apple's tech report directly (egress blocked) for exact image benchmark tables.
- Not confirmed: whether PCC model accepts images; whether Foundation Models (on-device or PCC) can be called from an unsigned macOS CLI/daemon; exact daily quota numbers; who pays for Claude/Gemini calls routed through the framework.
- Did not verify whether Foundation Models image input shipped in macOS 27 release (Sept/Oct 2026) or remains beta.

## 3. Apple open research models: FastVLM, MobileCLIP/MobileCLIP2, AIMv2

### Takeaway
FastVLM (0.5B/1.5B/7B) is fast but its weights are under the **Apple Machine Learning Research Model license: research-only, non-commercial, revocable** — not usable for a YouTube video business. MobileCLIP2 uses the same apple-amlr license. Technically, FastVLM runs in plain PyTorch and via HF `trust_remote_code`, so it could run on Windows (7B won't fit a 4 GB GPU unquantized), but the license rules it out for commercial use. Its quality ceiling (Qwen2-7B LLM) is well below current Qwen3-VL.

### Cited Findings
- FastVLM sizes 0.5B / 1.5B / 7B (7B uses Qwen2-7B LLM); smallest beats LLaVA-OneVision-0.5B with 85x faster TTFT and 3.4x smaller vision encoder; 7B beats Cambrian-1-8B with 7.9x faster TTFT; PyTorch inference via `predict.py`; Apple-silicon export (fp16/int8/int4) and iOS demo app — [apple/ml-fastvlm GitHub](https://github.com/apple/ml-fastvlm)
- LICENSE_MODEL: "personal, non-exclusive ... revocable, and limited license ... exclusively for Research Purposes ... 'Research Purposes' does not include any commercial exploitation, product development or use in any commercial product or service." Derivatives (fine-tunes) also research-only — [ml-fastvlm LICENSE_MODEL](https://raw.githubusercontent.com/apple/ml-fastvlm/main/LICENSE_MODEL)
- FastVLM-7B on Hugging Face (apple-amlr), loads with transformers `trust_remote_code` — [HF apple/FastVLM-7B](https://huggingface.co/apple/FastVLM-7B/tree/main) (via search snippet)
- MobileCLIP2 checkpoints on HF are `license: apple-amlr`; community ONNX export exists — [HF apple/mobileclip2 README](https://huggingface.co/apple/mobileclip2_coca_dfn2b_s13b_context77/blob/main/README.md); [plhery/mobileclip2-onnx](https://huggingface.co/plhery/mobileclip2-onnx)
- Third-party comparison recommends SmolVLM2 over FastVLM when license simplicity for commercial product matters — [aiidelist FastVLM vs SmolVLM2](https://aiidelist.com/blog/fastvlm-vs-smolvlm2)
- Apple released FastVLM and MobileCLIP2 on HF with a real-time WebGPU in-browser video captioning demo (Aug 2025) — [smol.ai news](https://news.smol.ai/issues/25-08-29-not-much)

### Inferences
- FastVLM/MobileCLIP2 *can* run on Windows (PyTorch/ONNX; 0.5B/1.5B fit 4 GB), but the user monetises videos, so the research-only license makes them a non-starter. Even ignoring license, a Qwen2-based 7B VLM is a step down from Qwen3-VL-8B, which is Apache-2.0.
- AIMv2 is a vision encoder family (not a chat VLM) — not directly useful as a judge.

### Gaps
- Did not check AIMv2's license or any 2026 Apple open-model release (none surfaced in searches).
- No verified FastVLM benchmark vs Qwen3-VL found.

## 4. MLX / mlx-vlm on Apple silicon; Mac mini as a LAN vision server

### Takeaway
This is the only Apple-side route that genuinely helps: a Mac running MLX/mlx-vlm (or oMLX / vllm-mlx) serving open VLMs like Qwen3-VL over an OpenAI-compatible HTTP API, reachable from the Windows PC over LAN. Community benchmarks show Qwen3-VL-4B at ~33-37 tok/s and Qwen3-VL-30B-A3B (MoE) at ~41 tok/s on base M4 machines. Dense 32B VLMs need 32 GB+ and run much slower (memory-bandwidth bound).

### Cited Findings
- oMLX community benchmarks (macOS 26.3.1, 1k context, token generation): Qwen3-VL-4B-Instruct on M4 10-core 16 GB ~37.1 tok/s; on M4 32 GB ~32.8 tok/s; Qwen3-VL-30B-A3B-Instruct on M4 10-core 32 GB ~41.1 tok/s — [oMLX benchmarks](https://omlx.ai/benchmarks/fqyhj2ep) and sibling pages (via search summary; individual pages not fetched)
- vllm-mlx reported up to ~400 tok/s aggregate on Apple silicon (German press) — [borncity](https://borncity.com/news/vllm-mlx-apples-neuer-ki-server-erreicht-400-token-sekunde/) (not verified, likely batched throughput)
- Mac mini M4 Pro 24 GB runs a Qwen 3.6 model at Q4 ~15-22 tok/s via MLX; M4 Pro 64 GB has 273 GB/s bandwidth — [search summary of hardware guides](https://www.compute-market.com/blog/qwen-3-6-local-hardware-guide-2026) (secondary source)

### Inferences
- For ESTA's frame judging (short outputs: yes/no + reasoning), prompt-processing (image tokens) speed matters more than generation speed; MLX prefill on base M4 is notably slower than a 3090. Not verified with numbers.
- A Mac mini as a headless LAN server is architecturally simple: mlx-vlm / oMLX expose OpenAI-compatible endpoints; the Windows backend (:8787) or Python tools would just POST frames. Qwen3-VL-30B-A3B on a 32 GB M4 is the sweet spot for quality/speed per dollar on Mac.

### Gaps
- No verified prefill (image-token) throughput numbers or dense 32B VLM (Qwen3-VL-32B) tok/s on M4 Pro 64 GB found.
- Did not verify mlx-vlm video input support specifics.

## 5. Does any of it run on Windows?

### Takeaway
No, except FastVLM / MobileCLIP2 weights (PyTorch / ONNX) — which are research-only licensed. Vision framework, Foundation Models (on-device and PCC) and MLX all require Apple OS on Apple silicon.

### Cited Findings
- FastVLM runs via plain PyTorch `predict.py`; HF checkpoints use `trust_remote_code` — [ml-fastvlm](https://github.com/apple/ml-fastvlm); [HF FastVLM-7B](https://huggingface.co/apple/FastVLM-7B/tree/main)
- Foundation Models / PCC require Apple Intelligence-capable devices and an app entitlement — [WWDC26 session 319](https://developer.apple.com/videos/play/wwdc2026/319/)
- MLX targets Apple silicon (oMLX benchmarks are all macOS) — [oMLX benchmarks](https://omlx.ai/benchmarks/fqyhj2ep)

### Inferences
- If the user owns an iPhone only: theoretically a custom iOS app could run Foundation Models image prompts, but bridging that into a Windows batch pipeline is impractical. Not recommended.

### Gaps
- None material.

## 6. Hardware cost: cheapest Mac for a 32B VLM vs used RTX 3090

### Takeaway
A Mac mini M4 Pro 64 GB is ~$2,000-2,200 new; a used RTX 3090 24 GB is ~$700-900 and runs 32B Q4 models and Qwen 35B-A3B MoE much faster — but needs a PC that can host it (PSU/case), which the user's current PC may or may not support. For pure "local vision server" value, the 3090 wins on price/performance; the Mac wins on power draw, silence, and 64 GB capacity (bigger models / higher quant).

### Cited Findings
- Mac mini M4 Pro 64 GB: from $1,999 (12-core) / $2,199 (14-core), 512 GB; base M4 Pro $1,299 — [9to5toys / macprices summary](https://www.macprices.net/macmini.shtml) (prices may be dated; 2025 listings)
- Mac Studio M4 Max 16-core/40-GPU, 64 GB, 1 TB: $2,923.99 at CDW — [CDW](https://m.cdw.com/product/apple-mac-studio-m4max-64-gb-ram-1-tb-ssd/8288076)
- Used RTX 3090 24 GB: $699-999, healthy range $700-900; runs 32B at Q4 — [modelfit.io](https://modelfit.io/gpu/rtx-3090/); [bestgpuforllm](https://bestgpuforllm.com/articles/used-rtx-3090-buying-guide-for-llm/)
- RTX 3090: Qwen 3.5-35B-A3B at Q4_K ~111 tok/s at 4K context — [agentnativedev Medium](https://agentnativedev.medium.com/qwen-3-5-35b-a3b-why-your-800-gpu-just-became-a-frontier-class-ai-workstation-63cc4d4ebac1) (secondary)

### Inferences
- Rough throughput: 3090 (~936 GB/s) vs M4 Pro (273 GB/s) — ~3x faster generation on the 3090 for models that fit in 24 GB; MoE 30B-A3B VLMs make both viable.
- Cheapest Mac that runs a dense 32B VLM "well": 64 GB M4 Pro mini (~$2k) runs it, but slowly (likely single-digit to low-teens tok/s — unverified). A 32 GB base M4 mini (~$1,000-1,200, not verified) is enough for Qwen3-VL-30B-A3B.

### Gaps
- Late-2026 Mac pricing (M5-generation Mac mini, if released) not verified; possible DRAM-driven price changes in 2026 not checked.
- Base M4 Mac mini 32 GB current price not verified.
