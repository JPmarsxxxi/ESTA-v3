# Free ($0) hosted vision-language inference APIs, as of October 2026

Research date: 2026-10-07. Workload assumed: 100-600 image-judging calls per video (1-4 frames each, short JSON reply), a few videos per week. Peak need is about 600 calls in one day, with 300-2,400 calls a week.

**How this was researched:** the sandbox's egress proxy blocked direct fetches of every primary doc page tried: ai.google.dev, openrouter.ai, docs.github.com, console.groq.com, plus the aggregator pages mintlify.com, costgoat.com and tinkerllm.com. Every finding below therefore comes from web-search result snippets, and most of those are third-party aggregators (freellm.net, tokenmix, aifreeapi, benchlm and others), not official docs. Aggregators often copy each other and lag behind the official pages, so **check each number in the provider's console before relying on it.** Each figure says where it came from. Conflicts are flagged.

## Q1. Provider-by-provider: free tier, card requirement, vision models, exact limits

### Takeaway
For this workload, six options are realistic at $0, no card:
- **Gemini Flash-Lite** (~500 RPD on the 3.x Lite models)
- **Groq Llama 4 Scout/Maverick** (~1,000 RPD, if still served)
- **Cerebras Gemma 4 31B** (1M tokens/day, but only 5 RPM)
- **OpenRouter Gemma 4 `:free`** (only 50 RPD unless a one-time $10 is paid)
- **GitHub Models** (GPT-4.1 at 50 RPD; mini/low tier at about 150 RPD)
- **Zhipu GLM-4.6V-Flash** (free, 1 concurrent request)

Stacking two or three of these covers 600 calls a day. Gemini Flash (non-Lite) at 20 RPD is useless at this volume.

### Summary table (all limits as reported Jun-Oct 2026 by the sources cited below; verify in console)

| Provider | Card needed? | Vision models on free tier | Reported free limits | Fits 600 calls/day? | Confidence |
|---|---|---|---|---|---|
| Google AI Studio / Gemini API | No | Gemini 3.x Flash, 3.x Flash-Lite (also older 2.5/2.0 Flash-Lite), Gemma via API | 3.5/3.1 Flash-Lite: 500 RPD. 3.5-3.8 Flash: ~20 RPD (Sep 2026). Older 2.x Flash-Lite reportedly 30 RPM / 1,500 RPD | Flash-Lite: yes, barely (500). Flash: no | Medium (aggregators + Sep 2026 Google forum thread) |
| OpenRouter `:free` | No | gemma-4-31b-it:free, gemma-4-26b-a4b-it:free, nemotron-3-nano-omni-30b-a3b:free, `openrouter/free` auto-router (image-aware). Older lists add qwen2.5-vl-32b/72b:free, mistral-small-3.1:free, kimi-vl-a3b-thinking:free, gemma-3:free, llama-3.2-11b-vision:free (current status unknown) | 20 RPM. 50 RPD with <$10 lifetime credits; 1,000 RPD after a one-time $10 purchase | Only with the $10 purchase, which is not $0 | Medium-high on the rule; low on the current model list |
| GitHub Models | No (GitHub account) | GPT-4.1, GPT-4.1-mini, GPT-4o and others in "high"/"low" tiers | High tier (GPT-4.1): 10 RPM, 50 RPD, 8K in / 4K out tokens per request. Mini tier: 15 RPM, 150 RPD. Limits scale with Copilot plan | No alone (50-150 RPD); useful as a top-up | Medium |
| Groq | No | Llama 4 Scout 17B-16E, Llama 4 Maverick 17B-128E (up to 5 images per request, JSON mode) | Scout free: 30 RPM, 30K TPM, 1,000 RPD (Jul 2026 aggregator) | Yes, if Scout is still served | Medium; current model availability unverified |
| Cerebras | No | gemma-4-31b (max 2 images per request, 4 MB payload) | 5 RPM, 30K TPM, 1M tokens/day, plus $5 credits | Yes on tokens, but 600 calls at 5 RPM takes about 2 hours | Medium |
| NVIDIA build.nvidia.com (NIM) | No (NVIDIA Developer Program, email) | Qwen3-VL (2B to 235B listed), Llama 4 Maverick, Llama 3.2 11B Vision, Phi-3 Vision | 40 RPM. Sources conflict: "~1,000 inference credits" (roughly one per call) vs "no daily cap" | Unclear: one-time credits would last 1-2 videos | Low (conflicting) |
| Zhipu / Z.ai (BigModel) | No | GLM-4.6V-Flash (9B, 128K, switchable reasoning) | Free; 1 concurrent request; endpoint api.z.ai/api/paas/v4 | Probably yes, run serially | Medium |
| Mistral La Plateforme "Experiment" | No card; phone (SMS) verification | Pixtral Large, Mistral Small/Medium (vision-capable) | Sources conflict: "~1 req/s" vs "2 RPM, 500K TPM, 1B tokens/month". Mistral no longer publishes the numbers (see Admin Console > Limits) | 1 RPS: yes. 2 RPM: no (5 hours) | Low |
| Cloudflare Workers AI | No | Llama 4 Scout, Gemma 3 12B, Mistral Small 3.1 24B, Llama 3.2 11B Vision, LLaVA 1.5 7B | 10,000 neurons/day shared across all models | Unknown: depends on neurons per image call | Medium on the allowance; neuron cost per call unknown |
| Hugging Face Inference Providers | No | Whatever the routed providers serve (Qwen-VL and others) | $0.10/month credits for free users ($2 for PRO) | No: too small | High |
| Cohere trial key | No | Aya Vision 32B | 1,000 calls/month across all endpoints; 20 RPM reported for Aya Vision; "not for production" | No (1,000/month) | Medium |
| Chutes | n/a | n/a | Free tier ended (killed Feb 2026; listed as ended by 2026-09-30); cheapest is a $3/month plan | No | Medium |
| Alibaba Model Studio (DashScope intl) | Alibaba Cloud account (card typical, unverified) | Qwen3-VL family | One-time 1M tokens per model, 90 days, Singapore region only (none on US-Virginia) | Short-term only: ~1M tokens is roughly 1-3 videos | High (official help page in search results) |
| SiliconFlow | No card, but real-name ID verification (since 2026-05-15) | Free list reported as small models (e.g. Qwen3-8B); free VL model not confirmed | 1,000 RPM, 50K TPM on free models | Impractical outside China (ID check) | Low-medium |
| SambaNova Cloud | No | Lists Llama 4 Maverick and Gemma 3; whether vision is on free tier is unclear | 200K tokens/day | Maybe 1 video/day if vision works | Low |
| Together AI | Unclear | meta-llama/Llama-Vision-Free (Llama 3.2 11B) historically | Not found | Unknown | Low |
| Ollama Cloud | No | qwen3-vl:235b on cloud (marked "retiring", replaced by qwen3.5) | Free plan: 1 concurrent request, "starter amount of usage credits" (amount not found) | Unknown | Low |

