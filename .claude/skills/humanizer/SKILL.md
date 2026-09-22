---
name: humanizer
description: Rewrites AI-written text to break AI patterns and lean into the user's voice. Text in, text out — does not save canonical artifacts. Auto-invoked by every generative skill (scriptwriter today; future caption/description/hook skills) before drafts are shown to the user. Can also be invoked standalone — paste any text and say "humanize this".
---

# Humanizer Skill

You take a piece of AI-written text and make it sound less like AI wrote it. You're a preprocessor — your output still goes back to the user for the final pass. Your job is to clean up the obvious AI tells and lean into the user's voice so the user has less work to do.

## What you receive

- The text to humanize — passed in by the calling skill, or pasted by the user in chat.
- Context to read (if available — fall back to text-only if not):
  - **`sessions/<session-id>/voice_profile.md`** — THE primary voice reference if it exists. This is a structured list of the user's named writing techniques (signature rhetorical moves, register, ending patterns, earned-only patterns, active avoid list). When this file is present, your job during rewrite is NOT only to strip AI tells but also to inject the user's named techniques where the AI draft is missing them.
  - `sessions/<session-id>/requirements.json` — `style`, `comments`, and `example_scripts` (the raw voice samples).
  - `profile/preferences.md` — running cross-session notes on the user's tone.
  - `sessions/<session-id>/research.json` — for factual grounding (do not introduce facts that contradict the research).

If invoked standalone with no session context, work from the text alone plus whatever voice cues are visible in it.

## What "humanize" means here, concretely

**Break AI-y rhythm.** AI writes in even sentence lengths and parallel structure. Mix it up — fragments, run-ons, one-liners, callbacks. Drop conjunctions where speech would. Cut the connective tissue: *"Furthermore", "Additionally", "Moreover", "It's worth noting", "What's interesting is"* — those are AI fillers, not speech.

**Strip hedging.** AI hedges constantly: *"perhaps", "tends to", "often", "in many cases", "some might argue"*. Speech commits or cuts. Commit or cut.

**Strip the polished register.** AI defaults to neutral-formal. Match the register of the user's example_scripts and profile. If they say "bruv", "lowkey", "actually insane", "this is mental" — bring that vocabulary in. If they use ALL CAPS for emphasis, do that. If they use sentence fragments for impact, do that.

**Replace generic with specific.** AI says *"a number of things", "various factors", "many people"*. Pick a number. Name the thing. Use the specific example.

**Inject personality markers.** From example_scripts and profile. The user's "SIKE bro" or "absolute shambles" or "they bottled it" — those are voice markers; use them when they fit. Don't force them where they don't.

**Preserve structure.** If the input has `[HOOK]` / `[BODY]` / `[CTA]` tags, keep them exactly. If it's a single paragraph, keep it a single paragraph. Don't change the shape — only the texture.

**Preserve facts.** Don't introduce claims not in the input. Don't drop verified facts. The humanizer is a stylistic pass, not an editorial one.

## AI tells to actively kill

These are named patterns AI defaults to that real writers don't (or use rarely and earned). Hunt for them and rewrite. The meta-rule before the list:

**Earned emphasis only.** A rhythmic pattern from the user's example_scripts is fair game IF you only use it at moments the build-up genuinely justifies. The same pattern applied uniformly across a draft is an AI tell, not a voice match. If you can't point to *why* this exact spot needs the rhetorical move, cut it.

The patterns:

1. **Negation tricolon / cascading negation.** *"Not X. Not Y. Because Z."* — e.g., *"Not because the league was too hard. Not because they lacked talent. Because they CANNOT stop bottling it."* Rewrite as a single direct claim. At most one negation, never a cascade.

2. **Number ladder via negation.** *"Not two wins. Not three. ONE."* — same DNA as #1. Cut the ladder, just state the number with the surrounding context.

3. **Dramatic narration phrases.** *"And that's the moment everything dies", "Then April arrives", "The clock was ticking", "Everything changes"* — AI personifying months/seasons or narrating like a documentary voiceover. Cut or rewrite plain.

4. **Listicle transitions.** *"But wait, it gets worse", "Here's the kicker", "Plot twist", "And then?"* — these are AI's go-to filler between beats. Cut. Move on with the next sentence.

5. **Single-word emphasis endings.** *"Gone."*, *"Again."*, *"Period."*, *"Done."* standing alone. Real writers use these at most once or twice in a piece, only when the build-up earns it. AI sprinkles them every few paragraphs. Cap: one per script, only at a genuine climax point.

6. **Staccato lists for drama.** *"Tibia. Fibula. Ankle dislocated."* AI sprinkles short-sentence lists everywhere for "punch." Only keep if the user's actual example_scripts demonstrate this pattern AND the moment earns it. Otherwise rewrite as a normal sentence.

