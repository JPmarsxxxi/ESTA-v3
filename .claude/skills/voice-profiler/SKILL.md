---
name: voice-profiler
description: Extracts the user's writing techniques from their example scripts and saves a structured voice profile. Reads requirements.json + profile/preferences.md. Outputs sessions/<id>/voice_profile.md — a named list of rhetorical moves, register notes, ending patterns, earned-only patterns, and active-avoid patterns. Consumed by scriptwriter and humanizer (and any future generative skill) to produce technique-level voice matches, not surface pastiche. Invoke automatically after requirements when example_scripts is a list. Skip when example_scripts is the "ASSET_COLLECTOR_PLACEHOLDER" sentinel (re-run later if the user drops samples).
---

# Voice Profiler Skill

You decompose the user's writing into named techniques so downstream skills (scriptwriter, humanizer, future caption/description skills) can apply each move explicitly instead of vibes-matching the surface. Without this profile, AI writing matches caps and slang words but misses the actual rhetorical engine — subject-POV undercuts, direct second-person address, signature endings, the works.

## Preflight

1. Read `sessions/<session-id>/requirements.json`. Get `example_scripts`, `style`, `comments`, `topic`.
2. If `example_scripts` is the sentinel string `"ASSET_COLLECTOR_PLACEHOLDER"`, refuse politely: *"No example scripts to analyze yet — paused here. Drop a sample in chat and I'll extract your voice."* Stop.
3. If `example_scripts` is an empty list, same response.
4. Read `profile/preferences.md` if it exists — global voice notes from past sessions add to (don't override) the per-session analysis.
5. Append every conversational turn to `sessions/<session-id>/conversation.jsonl` with `{"ts": <datetime.now().isoformat()>, "role": ..., "text": ...}`.

## Tone

Brief and direct. Tell the user what you're doing in one short sentence, do the analysis, show the profile concisely, then offer the tweak/redirect/green-light handoff. No fluff.

> "Extracting your voice from the example(s) you dropped. Back in a sec."

## The extraction

Read each example script in full. For each, mentally annotate. Then synthesize across all examples. You are looking for **techniques** — not just words. A technique is the underlying rhetorical move, named.

### What to look for

**Signature rhetorical moves** — the moves that recur and feel load-bearing. Examples (not exhaustive):
- **Subject-POV with undercut** — put the subject's expected thought in their voice, then violently reverse. E.g., *"probably thinking 'I'm saving the season AGAIN.' SIKE bro."*
- **Direct second-person to the subject** — address the team/player/thing as "you", not "they". E.g., *"Your defense collapsed", "sends you home crying"*.
- **Rhetorical question + one-word verdict** — *"That redemption arc? CANCELLED."*
- **Repetition for incredulity** — state a number plain, then yell it. *"33% possession. THIRTY-THREE PERCENT."*
- **Comparison-as-roast** — *"praying for CL qualification like it's a Europa League team."*
- **Slang-as-verb / slang-as-verdict** — *"VIOLATED", "Clinical.", "Absolute shambles."*
- **Negation triplet (with specific numbers, sparingly)** — *"Not ten, not twelve, FOURTEEN."*

If you spot a recurring move that doesn't fit these names, **invent a name for it** and describe it clearly.

**Address style** — who is the writer talking to? "You" (the subject), "you" (the viewer), third-person about the subject? Often a mix — note which is dominant.

**Sentence rhythm** — average sentence length feel, where short fragments appear (climax? transition?), where the writer breaks rhythm intentionally.

**Register / vocabulary** — the specific slang ("bruv", "bro", etc.), what they call things (e.g. "the title race" vs "the league"), all-caps usage patterns.

**Endings** — how paragraphs and sections END. Slang verdict close? Question+verdict? Punchline? Note the dominant pattern.

**Earned-only patterns** — patterns that work BUT only when earned. Negation triplets are the canonical example: fine when used sparingly with specific numbers, AI tell when sprinkled everywhere. Document the user's usage and frequency cap.

**Active avoid list** — what patterns are conspicuously ABSENT from the user's writing that AI tends to use? E.g., third-person passive observation, dramatic narration ("And that's the moment everything dies"), generic transitions ("But wait, it gets worse"). These go on the avoid list.

## Output format — voice_profile.md

Write `sessions/<session-id>/voice_profile.md` with the following structure. Use plain markdown. Keep each technique entry tight (1–3 lines + an illustrative quote from the user's actual examples).

```markdown
# Voice Profile — <session-id>

Extracted from <N> example script(s) in requirements.json on <iso8601>.

## Signature rhetorical moves
- **<Move name>.** <One-line description of how it works.> Use <N>x per script at <when>. Example from user: *"<exact quote>"*
- **<Move name>.** ...
- ...

## Address style
<One short paragraph on who the writer talks to/about, the dominant person, and any consistent stance.>

## Sentence rhythm
<Short notes — typical length, where fragments hit, when rhythm breaks.>

## Register
- <Slang or vocabulary item> — <usage note>
- ALL CAPS usage: <when and where, e.g. "surgically on killer numbers/judgments, not uniformly">
- Slang verbs/verdicts: <list>

## Ending patterns
- **<Pattern name>.** <Description.> Example: *"<quote>"*
- ...

## Earned-only patterns
- **<Pattern name>.** <When it's earned + frequency cap.> Example: *"<quote>"*

## Active avoid list
- <Pattern> — <reason / what it'd sound like>
- ...
```

Field discipline:
- Quote from the user's actual examples wherever you cite — those become the anchor for downstream skills.
- If you have only one example script, say so up front — the profile is provisional and may sharpen with more samples.
- Don't pad. If the user only has 3 signature moves, the file has 3, not 7.

## Save + hand off

1. Write `sessions/<session-id>/voice_profile.md` (UTF-8).
2. **Show a concise summary** to the user in plain language — 3–5 lines naming the most distinctive moves and ending patterns you identified, with one example quote. Don't dump the whole markdown.
3. **Announce next step + offer the pause** per `CLAUDE.md` pipeline rules:
   - If `sessions/<session-id>/research.json` does NOT exist: *"On to research next — anything to tweak in the voice profile first?"*
   - If `research.json` exists already: *"On to the script — anything to tweak in the voice profile first?"*
4. **Read the user's reply:**
   - **Tweak** ("add a move I do called X", "the avoid list should include Y", "this isn't right, my voice is more Z") → edit `voice_profile.md` in place with the Edit tool, re-show summary, re-announce.
   - **Redirect** ("skip to scriptwriter", "stop here") → respect.
   - **Green light** (silence, "ok", "go") → invoke the next skill.

## Re-invocation

If `voice_profile.md` already exists and the skill is invoked again, treat it as a refresh — overwrite the file with the new analysis. The user may have added example scripts since the last run, so re-deriving is intentional, not append.

If the user drops a new example mid-flow during scriptwriter or humanizer, those skills should re-invoke voice-profiler before continuing.
