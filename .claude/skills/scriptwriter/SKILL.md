---
name: scriptwriter
description: Writes a video script. Two modes. AUTHOR (default) — reads requirements.json, research.json, profile/preferences.md; calculates word-count targets, generates talking points, drafts the full script in [HOOK]/[BODY]/[CTA] format, runs the humanizer, then has the user inject their voice and paste back. ARRANGER (found-audio flows) — when audio_pool.json exists, instead of writing prose it selects and sequences real clips from the pool into the arc, producing script.md + arrangement.json (the spec audio:assemble stitches). Invoke after research.json exists. Refuses if skip_scriptwriter is true.
---

# Scriptwriter Skill

You co-write a video script with the user. Two passes: talking points first (so the shape is agreed on), then the full script. On the final pass, the user always owns the voice — AI writing alone is never the canonical script. The user paste-backs their humanized version after seeing your draft, and that's what gets saved.

## Preflight

1. Read `profile/preferences.md` if it exists. Adapt your tone.
2. Read `sessions/<session-id>/requirements.json`. If `skip_scriptwriter` is true, refuse politely: *"Looks like you uploaded your script already in requirements. If you want to redo it, just say so and we restart from requirements."* Stop.
3. Read `sessions/<session-id>/research.json`. If it doesn't exist, tell the user to run research first.
3b. **Mode check.** If `sessions/<session-id>/audio_pool.json` exists (a found-audio flow — audio `found-fetch` already ran), switch to **Arranger mode** (see the dedicated section near the end) and skip the word-count target, voice-profile step, and Phases A/B entirely. Otherwise continue in **author mode** (the default — everything below through "Save + hand off (author mode)").
4. Read `sessions/<session-id>/voice_profile.md` if it exists. This is the canonical list of the user's writing techniques — you will apply each by name during generation. If it does NOT exist AND `requirements.example_scripts` is a non-empty list, invoke the `voice-profiler` skill first to produce it, then continue. (If `example_scripts` is the sentinel and no profile exists, proceed without — but note the gap to the user when announcing what you'll do.)
5. Append every conversational turn to `sessions/<session-id>/conversation.jsonl` with `{"ts": <datetime.now().isoformat()>, "role": ..., "text": ...}` — actual current timestamp, never a placeholder.
6. Read `config.yaml`. If `llm_provider` is anything other than `claude`, invoke `tools/llm/router.py`. For `claude` (the default), do the generation in-conversation following the prompt templates documented in `tools/scriptwriter/prompts.py`.

## Word-count target

Apply the rules from `tools/scriptwriter/word_count.py`: speaking rate **150 wpm**, **Hook = 30 words (~12s)**, **CTA = 30 words (~12s)**, Body = total minus 60. For a range like "2-3 minutes", average to 2.5 minutes → 375 total / 30 hook / 315 body / 30 cta.

Mention the total briefly to the user — "Targeting ~375 words for 2-3 minutes" — don't dump the full breakdown.

## Phase A: Talking points

Default flow — ask first:

> "Got talking points in mind for this, or want me to pull them from the research?"

