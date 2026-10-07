# Open-weight VLM quality vs Claude / GPT / Gemini (as of Oct 2026)

Research note on method: WebFetch to huggingface.co, arxiv.org, ai.google.dev, NVIDIA NGC/build, modelscope, substack and most blogs was blocked by the egress proxy in this session. Primary sources reached directly: the official GitHub READMEs (raw.githubusercontent.com) of QwenLM/Qwen3.5, QwenLM/Qwen3-VL, QwenLM/Qwen3-Omni, OpenGVLab/InternVL, OpenBMB/MiniCPM-V, zai-org/GLM-V, allenai/molmo2, MoonshotAI/Kimi-VL, AIDC-AI/Ovis, deepseek-ai/DeepSeek-VL2. All benchmark numbers below otherwise come from search-result extracts of model cards/aggregators (URL given); they could not be opened and checked against the full table, so treat individual numbers as "reported, not re-verified". All benchmark numbers are vendor self-reported unless stated.

## 1. Which open VLM families lead right now (incl. 2026 releases)?

### Takeaway
As of Oct 2026 the open frontier for vision is natively multimodal LLMs rather than separate "-VL" models: Qwen3.5 / Qwen3.6 / Qwen3.8 (Alibaba, Apache 2.0), Kimi K2.5 (Moonshot, ~1T MoE), GLM-5.3-Flash (Z.ai, MIT) and Gemma 4 (Google, Apache 2.0). For a single-GPU deployment, the dense ~27B Qwen (3.6-27B, now 3.8-27B) is the community's default pick. Older dedicated VLM families (Qwen3-VL, InternVL3.5, MiniCPM-V 4.5, GLM-4.5V/4.6V, Molmo 2, Ovis2.5, Kimi-VL) are now one generation behind but still relevant at small sizes.