7. **Em-dashes as a rhythm crutch.** Em-dashes everywhere is the new AI tell. Use commas, periods, or full sentences instead.

When you make a pass, explicitly check for each of these and rewrite. They are not exhaustive — but they are the highest-signal patterns the user has flagged as immediate giveaways.

## How to apply: scan → rewrite → audit

Apply the rules through an explicit three-stage process inside your single response. All three stages happen in one turn — they are internal scratch work, not separate calls. Without this structure, rules get skipped when Claude tries to juggle them all at once.

### Stage 1 — Scan the input

Before rewriting anything, scan the input draft for two things:

**(a) AI tells present** — which named patterns from "AI tells to actively kill" appear. List each with the count and/or the exact phrase.

**(b) User voice techniques ABSENT** — if `voice_profile.md` exists, list which of the user's named signature rhetorical moves are missing from the draft. This is what makes the rewrite a voice-injection pass, not just an AI-tell-removal pass.

Example:

```
SCAN:
AI tells present:
- Negation tricolon: 2 instances — "Not because the league was too hard..." / "Not in 2008..."
- Number ladder: 1 — "Not two wins. Not three. ONE."
- Dramatic narration: 1 — "Then April arrives."
- Single-word endings: 5 instances
- Em-dash crutch: 12 instances

User techniques absent (from voice_profile.md):
- Subject-POV with SIKE undercut: 0 instances — profile says use 1-2x at climax moments
- Direct second-person to Arsenal: weak — only 2 instances, profile says concentrate in points 2 and 3
- Question + one-word verdict: 0 — profile says use 1-2x as ending pattern
- Slang verdict close: missing — endings are "Go figure." / "It didn't matter." instead of "Embarrassing." / "Shambles."
```

If `voice_profile.md` does NOT exist, omit section (b) and operate on (a) only.

If a pattern is absent under (a), omit it. The scan exists to make you *see* the gaps before rewriting — Claude with an explicit list in front of it fixes them more reliably than Claude trying to remember all rules at once.

### Stage 2 — Rewrite

Now humanize the text. Two parallel jobs:
- **Remove** every AI tell flagged in scan (a).
- **Inject** every user voice technique flagged absent in scan (b) — at moments the text earns it (climax for SIKE undercut, ending of sections for slang verdicts, the most damning stat for repetition-for-incredulity, etc.). Use the user's actual quoted examples from `voice_profile.md` as the texture reference.

The general rules (rhythm, hedging, register, structure preservation, facts preservation) apply alongside.

### Stage 3 — Audit the output

Re-scan the rewritten text. Check both:
- **AI tells removed?** Re-scan for the named patterns. Surgical-fix anything still present.
- **User techniques injected?** If `voice_profile.md` exists, verify each signature move that was flagged absent in Stage 1 is now present (at an earned moment). If any are still missing, surgical-inject them now.

Allow earned exceptions (e.g., one single-word ending kept at a real climax). Do not rewrite passages that are already clean. One audit round only — no infinite loops. Write a short audit summary:

```
AUDIT:
- AI tells: all cleared except one kept "Gone." at the end of section 2 (climax, earned).
- User techniques: SIKE undercut injected at the Eduardo moment; direct-second-person concentrated in points 2 and 3 as planned; slang verdict closes added to all section endings. All voice profile moves now present.
```

Then make the surgical fixes.

## What NOT to do

- Don't add jokes that weren't there. The user will do that — you're prepping the soil.
- Don't change argument or conclusions.
- Don't make it longer. Match the input length within ~10%.
- Don't go overboard on slang — match the example_scripts' register, don't exceed it.
- Don't sprinkle em-dashes everywhere — that's the new AI tell.

## Output

The response has three parts, in this order:

1. **SCAN block** — visible. Lists the AI tells found in the input (from Stage 1). This is the user-visible record that no rules were skipped during this pass.
2. **AUDIT block** — visible. Confirms the output is clean, or notes any residual tells that were kept intentionally (earned emphasis) and any surgical fixes made in Stage 3.
3. **The humanized text** — the actual rewritten content. If the input had `[HOOK]` / `[BODY]` / `[CTA]` tags, preserve them exactly.

When the calling skill consumes the output (e.g., scriptwriter), only the humanized text is stored in `metadata.humanized_draft`. The SCAN and AUDIT blocks are conversational records — not artifact content.

When invoked standalone (user pasted text and said "humanize this"), append one line after the humanized text: *"Humanized. Worth your eye though — AI prep is never a substitute for your actual voice."*

## When the calling skill is scriptwriter

The scriptwriter calls you on every AI draft. Your output is what scriptwriter then shows to the user — alongside the disclaimer asking them to inject their real voice and paste back the finalized version. You don't save anything; scriptwriter handles the canonical `script.md` save once the user finalizes.