Parse the user's natural answer:
- "you do it" / "from research" / silence → Claude generates.
- "yeah I've got…" / "let me list them" → user provides, take what they give.
- "skip the points, just write it" → fall through to Phase B without showing talking points (Claude still internally synthesizes them, just doesn't display).

### When Claude generates talking points

Use the talking-points prompt from `prompts.py`. **Pass the full requirements context** — topic, style, duration, comments, example_scripts — plus the research summary. The talking points themselves should feel like they'd be made by the user's voice (from example_scripts), not neutral facts to be styled later.

Generate 3–5 points, 1–2 sentences each. Each builds logically on the previous.

### No style examples? Pause and offer.

If `requirements.example_scripts` is the sentinel `"ASSET_COLLECTOR_PLACEHOLDER"`, do NOT plow ahead. Say:

> "Heads up — no style examples yet, so I don't have a hard voice anchor. I can write off your style + comments + topic alone, but it'll lean on my read of the genre, not your actual voice. Want to drop a sample now to lock it tighter, or proceed without?"

Parse the reply:
- **Drop a sample** → ingest the script, append `{"text": ..., "length": ..., "source": "user_paste"}` to `requirements.example_scripts`, update `requirements.json` in place with the Edit tool, then proceed.
- **Proceed without** → continue. `profile/preferences.md` becomes the only voice signal — lean on it more.
- **Wait for asset-collector** → asset-collector skill not built yet, so respond: *"asset-collector skill not built yet — paused here. Drop a sample any time and I'll resume."* (When asset-collector ships, this branch changes to auto-invoke it.)

### Show talking points + approve/regen/edit

Display the points in plain language. Then:

> "Want me to draft the full script from this, or are we tweaking the points first?"

Parse:
- **Tweak** ("add a 4th about X", "drop point 2", "rephrase the first one") → adjust inline, re-show. Set `user_edited_talking_points: true` in metadata.
- **Regen** ("try again", "different angle") → regenerate with the variety instruction (attempt counter increments). Re-show. Bump `talking_points_regens`.
- **Green light** (silence, "go", "yeah do it") → proceed to Phase B.
- **User pastes their own list** ("actually here's mine: 1...") → take it verbatim, set `user_edited_talking_points: true`, proceed.

## Phase B: Full script

Use the script prompt from `prompts.py`. Pass all context: full requirements (incl. example_scripts), the final approved talking points, the research findings, the profile notes, **and the voice_profile.md if it exists**.

### Plan technique application BEFORE drafting

If `voice_profile.md` exists, do an explicit micro-planning step before writing — list each named signature move from the profile and plan **where each will appear** in the script (which talking point, which beat). Example:

```
TECHNIQUE PLAN:
- Subject-POV with SIKE undercut → applied to talking point 1 (Eduardo injury moment)
- Direct second-person to Arsenal → woven throughout body; concentrated in points 2 and 3
- Question + one-word verdict → ending of talking points 2 and 3
- Repetition for incredulity → on the "248 days" stat in point 3
- Negation triplet (earned) → maybe once, on the points-behind stat
- Slang verdict close → at the end of each section + the CTA
```

Without this planning step, Claude grabs surface features (caps, slang) and skips the techniques. The plan forces deliberate placement of each move.

Then generate following the strict `[HOOK]` / `[BODY]` / `[CTA]` tag format documented in `prompts.py`. Parse with `tools/scriptwriter/parser.py` to extract sections and word counts.

### Auto-invoke the humanizer

After parsing, do **NOT** show the raw AI draft. Read `.claude/skills/humanizer/SKILL.md` and apply it to the AI draft, passing along the full context (requirements, example_scripts, profile, research). Save:
- The raw AI draft → `metadata.ai_draft`
- The humanizer output → `metadata.humanized_draft`

### Show the humanized draft + the stale-AI disclaimer

Show the humanized script in `[HOOK]` / `[BODY]` / `[CTA]` form with section word counts. Then explicitly:

> "Here it is. AI writing — even after the humanizer pass — still tends to land flat. Inject your real voice into it: the weird sidetracks, the inside jokes, the bits only you would say. Paste your finalized version back here (or drop a file path) and I'll lock that in as the script."

Parse the user's reply:
- **User pastes / links a finalized version** → take it as the canonical script. Set `user_finalized: true`. Move to handoff.
- **Regen** ("try again", "the hook needs more bite", "different angle") → loop back to the start of Phase B. Regenerate AI draft with variety instruction (increment `script_regens`). Re-run humanizer. Re-show.
- **Targeted edit** ("change the hook to X", "the second paragraph should mention Y") → apply the edit to the humanized draft in place, re-show, ask again for paste-back. Don't save script.md until user finalizes or explicitly skips.
- **Use as-is / skip humanization** ("just use what you wrote", "it's fine") → **warn once**: *"Heads up, this will sound AI-y to your audience. Saving the humanized version as-is."* Then save. Set `user_skipped_humanization: true`.

## Save + hand off (author mode)

1. Write `sessions/<session-id>/script.md` with the FINAL script — the user-pasted version, OR the humanized fallback if user explicitly skipped humanization. Plain text, preserve `[HOOK]` / `[BODY]` / `[CTA]` tags so downstream skills can parse sections.
2. Write `sessions/<session-id>/script_metadata.json` matching the `ScriptMetadata` schema in `tools/scriptwriter/schema.py`. Include `ai_draft`, `humanized_draft`, final word counts, regen counts, talking points, `research_sources` actually referenced from research.json, example_scripts count, llm_provider.
3. Show a concise summary in plain language: *"Script saved. 378 words (target 375). Took 2 regens. Three sources from research are reflected."*
4. Announce next step + offer the pause:
   > "On to audio next — anything to revisit on the script first?"

   On green-light, invoke the `audio` skill (clone / self-record).
5. Read the user's reply per the pipeline rules in `CLAUDE.md` (tweak / redirect / green-light).

## Arranger mode (found-audio flows)

Use this **instead of** Phases A/B when `audio_pool.json` exists — the narration is built from found audio (the `found-audio-collage` flow), so you don't write prose; you **select and sequence** real clips from the pool into the arc. No humanizer pass (there's no authored prose to de-AI).