### Cited Findings
**Qwen (Alibaba)**
- Release timeline from the official repo: Qwen3.5-397B-A17B (2026-02-16); Qwen3.5-122B-A10B, 35B-A3B, 27B (2026-02-24); Qwen3.5-9B/4B/2B/0.8B (2026-03-02); Qwen3.6-35B-A3B (2026-04-16); Qwen3.6-27B (2026-04-22); Qwen3.8-2.4T-A95B (2026-08-12); Qwen3.8-27B (2026-08-14). — [QwenLM/Qwen3.5 README](https://raw.githubusercontent.com/QwenLM/Qwen3.5/main/README.md)
- Qwen3.5 is a "Unified Vision-Language Foundation: early fusion training on trillions of multimodal tokens ... outperforms Qwen3-VL models across reasoning, coding, agents, and visual understanding benchmarks". llama.cpp supports the series for text and vision, and mlx-vlm on Apple Silicon. — [QwenLM/Qwen3.5 README](https://raw.githubusercontent.com/QwenLM/Qwen3.5/main/README.md)
- Qwen3.8 "brings a Qwen-Max-class model to open release" (2.4T-A95B). — [QwenLM/Qwen3.5 README](https://raw.githubusercontent.com/QwenLM/Qwen3.5/main/README.md)
- Qwen3.8-27B: dense, native vision-language (image and video), Apache 2.0, released 2026-08-14, 262K context (extensible to 1M). Reported gains over Qwen3.6-27B on SWE-bench Multimodal, MathVision, CharXiv and an internal Vision2Web suite. — [DataNorth](https://datanorth.ai/news/alibaba-releases-qwen3-8-27b); [Qubrid](https://www.qubrid.com/blog/qwen38-27b-api-benchmarks-pricing-and-the-complete-developer-guide). I did not find its full vision benchmark table.
- Community: "Qwen 3.6 dropped the separate VL track, vision is now baked in, and the 27B dense is the new state-of-the-art local vision model on 24GB+". — [tinyweights.dev / latent.space summaries via search](https://tinyweights.dev/posts/best-local-vision-language-models-2026/)
- The earlier dedicated Qwen3-VL line (2B/4B/8B/32B dense, 30B-A3B and 235B-A22B MoE, Instruct and Thinking variants, released Sep–Oct 2025; tech report Nov 2025). — [QwenLM/Qwen3-VL README](https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/README.md)

**Other 2026 releases**
- Kimi K2.5 (Moonshot, Jan 27 2026): first Moonshot flagship with multimodal input, open weights. Artificial Analysis describes it as "the first time that the leading open weights model has supported image input". — [Artificial Analysis](https://artificialanalysis.ai/articles/kimi-k2-5-everything-you-need-to-know)
- GLM-5.3-Flash (Z.ai, released 2026-08-26): "our first open-source natively multimodal model". — [zai-org/GLM-V README](https://raw.githubusercontent.com/zai-org/GLM-V/main/README.md). Reported as 320B total / 18B active MoE with a 24-layer vision encoder for image and video, MIT license, 1M context. — [Eigent](https://www.eigent.ai/blog/glm-5-3-flash-multimodal-model); [CometAPI](https://www.cometapi.com/models/zhipuai/glm-5-3-flash/). Z.ai also shipped GLM-5V-Turbo (2026-04-02), which is API-only per the docs link. — [GLM-V README](https://raw.githubusercontent.com/zai-org/GLM-V/main/README.md)
- Gemma 4 (Google, 2026-04-02): Apache 2.0 (Gemma 1–3 used the custom Gemma license). Variants: E2B, E4B, 26B-A4B MoE, 31B dense. Text+image input on all, audio on the small ones, video supported as frames. — [releases.sh](https://releases.sh/release/rel_HT8t3Rgp88YkgpZPWByzZ); [NYU Shanghai RITS](https://rits.shanghai.nyu.edu/ai/google-releases-gemma-4-frontier-open-models-under-apache-2-0/). One search extract also mentions a "12B unified" variant and another a "Gemma 4 120B". I could not confirm either, so treat them as unverified.
- MiniCPM-o 4.5 (9B, open-sourced 2026-02-03): "matches Gemini 2.5 Flash on vision and speech", full-duplex streaming. MiniCPM-V 4.6 (1.3B, 2026-05-11): built on SigLIP2-400M + Qwen3.5-0.8B and "reaches Qwen3.5 2B-level capability" on OpenCompass, RefCOCO, HallusionBench, OCRBench. In Ollama since 2026-06-25. — [OpenBMB/MiniCPM-V README](https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md)
- Molmo 2 (Ai2, paper arXiv 2601.10611, Jan 2026): "state-of-the-art among open-source models" for point-driven grounding in single image, multi-image and video, plus tracking. Open weights AND open data. — [allenai/molmo2 README](https://raw.githubusercontent.com/allenai/molmo2/main/README.md)

**2025 families (one generation behind)**
- InternVL3.5 (2025-08-26, largest 241B-A28B; also a GPT-OSS-20B-based variant). The repo is MIT. No InternVL4 announced in the repo news. — [OpenGVLab/InternVL README](https://raw.githubusercontent.com/OpenGVLab/InternVL/main/README.md)
- GLM-4.5V (2025-08-11) and GLM-4.6V (implementation in transformers `glm4v_moe`). The GLM-V repo has been unmaintained since 2026-09-02. — [GLM-V README](https://raw.githubusercontent.com/zai-org/GLM-V/main/README.md)
- MiniCPM-V 4.5 (8B, 2025-08-26): claims to beat GPT-4o-latest, Gemini-2.0 Pro and Qwen2.5-VL-72B. — [MiniCPM-V README](https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md)
- Ovis2.5-2B/9B (2025-08-15), Apache 2.0. — [AIDC-AI/Ovis README](https://raw.githubusercontent.com/AIDC-AI/Ovis/main/README.md)
- Kimi-VL-A3B-Thinking-2506 (Jun 2025): MMMU 64.0, MMMU-Pro 46.3, VideoMMMU 65.2, Video-MME 71.9. — [MoonshotAI/Kimi-VL README](https://raw.githubusercontent.com/MoonshotAI/Kimi-VL/main/README.md)
- DeepSeek-VL2 (Dec 2024): the code is MIT and the weights are under the DeepSeek Model License ("supports commercial use"). No newer open DeepSeek VLM found. — [DeepSeek-VL2 README](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-VL2/main/README.md)

### Inferences
- For the ESTA use case (single local GPU or a Kaggle T4), the realistic candidates are Qwen3.8-27B, Qwen3.6-27B or Qwen3.6-35B-A3B, Qwen3.5-9B, Gemma 4 26B-A4B or 31B, and MiniCPM-o 4.5 / MiniCPM-V 4.5. Kimi K2.5, GLM-5.3-Flash, Qwen3.5-397B and Qwen3.8-2.4T need multi-GPU servers, or a hosted API.
- Llama 4 vision, Pixtral/Mistral Small 3.x, Phi-4-multimodal and SmolVLM did not appear as leaders in any 2026 source found. They look superseded for this task.

### Gaps
- I could not open the full model cards for Qwen3.6/3.8, Gemma 4, Kimi K2.5 or GLM-5.3-Flash (blocked), so I have no full per-benchmark tables for them.
- I found no 2026 data for Llama 4 vision, Mistral Small 3.x/Medium vision, Phi-4-MM, SmolVLM or Moondream 3. The Moondream repo README only lists 2B/0.5B.
- InternVL4 or an InternVL3.5 successor: none found.

## 2. Benchmarks side by side with Claude / GPT / Gemini; which sizes reach near-frontier?

### Takeaway
On static benchmarks, the largest open models (Qwen3.5-397B, Kimi K2.5) now match or beat Claude Opus 4.5 and sit just below GPT-5.2 / Gemini 3 Pro on MMMU/MMMU-Pro. Mid-size models (27B–35B-A3B) are within ~2–5 points of them on MMMU. Even Qwen3.5-9B beats Claude Opus 4.5 on reported OCRBench. Human-preference ranking tells a different story: on LMArena Vision (Mar 2026) the best open model (Qwen3.5-27B, 1237) sat about 50 Elo below Gemini 3 Pro (1290), at rank #20. Claude is not the visual frontier on benchmarks: Gemini 3 Pro and GPT-5.2 lead.

### Cited Findings
**Frontier-scale open vs closed (vendor-reported in Qwen3.5 model card, Feb 2026)**
| Benchmark | Qwen3.5-397B-A17B | GPT-5.2 | Claude Opus 4.5 | Gemini 3 Pro |
|---|---|---|---|---|
| MMMU | 85.0 | 86.7 | 80.7 | 87.2 |
| MMMU-Pro | 79.0 | 79.5 | 70.6 | 81.0 |
— [paperswithcode/Qwen3.5 extract via search](https://paperswithcode.co/benchmark/mmmu); [DeepLearning.AI The Batch](https://www.deeplearning.ai/the-batch/alibabas-latest-flagship-models-are-open-weights-moe-performers-in-sizes-from-less-than-1b-parameters). Qwen claims Qwen3.5-397B outperformed GPT-5.2, Claude 4.5 Opus and Gemini 3 Pro on 28 of 44 vision benchmarks. That is a vendor claim, and the 44-row table could not be opened.

**Kimi K2.5 vs Claude Opus 4.5 (Moonshot-reported, Jan 2026)**: MMMU-Pro 78.5 vs 74.0; VideoMMMU 86.6 vs 84.4; OCRBench 92.3 vs 86.5. — [aicybr summary of model card](https://aicybr.com/blog/kimi-k2-5-guide); [NVIDIA NIM card](https://docs.api.nvidia.com/nim/reference/moonshotai-kimi-k2-5). Note that Claude Opus 4.5 scores differently in the two vendors' tables (MMMU-Pro 70.6 in Qwen's vs 74.0 in Moonshot's). Each vendor ran its own harness, so numbers across vendor tables are not directly comparable.

**Mid/small open models (vendor-reported)**
- Qwen3.5: MMMU 83.9 (122B-A10B), 82.3 (27B), 81.4 (35B-A3B); MathVision 86.2 (122B) / 86.0 (27B); MathVista-mini 87.4 (122B) / 87.8 (27B). — [Qwen3.5-35B-A3B HF card via search](https://huggingface.co/Qwen/Qwen3.5-35B-A3B)
- Qwen3.6-27B (Apr 2026): MMMU 82.9, MMMU-Pro 75.8, MMStar 81.4, RealWorldQA 84.1, MathVista-mini 87.4, VideoMMMU 84.4, Video-MME (w/ subs) 87.7. — [Qwen3.6-27B HF card via search](https://huggingface.co/Qwen/Qwen3.6-27B); [codesota](https://www.codesota.com/model/qwen3.6-27b)
- Qwen3.5-9B: MMMU-Pro 70.1, MathVision 78.9, OCRBench 89.2, OmniDocBench 87.7, VlmsAreBlind 93.7 (vs GPT-5-Nano MMMU-Pro 57.2, OmniDocBench 55.9). — [awesomeagents](https://awesomeagents.ai/models/qwen-3-5-9b/); [Qwen3.5-9B HF](https://huggingface.co/Qwen/Qwen3.5-9B)
- Gemma 4 MMMU-Pro: 31B 76.9, 26B-A4B 73.8, (reported "12B" 69.1), E4B 52.6, E2B 44.2. 26B-A4B MATH-Vision 82.4. — [Gemma 4 model card via search](https://ai.google.dev/gemma/docs/core/model_card_4?hl=de); [insiderllm](https://insiderllm.com/guides/gemma-4-local-ai-guide/). By MMMU-Pro, Gemma 4 31B (76.9) sits slightly above Qwen3.6-27B (75.8) and above Claude Opus 4.5 (70.6–74.0).
- Qwen3-VL-8B-Instruct (Oct 2025): OCRBench 89.6, HallusionBench 61.1, Video-MME 71.4, MVBench 68.7. — [datalearner](https://www.datalearner.com/en/ai-models/pretrained-models/qwen3-vl-8b-instruct/analysis); [codesota](https://www.codesota.com/model/qwen3-vl-8b-instruct)
- Qwen3-VL-4B MMMU 67.4 vs Gemma 3 27B 64.9. — [insiderllm vision guide](https://insiderllm.com/guides/vision-models-locally/)
- Kimi-VL-A3B-Thinking-2506: MMMU 64.0, Video-MME 71.9. — [Kimi-VL README](https://raw.githubusercontent.com/MoonshotAI/Kimi-VL/main/README.md)

**Human preference / independent**
- LMArena Vision (Mar 2026): #1 Gemini 3 Pro 1290, #2 Gemini 3.1 Pro Preview 1276, #3 GPT-5.2 Chat 1275. The top open model, Qwen3.5-27B, scored 1237 at #20. — [codesota arena summary](https://www.codesota.com/arena/vision); [arena.ai vision leaderboard](https://arena.ai/de/leaderboard/vision)
- GLM-5.3-Flash averaged 66.3% on a third-party six-task "Vision Evals" suite, rank #22 of 33, with the suite not detailed. — [Roboflow playground via search](https://playground.roboflow.com/models/z-ai/glm-5-3-flash)
- Low-quality aggregator data to avoid: one 2026 listicle still claims "Qwen2.5-VL-72B leads open-weight VLMs at ~70.2 MMMU". That is stale (early-2025 data). — [presenc.ai](https://presenc.ai/research/best-open-weight-vision-language-models-2026)

### Inferences
- Near-frontier sizes: 27B dense / 35B-A3B (Qwen3.5/3.6/3.8) and Gemma 4 26B–31B reach roughly Claude Opus 4.5 level on MMMU/MMMU-Pro. 8–9B reaches it on OCR-type benchmarks but not on reasoning (MMMU-Pro ~70). Below 4B, quality drops off sharply (Gemma 4 E4B MMMU-Pro 52.6).
- The roughly 50-Elo LMArena gap, despite benchmark parity, suggests open models still trail frontier closed models on open-ended, real-user visual questions. That gap is closer to the ESTA "judge this clip" task than MMMU is.

### Gaps
- I found no reliable side-by-side for Claude Sonnet 4.5/4.6/5 or Claude Opus 4.6/4.7/5 vision benchmarks against open models. The only Claude numbers found are Opus 4.5 in the Qwen and Kimi vendor tables.
- No Gemini 3.1 or GPT-5.5 vision numbers against open models.
- No full MMBench / MMStar / POPE / HallusionBench row with frontier models for 2026 open models.
- No current (Oct 2026) LMArena snapshot. The latest found is March 2026, before Qwen3.6/3.8, Gemma 4 and GLM-5.3-Flash.

## 3. OCR of in-frame text, public-figure identification, grounding, hallucination, strict JSON

### Takeaway
OCR and grounding are where open models are strongest. Qwen and Kimi beat Claude on reported OCRBench, and Qwen/Molmo 2 give box/point grounding that Claude does not offer natively. Public-figure identification is a real differentiator in the other direction from what you might expect: Qwen3-VL explicitly trains to "recognize everything — celebrities", whereas InternVL3.5 largely fails and Claude by policy does not identify people by face. Hallucination resistance and calibrated "default to mismatch" behaviour are the weakest area for small open models. No benchmark captures it well, so it needs a local eval.

### Cited Findings
- **OCR**: Qwen3-VL expanded OCR to 32 languages, "robust in low light, blur, and tilt". — [Qwen3-VL README](https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/README.md). Reported OCRBench scores: Kimi K2.5 92.3, Qwen3-VL-8B 89.6, Qwen3.5-9B 89.2; Claude Opus 4.5 86.5 (Moonshot table). — sources above. MiniCPM-V 4.5 claims leading OCRBench, surpassing GPT-4o-latest and Gemini 2.5. — [MiniCPM-V 4.5 arXiv 2509.18154 via search](https://arxiv.org/pdf/2509.18154)
- Gemma 4 OCR caveat: users reported OCR failures and infinite loops on basic image reading. Its vision token budget is configurable (70–1120 tokens per image), and 560–1120 is needed for small text. — [Gemma 4 summaries via search](https://insiderllm.com/guides/gemma-4-local-ai-guide/)
- **Celebrity / public-figure ID**: Qwen3-VL README says "Broader, higher-quality pretraining is able to 'recognize everything' — celebrities, anime, products, landmarks, flora/fauna". — [Qwen3-VL README](https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/README.md). Max Woolf's July 2025 test found Qwen2.5-VL correctly identified Mark Zuckerberg and Priscilla Chan but sometimes answered "No notable people identified". In the same test, InternVL3.5 "fails to recognize most celebrities, with the 14B version failing to recognize all but two". — [minimaxir.com, Jul 2025 (search extract)](https://minimaxir.com/2025/07/llms-identify-people/). PopVQA benchmark: Qwen2-VL visual accuracy 0.433 (old model). — [alphaxiv PopVQA](https://alphaxiv.org/benchmarks/tel-aviv-university/popvqa)
- **Grounding**: Qwen3-VL "stronger 2D grounding and enables 3D grounding", with boxes and points in relative coordinates. — [Qwen3-VL README](https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/README.md). Molmo 2: SOTA open pointing/grounding in image, multi-image and video, plus video tracking. — [molmo2 README](https://raw.githubusercontent.com/allenai/molmo2/main/README.md)
- **Hallucination**: Qwen3-VL-8B HallusionBench 61.1. — [datalearner](https://www.datalearner.com/en/ai-models/pretrained-models/qwen3-vl-8b-instruct/analysis). MiniCPM-V 4.6 (1.3B) is reported at Qwen3.5-2B level on HallusionBench. — [MiniCPM-V README](https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md). MiniCPM uses RLAIF-V alignment (CVPR 2025) specifically to cut hallucination. — [MiniCPM-V README](https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md)
- Practical: PhotoPrism's Ollama guide recommends temperature 0.01 and repeat penalty 1.2 for Qwen3-VL to reduce hallucinations and loops. It says the 2B/4B variants are "less predictable and consistent" while 8B "generally works well". — [PhotoPrism Ollama models guide](https://d.photoprism.app/user-guide/ai/ollama-models)
- A 2026 paper finds VLMs "ignore visual detail in favor of semantic anchors". That failure mode is directly relevant to fine instance markers such as score text and dates. — [arXiv 2604.02486 (title via search)](https://arxiv.org/pdf/2604.02486)
- **JSON**: Qwen-VL supports JSON output for structured tasks, per Roboflow's workflow block docs. — [Roboflow Qwen-VL block](https://docs.roboflow.com/workflows/blocks/blocks/run-a-model/qwen-vl)

### Inferences
- For the ESTA "right person / right scoreboard / right venue / right date" check, the strongest open choice is a Qwen 3.5+/3.6/3.8 model. It is trained for celebrity recognition and leads on OCR. Claude may refuse face-based identification, so for the "right person" marker an open Qwen model may actually be more useful than Claude. Verify this locally, because recognition of less-famous people (athletes, local figures) is unknown.
- Strict JSON is best enforced at the serving layer (vLLM/llama.cpp/Ollama grammar- or schema-constrained decoding) rather than relying on model compliance. That is standard practice, but I found no source benchmarking JSON adherence for VLMs specifically.
- "Default to mismatch when unsure" calibration is not measured by any public benchmark. Expect small open models to over-claim matches (sycophancy toward the description in the prompt). A labelled eval set of clips from ESTA sessions is the only reliable way to measure it.

### Gaps
- No 2026 systematic public-figure-ID benchmark across Qwen3.5+/Gemma 4/Kimi K2.5 vs Claude/GPT/Gemini.
- No primary source fetched for Claude's face-identification policy (blocked). It is stated here from general knowledge and should be verified.
- No POPE / HallusionBench numbers for Qwen3.6/3.8 or Gemma 4 against frontier models.
- No JSON-schema adherence benchmark for VLMs.

## 4. Native video input (frame sampling, temporal grounding)

### Takeaway
Native video is standard in open models and arguably more flexible than Claude, which takes frames as images only. Qwen3-VL/3.5+ accepts an mp4 or a frame list directly, with configurable fps (default 2) or num_frames, timestamp-aligned positional encoding and second-level event localization. Molmo 2 and MiniCPM-V 4.5/4.6 are also strong at video.

### Cited Findings
- Qwen3-VL: native 256K context (expandable to 1M), "hours-long video with full recall and second-level indexing". Interleaved-MRoPE and "Text–Timestamp Alignment ... precise, timestamp-grounded event localization". Video input accepts a URL, local mp4 or list of frames with `sample_fps`. Default fps is 2, settable via `fps` or `num_frames` (e.g. 128). The token budget is controlled via `total_pixels` (recommended < 24576*32*32). — [Qwen3-VL README](https://raw.githubusercontent.com/QwenLM/Qwen3-VL/main/README.md)
- Qwen3.6-27B: Video-MME (w/ subtitles) 87.7, VideoMMMU 84.4. — [Qwen3.6-27B card via search](https://huggingface.co/Qwen/Qwen3.6-27B)
- Kimi K2.5 VideoMMMU 86.6 vs Claude Opus 4.5 84.4. — [aicybr](https://aicybr.com/blog/kimi-k2-5-guide)
- MiniCPM-V 4.5: "state-of-the-art high-FPS (up to 10FPS) video understanding" on Video-MME, LVBench, MLVU, MotionBench, FavorBench. — [MiniCPM-V 4.5 paper via search](https://arxiv.org/pdf/2509.18154). MiniCPM-V 4.6 defaults to `max_num_frames` 128, and its sample prompt asks the model to "focus on on-screen text, interface changes, main actions, and scene changes". — [MiniCPM-V README](https://raw.githubusercontent.com/OpenBMB/MiniCPM-V/main/README.md)
- Molmo 2: long-context SFT with 384 frames, video pointing and tracking, and evaluated on MVBench, TOMATO, MotionBench, TempCompass, Video-MME, LVBench, MLVU. — [molmo2 README](https://raw.githubusercontent.com/allenai/molmo2/main/README.md)
- Qwen3-Omni-30B-A3B (Sep 2025) handles audio inside video (`use_audio_in_video`) and has cookbooks for video description and scene transitions. — [Qwen3-Omni README](https://raw.githubusercontent.com/QwenLM/Qwen3-Omni/main/README.md)
- Gemma 4 handles video as frames. — [Wikipedia/Gemma summary via search](https://en.wikipedia.org/wiki/Gemma_(language_model))
- Video-MME-v2 (Apr 2026) is a much harder benchmark. Qwen3.5-9B-Think scored 23.2/13.7 and 4B-Think 20.7/11.6 on its two headline metrics, so short-clip benchmark saturation overstates real video understanding. — [Video-MME-v2 arXiv 2604.05015 via search](https://arxiv.org/pdf/2604.05015)

### Inferences
- For ESTA (b) style analysis and (c) short-clip judgement, Qwen 3.5+/3.6/3.8 with fps=1–2 over a 5–15 s clip fits comfortably in a 24 GB budget at a reduced pixel budget. MiniCPM-V 4.5/o 4.5 is the fallback for 8–12 GB GPUs. Shot-type and colour-grade description is easier than instance verification, so open models should be closer to Claude on (b) than on (a).

### Gaps
- No frontier closed-model numbers on Video-MME-v2 for comparison.
- No published measure of VRAM/latency for video at given fps on consumer GPUs from primary sources (see sibling note `running_free_hardware.md`).

## 5. Licenses and commercial use

### Takeaway
The leading open choices are permissive. Qwen3.5/3.6/3.8 (Apache 2.0), Gemma 4 (Apache 2.0, a change from Gemma 3's custom terms), GLM-5.3-Flash (MIT), InternVL (MIT repo), Ovis (Apache 2.0) and Molmo 2 (Apache-style Ai2 release) all allow commercial use of outputs. Older restricted options are Llama 4 (Llama community license) and DeepSeek-VL2 (custom model license, commercial allowed). None of these licenses restricts using model output about YouTube content. Rights to the YouTube footage itself are a separate copyright/ToS question that the model license does not touch.

### Cited Findings
- Qwen3.8-27B: Apache 2.0. — [DataNorth](https://datanorth.ai/news/alibaba-releases-qwen3-8-27b). The Qwen3.5 repo defers to "the license file released with the model weights". — [Qwen3.5 README](https://raw.githubusercontent.com/QwenLM/Qwen3.5/main/README.md)
- Gemma 4: Apache 2.0, "a significant change from previous versions". — [Gemma 4 summaries via search](https://rits.shanghai.nyu.edu/ai/google-releases-gemma-4-frontier-open-models-under-apache-2-0/)
- GLM-5.3-Flash: MIT. — [Eigent](https://www.eigent.ai/blog/glm-5-3-flash-multimodal-model)
- InternVL: "released under the MIT license. Parts ... subject to their respective licenses". — [InternVL README](https://raw.githubusercontent.com/OpenGVLab/InternVL/main/README.md)
- Ovis: Apache 2.0. — [Ovis README](https://raw.githubusercontent.com/AIDC-AI/Ovis/main/README.md)
- DeepSeek-VL2: MIT code, DeepSeek Model License weights, "supports commercial use". — [DeepSeek-VL2 README](https://raw.githubusercontent.com/deepseek-ai/DeepSeek-VL2/main/README.md)
- Molmo 2 repo license badge points to Apache-2.0-style OLMo licensing. Some training datasets have their own agreements. — [molmo2 README](https://raw.githubusercontent.com/allenai/molmo2/main/README.md)

### Gaps
- Kimi K2.5 license terms: it is reported as open weights, but I did not verify whether it uses a modified-MIT license with an attribution clause, as earlier Kimi K2 did.
- MiniCPM model-weight license terms were not checked; earlier versions required registration for commercial use.
- Llama 4 license specifics were not re-checked.

## 6. Community reports comparing small open VLMs with Claude for image-judging

### Takeaway
Community consensus in 2026 is that Qwen 3.5/3.6 (27B dense, 35B-A3B) is the best local vision model, with Gemma 4 26B-A4B as the fast alternative. Direct, rigorous comparisons to Claude on image-judging tasks are scarce. What exists points to small models (2–4B) being inconsistent, with 8–9B workable and 27B the first tier people describe as close to cloud models.

### Cited Findings
- "Qwen 3.5 is the most broadly recommended family right now across use cases, while Gemma 4 has strong recent buzz for local usability." Gemma 4 26B-A4B is called "the fast multimodal pick" (3.8B active, ~18 GB at Q4). — [tinyweights.dev / localclaw summaries via search](https://tinyweights.dev/posts/best-local-vision-language-models-2026/); [localclaw.io](https://localclaw.io/use-case/vision.html)
- A June 2026 community "Best local model for vision" benchmark update exists. Its content was blocked and is unverified. — [prismix.dev](https://prismix.dev/news/ec6b5490ed7e)
- Qwen3-VL small variants (2B/4B) are "less predictable and consistent", while 8B "generally works well". — [PhotoPrism](https://d.photoprism.app/user-guide/ai/ollama-models)
- A hands-on Qwen3-VL review found it identified architectural styles, human subjects, lighting and seasonal details well. — [Stark Insider, Oct 2025](https://cloud.starkinsider.com/2025/10/qwen3-vl-vision-ai-model-review-test-results.html)
- Gemma 4 users reported OCR loops and failures at low vision-token budgets. — [insiderllm](https://insiderllm.com/guides/gemma-4-local-ai-guide/)

### Inferences
- Honest assessment of where open models fall short of Claude for ESTA's task (a):
  1. Calibrated refusal to match when evidence is ambiguous. Small models tend to agree with the prompt.
  2. Long, nuanced reasoning over many weak cues (venue plus date plus kit colours) in one judgement.
  3. Consistency across runs.
  4. The open-ended quality gap visible on LMArena despite benchmark parity.

  Open models are equal or better on raw OCR of scoreboards and text, grounding, native video ingestion and celebrity recognition.
- Practical recommendation for the report writer:
  - Qwen3.8-27B or Qwen3.6-27B (Q4 on 24 GB) as the "closest to Claude" single-GPU pick.
  - Qwen3.6-35B-A3B or Gemma 4 26B-A4B for speed.
  - Qwen3.5-9B or MiniCPM-o 4.5 for 8–12 GB GPUs.
  - Use schema-constrained decoding and temperature ~0. Ask for evidence fields (OCR'd text, recognised person, venue cues) before the verdict, and validate on a labelled set of ESTA clips.

### Gaps
- I found no r/LocalLLaMA thread or GitHub issue directly benchmarking Qwen/Gemma against Claude on yes/no shot-matching with confidence. Reddit was not reachable directly; only search snippets were available.
- No data on how quantization (Q4 vs FP16) affects VLM judgement accuracy for these specific models.