### Cited Findings

**Google Gemini API**
- Gemini 3.5 Flash-Lite and 3.1 Flash-Lite: 500 RPD free. Gemini 2.0 Flash-Lite: 30 RPM, 1M TPM, 1,500 RPD. 2.5 Flash-Lite: 30 RPM, 1,500 RPD — [scriptbyai](https://www.scriptbyai.com/gemini-api-free-tier-limits/), [aipromptshub](https://aipromptshub.co/blog/gemini-api-free-tier-rate-limits), [tokenmix](https://tokenmix.ai/blog/gemini-api-free-tier-limits). The 2.x figures may be stale or for retired models.
- A Sep 2026 Google AI Developers Forum thread, "Gemini 3.8 Flash Free Tier 20 RPD Is Too Limited for Practical Evaluation", confirms Flash is at 20 RPD and contrasts it with Flash-Lite's 500 RPD. Snippets say 3.5/3.6/3.7/3.8 Flash all get about 20 free RPD — [Google AI Developers Forum](https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609), [eesel 3.8 Flash pricing](https://www.eesel.ai/blog/gemini-3-8-flash-pricing).
- Conflict: some trackers still list gemini-3-flash-preview at 10 RPM / 250K TPM / 1,500 RPD — [pecollective](https://pecollective.com/tools/gemini-free-tier-guide/), [GitHub issue digithings #5027](https://github.com/digithings-ai/digithings/issues/5027). Treat 1,500 RPD for Flash as stale or preview-only.
- Every current Flash and Flash-Lite model is reported to have a free tier — [aifreeapi](https://www.aifreeapi.com/en/posts/google-gemini-api-free-tier).
- No exact free-tier numbers for Gemma via the Gemini API were found in the snippets (see Gaps).

**OpenRouter**
- The `:free` rule: 20 RPM. 50 RPD if lifetime purchased credits are under $10; 1,000 RPD once at least $10 has ever been bought (a one-time threshold). No card is needed for the key or for 50 RPD — [klymentiev](https://klymentiev.com/blog/openrouter-free-tier), [benchlm](https://benchlm.ai/free-tier/openrouter), [fast.io](https://fast.io/resources/openrouter-rate-limit/).
- Conflict: one aggregator says "typically 20 RPM, 200 RPD" — [buldrr](https://buldrr.com/openrouter-free-api-keys-free-models-simple-guide/). The 50/1,000 rule appears in more sources.
- Free vision models listed in 2026: google/gemma-4-31b-it:free (text+image, 262K), google/gemma-4-26b-a4b-it:free (text+image+short video), nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free. The `openrouter/free` router picks a free model at random, filtered for image support — [OpenRouter free router](https://openrouter.ai/openrouter/free), [OpenRouter free collection](https://openrouter.ai/collections/free-models), [costgoat Oct 2026](https://costgoat.com/pricing/openrouter-free-models).
- Free model count: 25 on 2026-07-01, 24 on 2026-09-21 — [rubentorney](https://rubentorney.com/blog/en/openrouter-modeles-gratuits-2026.html).
- Older free vision variants: qwen2.5-vl-32b/72b:free, mistral-small-3.1-24b:free, kimi-vl-a3b-thinking:free, gemma-3-4b/12b/27b:free, llama-3.2-11b-vision:free — [Medium, csv610](https://medium.com/@csv610/exploring-openrouter-free-vision-models-5373c94b00e1). Whether these are still live in Oct 2026 is unverified.
- No current `qwen3-vl:free` was found.

**GitHub Models**
- GPT-4.1 on the free tier: 10 RPM, 50 RPD, 8K input / 4K output tokens per request. Mini tier (GPT-4.1-mini): 15 RPM, 150 RPD. Limits depend on the Copilot plan — [freellm.net gpt-4.1](https://freellm.net/models/github-models/gpt-4-1), [mintlify cheahjs mirror](https://www.mintlify.com/cheahjs/free-llm-api-resources/providers/free/github-models), [GitHub community discussion #137298](https://github.com/orgs/community/discussions/137298).

**Groq**
- Free plan, Llama 4 Scout: 30 RPM, 30K TPM, 1,000 RPD, 128K context, no card — [rapidevelopers Jul 2026](https://www.rapidevelopers.com/md/ai-api-limits-performance-matrix/llama-4-scout), [eesel Groq pricing](https://eesel.ai/blog/groq-pricing).
- Llama 4 Scout and Maverick on Groq support up to 5 image inputs per request, JSON mode and tool use — [releases.sh](https://releases.sh/release/rel_9pZUmudpM5N-Hno7_IlTc-llama-4-scout-and-maverick-models-now-available), [Groq model page](https://console.groq.com/docs/model/llama-4-maverick-17b-128e-instruct).

**Cerebras**
- The free trial lists gpt-oss-120b, zai-glm-4.7 and gemma-4-31b. gemma-4-31b accepts up to 2 images per request in a 4 MB payload. Limits: 5 RPM, 30K TPM, 1M tokens/day, plus $5 credits — [benchlm cerebras](https://benchlm.ai/md/free-tier/cerebras.md), [pricepertoken](https://pricepertoken.com/endpoints/cerebras/free).

**NVIDIA build.nvidia.com**
- Free key via the NVIDIA Developer Program, no card. Sources say "~1,000 inference credits" and a 40 RPM limit. The catalog includes Qwen3-VL and Llama 4 Maverick — [sidsaladi substack](https://sidsaladi.substack.com/p/free-llm-api-nvidia-nim), [yangmao](https://yangmao.ai/en/providers/nvidia-build/), [NVIDIA live-vlm-webui VLM list](https://github.com/NVIDIA-AI-IOT/live-vlm-webui/blob/main/docs/usage/list-of-vlms.md).
- Conflict: another aggregator says "40 RPM with no daily cap" — [freellm.net vision](https://freellm.net/use-cases/vision), [tokenmix](https://tokenmix.ai/blog/free-llm-api).

**Zhipu / Z.ai**
- GLM-4.6V-Flash is free, has a 1-concurrent-request limit and 128K context, at api.z.ai/api/paas/v4 — [ayautomate](https://www.ayautomate.com/free-models/z-ai-zhipu-ai-glm-4-6v-flash), [freellmapi](https://freellmapi.co/free-glm-api), [VentureBeat](https://venturebeat.com/ai/z-ai-debuts-open-source-glm-4-6v-a-native-tool-calling-vision-model-for).
- The 9B Flash variant is free for commercial use — [aibase](https://news.aibase.com/news/23480).

**Mistral "Experiment" tier**
- No card; phone verification. Access to all models including Pixtral Large. Limits conflict between "~1 req/s, ~1B tokens/month" and "2 RPM, 500K TPM, 1B tokens/month". Mistral no longer publishes the numbers (check Admin Console > Limits) — [pricepertoken](https://pricepertoken.com/endpoints/mistral/free), [agentdeals](https://agentdeals.dev/vendor/mistral-ai), [costbench](https://costbench.com/software/llm-api-providers/mistral-ai/free-plan/), [workshop doc](https://github.com/DrDavidHall/mistral-api-workshop/blob/main/docs/free-tier-experiment-plan.md).

**Cloudflare Workers AI**
- 10,000 neurons/day free, shared across all models. Hosts Llama 4 Scout, Gemma 3 12B, Mistral Small 3.1 24B, Llama 3.2 11B Vision and LLaVA 1.5 — [flaviocopes](https://flaviocopes.com/cloudflare-workers-ai), [freellm.net CF](https://freellm.net/providers/cloudflare-workers-ai), [Cloudflare](https://www.cloudflare.com/product/workers-ai).

**Hugging Face Inference Providers**
- Free users get $0.10/month in credits (PRO users $2) — [HF docs](https://huggingface.co/docs/inference-providers/pricing), [hub-docs pricing.md](https://github.com/huggingface/hub-docs/blob/main/docs/inference-providers/pricing.md).

**Cohere**
- Trial keys are free, capped at 1,000 calls/month across all endpoints, and not allowed for production. Aya Vision 32B is reported at 20 RPM — [Cohere FAQ](https://docs.cohere.com/docs/cohere-faqs), [benchlm cohere](https://benchlm.ai/free-tier/cohere), [freellm.net aya vision](https://freellm.net/models/cohere/aya-vision-32b).

**Chutes**
- The free tier was killed in Feb 2026, citing heavy users extracting "56x to 324x" their value. The cheapest option is now a $3/month plan — [cheahjs issue #217](https://github.com/cheahjs/free-llm-api-resources/issues/217), [ai-deals](https://ai-deals.rockpool.cc/free-tier-chutes), [rpwithai](https://rpwithai.com/chutes-new-subscription-plans/).

**Alibaba Model Studio**
- New users get 1M tokens per model for 90 days, Singapore region only; the US-Virginia region has no free quota — [Alibaba Cloud help](https://www.alibabacloud.com/help/en/model-studio/new-free-quota).

**SiliconFlow**
- Free models: 1,000 RPM, 50K TPM. Real-name identity verification has been required since 2026-05-15 — [freellm.net China ecosystem](https://freellm.net/blog/china-free-llm-ecosystem), [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis).

**SambaNova**
- Free tier: 200K tokens/day, no card. Models include Llama 4 Maverick and Gemma 3. Whether vision is enabled on the free tier is unclear — [costbench](https://costbench.com/software/llm-api-providers/sambanova-cloud/), [freellm.net](https://freellm.net/providers/sambanova).

**Together AI**
- meta-llama/Llama-Vision-Free (Llama 3.2 11B) was historically listed as free — [debuggercafe](https://debuggercafe.com/serverless-inference-with-together-ai/), [comfyonline](https://www.comfyonline.app/comfyui-nodes/Together-Vision-Node). Its current status was not found.

**Ollama Cloud**
- Free tier at $0: 1 concurrent request, a starter amount of usage credits. qwen3-vl:235b is on cloud but marked as retiring (replaced by qwen3.5) — [ollamatps limits](https://ollamatps.com/limits/), [devtoolhub](https://devtoolhub.com/ollama-cloud-free-vs-pro-guide/), [Ollama Qwen3-VL blog](https://ollama.com/blog/qwen3-vl), [Ollama X post](https://x.com/ollama/status/1978225292784062817).

### Inferences
- A practical $0 stack for 600 calls a day:
  - Gemini Flash-Lite: 500 RPD.
  - Groq Llama 4 Scout: 1,000 RPD, if still live.
  - GitHub Models GPT-4.1-mini (150 RPD) and GLM-4.6V-Flash for overflow.
  - Cerebras Gemma 4 31B as a slow but token-rich fallback.
- Groq or Gemini Flash-Lite alone probably covers a single 600-call video. Gemini at 500 is borderline.
- Packing 2-4 frames into one request cuts call counts. Groq allows 5 images per request; Cerebras Gemma 4 allows 2.
- GitHub Models' 8K input-token cap per request may limit 4-frame calls at high detail. The OpenAI-style low-detail mode is cheap per image, but that per-image figure is from memory, not a source here.
- OpenRouter at $0 (50 RPD) is only good for spot checks. The one-time $10 unlocks 1,000 RPD, but that breaks the $0 constraint.

### Gaps
- Primary docs could not be fetched (egress blocked), so no limit here is confirmed against an official page.
- Not found:
  - Exact free-tier RPM/TPM for Gemini 3.x Flash-Lite.
  - Gemma-via-Gemini-API free limits.
  - Whether the limits are per project or per account.
- Whether Groq still serves Llama 4 Scout/Maverick in Oct 2026 (Meta's Llama 4 line may have been deprecated by providers) is unconfirmed.
- NVIDIA NIM: whether free use is one-time credits or ongoing 40 RPM is unresolved.
- Not found:
  - Cloudflare's neuron cost per vision call.
  - Ollama Cloud's free credit amount.
  - SambaNova's free vision availability.
  - Together's current free models.
  - Whether Alibaba needs a card for international sign-up.
- No source confirmed any **free** Qwen3-VL-235B endpoint with a daily quota. NVIDIA (credits) and Ollama Cloud (starter credits, model retiring) come closest.

## Q2. Which free offers host near-frontier vision models, and how stable have they been?

### Takeaway
Near-frontier vision at $0 is mostly two things:
- **Gemini Flash-Lite**, with Flash itself at only 20 RPD.
- **Gemma 4 31B** on OpenRouter `:free` and Cerebras.

Qwen3-VL-235B is free only as starter credits (NVIDIA, Ollama Cloud) or as Alibaba's one-time 1M-token trial. GLM-4.6V-Flash (9B) is free but not frontier. Free tiers have been cut repeatedly: Gemini in Dec 2025, Chutes in Feb 2026, SiliconFlow's ID check in May 2026, and OpenRouter's shrinking free list. Plan for churn.

### Cited Findings
- **Dec 2025 Gemini cut:** Gemini 2.5 Pro was dropped from the free tier, and 2.5 Flash went from ~250 RPD to ~20 RPD (~92%) without notice, causing widespread 429s. 2.5 Flash-Lite was reportedly not cut — [Google AI Developers Forum, "92% free tier quota"](https://discuss.ai.google.dev/t/do-they-really-think-we-wouldnt-notice-a-92-free-tier-quota/111262), [technobezz, 2025-12-20](https://www.technobezz.com/news/google-slashes-free-gemini-api-requests-to-20-per-day-2025-12-20-gl06), [HowToGeek](https://www.howtogeek.com/gemini-slashed-free-api-limits-what-to-use-instead/), [CometAPI](https://www.cometapi.com/is-free-gemini-2-5-pro-api-fried-changes-to-the-free-quota-in-2025/).
- **Flash still at ~20 RPD:** that level carried into the 3.x Flash line through Sep 2026 — [Google forum Sep 2026](https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609).
- **Chutes:** free tier removed in 2026 — [cheahjs issue #217](https://github.com/cheahjs/free-llm-api-resources/issues/217).
- **SiliconFlow:** real-name verification since 2026-05-15 — [freellm.net](https://freellm.net/blog/china-free-llm-ecosystem).
- **OpenRouter:** free model count went from 25 (Jul 2026) to 24 (Sep 2026). Earlier free vision variants (Qwen2.5-VL 72B and others) no longer appear in the 2026 snippets — [rubentorney](https://rubentorney.com/blog/en/openrouter-modeles-gratuits-2026.html), [OpenRouter collection](https://openrouter.ai/collections/free-models).
- **Qwen3-VL-235B listings:**
  - NVIDIA catalog — [NVIDIA live-vlm-webui](https://github.com/NVIDIA-AI-IOT/live-vlm-webui/blob/main/docs/usage/list-of-vlms.md).
  - Ollama Cloud, marked retiring — [ollama.com/library/qwen3-vl](https://ollama.com/library/qwen3-vl).
  - Alibaba's 1M-token trial — [Alibaba Cloud help](https://www.alibabacloud.com/help/en/model-studio/new-free-quota).

### Inferences
- Gemini's free tier is the strongest model quality-wise. It has the best "lite" option and has been cut once already. Flash-Lite survived the Dec 2025 cut, which suggests Google is steering free users to Lite.
- Build the pipeline provider-agnostic (an OpenAI-compatible client plus a fallback chain) so another cut just means moving to the next provider.

### Gaps
- No free GLM-4.5V/4.6V full-size (106B) offer was found, only the 9B Flash.
- No Kimi-VL free endpoint was confirmed beyond an older OpenRouter listing.

## Q3. Privacy / ToS: which free tiers train on your data, and any limits on automated or bulk use?

### Takeaway
- **Gemini free tier:** prompts and outputs can be used to improve Google models, with human review.
- **Mistral Experiment:** uses data for training unless you opt out.
- **Cohere trial keys:** explicitly not for production.
- **OpenRouter `:free`:** routes to upstream providers whose logging varies (not verified here).

For judging stock-footage frames this is likely acceptable, but don't send private or unreleased footage to the free tiers.

### Cited Findings
- **Gemini free tier:** content from unpaid services is used to improve products, including ML models, and human reviewers may annotate inputs and outputs. The paid tier does not train and is covered by the DPA — [bswen, 2026-03-23](https://docs.bswen.com/blog/2026-03-23-gemini-free-tier-data-privacy/), [meetily](https://meetily.ai/llm-privacy/gemini), [kingy.ai](https://kingy.ai/ai-tools/gemini-api/).
- **Google AI Studio terms:** reported changes ban "consumer use" of AI Studio — [remio.ai](https://www.remio.ai/post/new-google-ai-studio-terms-ban-consumer-use-the-developer-pivot). Details are unverified; developer API use appears to be the intended use.
- **Mistral:** data may be used for model improvement unless you opt out — [costbench](https://costbench.com/software/llm-api-providers/mistral-ai/free-plan/), [Mistral help: opt out](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training).
- **Cohere:** trial keys are "rate-limited and explicitly not allowed for production" — [benchlm](https://benchlm.ai/free-tier/cohere), [Cohere FAQ](https://docs.cohere.com/docs/cohere-faqs).
- **SiliconFlow:** requires real-name ID — [freellm.net](https://freellm.net/blog/china-free-llm-ecosystem).

### Inferences
- A personal hobby pipeline running a few hundred calls a day is unlikely to break "no production" clauses in spirit, but Cohere's trial explicitly excludes production use.
- Rotating many accounts or keys to dodge limits would likely breach most ToS (assumption; no specific clause was cited).

### Gaps
- Training/logging terms were not found for:
  - Groq, Cerebras, GitHub Models, NVIDIA build, Cloudflare, Zhipu, Ollama Cloud.
  - OpenRouter free routes, which per-provider may log prompts.

## Q4. Can a Claude Pro/Max subscription be used more efficiently for vision?

### Takeaway
Claude charges image input at roughly width x height / 750 tokens. A 1024x576 frame is about 790 tokens (calculated). Downscaling frames to around 512-768 px on the long edge cuts cost about 4x. Haiku 4.5 is the cheapest Claude vision model ($1/M input tokens on the API). Anthropic does not publish subscription limits in tokens, so how many image checks fit into Pro/Max usage could not be quantified.

### Cited Findings
- Image tokens ≈ width x height / 750. Max native resolution: 1568 px long edge / ~1568 tokens for most models; 2576 px / 4784 tokens for Opus 4.7/4.8 and newer — [Claude vision docs](https://platform.claude.com/docs/en/build-with-claude/vision), [docs.claude.com vision](https://docs.claude.com/en/docs/vision).
- Haiku 4.5 costs $1 per 1M input tokens (Jul 2026) — [intuitionlabs](https://intuitionlabs.ai/articles/claude-pricing-plans-api-costs).

### Inferences
- **API cost at Haiku rates:** 600 calls x 4 frames x ~790 tokens ≈ 1.9M input tokens ≈ $1.90 per video, plus small output. Not $0, but it gives a reference point.
- **Halving cost:** downscaling to 768x432 (~440 tokens/frame) roughly halves it.
- **Using the subscription:** inside Claude Code, a Haiku subagent doing frame checks draws on the Pro/Max allowance rather than the API bill. Batching 4 frames into one message and keeping replies to short JSON is the efficient pattern.
- **Contact sheet:** tiling 4 small frames into one ≤1568 px image costs about the same tokens as one large frame.

### Gaps
- No source found quantifying how images count against Pro/Max session or weekly limits, or whether Haiku usage is weighted lower than Opus/Sonnet in subscription limits.