### Preflight (arranger)
- Require `sessions/<id>/audio_pool.json` AND `audio_pool_analysis.json`. If the pool is missing: *"No audio pool yet — run audio `found-fetch` first."* If the pool exists but isn't analyzed: *"Pool isn't analyzed yet — run audio `analyze-pool` first."* Stop.
- Read `requirements.json` + `research.json` for the arc/brief (e.g. the emotional arc in `comments`). No 150-wpm word target — the time budget is filled by clip durations, music, and silence.

### Process
1. Read the **enriched** pool. Speech clips now carry `transcript`, `cues` ([{start,end,text}]) and (where whispered) word-level `words`; music/sfx are flagged `has_speech:false`. Group by `kind` (voice / clip / music / sfx / ambience).
2. Lay the arc across `[HOOK]/[BODY]/[CTA]` from the brief.
3. For each beat, pick clips by **actual content**, not titles — read the transcripts to find the line you want (e.g. a clip whose transcript contains "I'm God's lonely man"). Sequence them: which spoken line lands, what SFX/ambience sits under it, where a music bed runs.
4. **Set in/out from the timing, not by guessing:** for a spoken line, find the phrase in the clip's `words`/`cues` and set `in_point`/`out_point` to those timestamps (exact cut). For music/ambience/sfx, any window works — pick a clean stretch.
5. Prefer real pool clips. If a beat has no fitting clip (no transcript matches the line you need), **note the gap and offer to re-fetch** (`audio found-fetch` with new short-keyword queries) rather than inventing a line.

### Output — two files
- **`script.md`** — human-readable, `[HOOK]/[BODY]/[CTA]` tags, each clip a line: what's heard + source + the beat it serves. This is what `plan` reads and the user reviews.
- **`arrangement.json`** — the machine spec `audio:assemble` stitches. Match the `Arrangement` schema in `tools/scriptwriter/schema.py`: ordered `clips`, each with `order`, `beat`, `layer` (spine/bed), `pool_id` (`<source>:<id>`, keys into `audio_pool.json`), `file`, `in_point`/`out_point`, `gain_db`, `role`, `transcript`, `note`. Then validate: `python tools/scriptwriter/arrange.py validate --session sessions/<id>` — fix any errors before handoff.
- Also write `script_metadata.json` (set `llm_provider`, `research_sources`; word-count fields may be 0 for found-audio).

### Review + hand off
Show the arrangement — the spine as a numbered list, plus any bed. Read the reply per CLAUDE.md:
- **Tweak** ("use a different rain", "swap clip 3", "reorder") → edit `arrangement.json` + `script.md`, re-validate, re-show.
- **Gap** ("nothing fits the turn") → re-run `audio found-fetch` with tighter queries, then re-arrange.
- **Green light** → invoke the audio `assemble` mode (`run.py assemble --session sessions/<id>`), which stitches the arrangement into `audio.wav`. Then `timestamps` runs on that assembled audio (its physics + a caption track of the stitched clips).

## Code references

You do NOT need to read these files at runtime — the rules above are the contract. They exist for downstream skills to import:

- `tools/scriptwriter/word_count.py` — `calculate_target_word_count(duration_range)`.
- `tools/scriptwriter/prompts.py` — `TALKING_POINTS_PROMPT_TEMPLATE`, `SCRIPT_PROMPT_TEMPLATE`, `build_example_scripts_section(example_scripts)`, `build_variety_instruction(attempt)`. Source of truth for prompt content; `router.py` uses these for external providers.
- `tools/scriptwriter/parser.py` — `parse_script(raw)` → `{hook, body, cta, full, hook_words, body_words, cta_words, total_words}`.
- `tools/scriptwriter/schema.py` — `ScriptMetadata` TypedDict + `default_script_metadata(session_id)`; also `Arrangement` / `ArrangementClip` + `default_arrangement(session_id)` for arranger mode.
- `tools/scriptwriter/arrange.py` — `validate_arrangement(session_dir)` + a `validate` CLI; cross-checks `arrangement.json` against `audio_pool.json` (real pool refs, downloaded files, sane in/out). Run it before handing off to audio assemble.
- `tools/llm/router.py` — `generate(task, prompt_vars)`. Returns `CLAUDE_HARNESS_SENTINEL` for claude provider; raises `NotImplementedError` for others until they're wired up.
