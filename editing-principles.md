# Editing Principles

Grounded reference for how ESTA assembles a video, so the output reads as a
*crafted edit*, not a mechanical clip-placement. Modelled on the editing canon
(Murch, Dmytryk, continuity grammar, rhythm theory), **parameterized for both
vertical short-form and horizontal long-form** — ESTA produces both.

**How this is used (intended):**
- `plan` reads this *before* generating shots, so shot choices are principle-aware (the judgment half).
- `render` enforces the codifiable rules deterministically (the rules half).
- Principles are **style- AND format-parameterized** (§3): they scale with the
  energy/mood/pacing `style-analysis` extracts AND the `orientation` +
  `duration_range` from `requirements.json`. They are NOT absolute — a dreamy
  vertical montage and a horizontal long-form explainer apply them differently.

---

## 0. The master hierarchy — Murch's Rule of Six

Every cut decision is ranked. When two principles conflict, the higher one wins;
**never sacrifice a higher priority to satisfy a lower one.**

| # | Priority | Weight | Means |
|---|---|---|---|
| 1 | **Emotion** | 51% | Does the cut make the viewer *feel* the intended thing? |
| 2 | **Story** | 23% | Does it advance / clarify what the script is saying? |
| 3 | **Rhythm** | 10% | Does it land with musical timing? |
| 4 | **Eye-trace** | 7% | Does the eye flow across the cut, not snap? |
| 5 | **2D plane** | 5% | Screen-position continuity. |
| 6 | **3D spatial** | 4% | Real-space continuity. |

**Key reframe for ESTA:** "jarring" is a failure in the **bottom half
(rhythm / eye-trace)**. We fix it aggressively — *but never by breaking emotion
or story.* A cut that lands the feeling beats a technically smooth cut that
doesn't. Source: [StudioBinder](https://www.studiobinder.com/blog/walter-murch-rule-of-six/),
[FilmDaft](https://filmdaft.com/walter-murchs-rule-of-six-the-editors-formula-for-choosing-the-right-cut/).

---

## 1. Deterministic rules — `render` enforces these

Codifiable craft. The project schema already has the slots
(`transitions`, `keyframes`); render just has to fill them. Defaults below are
tunable and **style-gated** (see §3).

### R1 — Motion across every cut (the #1 anti-jarring rule)
There must be movement on screen *through* the cut, never a hard cut between two
dead-static frames.
- **Stills → Ken Burns**: keyframe a slow zoom/pan on every image (e.g. scale
  1.0 → 1.08 over the shot). The frame is always breathing, so the cut reads as
  flow, not a slap.
- **Video → cut in movement**: prefer cut points where the clip is mid-motion;
  begin/end shots with continuing action.
- Source: Dmytryk rules 3 & 5 ("cut in movement", "begin/end with continuing
  action") — [NYFA](https://www.nyfa.edu/student-resources/what-you-can-learn-from-edward-dmytryks-7-rules-of-cutting/),
  [Pond5](https://blog.pond5.com/11775-how-dmytryks-7-rules-of-cutting-hold-up-to-modern-post-production/).

### R2 — Audio bridges (J-cuts / L-cuts) to kill the staccato
Don't cut picture and sound on the same frame. Let audio lead (J) or trail (L)
the visual by ~0.3–0.5s. The canon names the un-bridged feeling exactly:
"abrupt / **staccato**." Works because humans hear-then-look.
- Source: [Filmmakers Academy](https://www.filmmakersacademy.com/glossary/audio-bridge/),
  [StudioBinder](https://www.studiobinder.com/blog/what-is-a-sound-bridge-definition/).

### R3 — Cut on a real boundary, not an estimate
Align shot changes to natural breaks — a speech pause/phrase boundary (from
word-level `timestamps.json`) or a music beat — not the 150 wpm *estimate*.
Cutting on a breath removes the "why did it cut *there*" jar.
- Source: rhythm / "cutting on the beat" — [Fiveable](https://fiveable.me/understanding-film/unit-7/rhythm-pacing-editing/study-guide/y5emVBnZReEe7M4s),
  [Backstage](https://www.backstage.com/magazine/article/film-rhythm-editing-guide-77147/).

### R4 — Shot duration scales with energy; vary it
Short shots = urgency/excitement; long holds = calm/contemplation. Don't sit on
a run of identical-length shots. Map cut frequency to the energy level from
`style-analysis`.
- Source: pacing/rhythm refs above.

### R5 — Transition by style, not by default
Hard cut is the default for *punchy*; short cross-dissolve (~0.3–0.5s) for
*dreamy/moody*. Never gratuitous transitions — they must be motivated.

### R6 — Minimum legibility duration for text/graphics
Text/overlays stay on screen long enough to read (e.g. ≥1.5s) with safe margins;
never flash.

### R7 — When unsure of the cut frame, cut long, not short
Default to slightly longer holds over clipped ones.
- Source: Dmytryk rule 2.

---

## 2. Judgment principles — `plan` (and Claude) reason with these

Not mechanical — applied when generating/ordering shots.

### J1 — Never cut without a positive reason
Every shot change must earn its place (new info, new beat, energy shift). No cut
just because "the clip ran out." Source: Dmytryk rule 1.

### J2 — Substance before form; cut for values, not matches
Serve what the moment *means* over technical tidiness. A cut that's emotionally
right but slightly mismatched beats a clean cut that's flat. Source: Dmytryk
rules 6 & 7; mirrors Murch's emotion-first.

### J3 — Shot variety / "fresh over stale"
Don't place two visually similar shots back-to-back (same framing, subject,
color, brightness). Rotate angle/scale/subject to keep the eye fed. Source:
Dmytryk rule 4; pacing "variety" refs.
- *Note:* this is the same check as the visual-validation flywheel — one rule,
  two consumers. See `notes/visual-validation-distillation.md`.

### J4 — Track the script's emotional arc
Shot choice and pacing follow the script's beats (hook hard, build, breathe,
CTA). Emotion (Rule of Six #1) is set here, not in render.

---

## 3. Style + format parameterization

Principles are not constants — two input sources supply the dials.

**Style** (`style-analysis`):

| style_analysis signal | drives |
|---|---|
| energy level | cut frequency / shot duration (R4), hard-cut vs dissolve (R5) |
| mood (dreamy ↔ punchy) | Ken Burns intensity (R1), dissolve length (R2/R5) |
| content type | how much continuity vs montage logic applies (§4) |

**Format** (`requirements.json` → `orientation` + `duration_range`):

| | Vertical / short | Horizontal / long |
|---|---|---|
| baseline pacing | faster cuts, pattern interrupts, hook in ~3s | can breathe, longer holds, slower build |
| continuity grammar | drop it (§4) — stock montage, no subjects | re-enable if real on-screen subjects |
| framing assumption | center-safe, captions high | rule-of-thirds, lower-thirds |

Style and format compose: a `feels-over-facts` **vertical** montage = strong Ken
Burns, soft dissolves, slow cuts on the music, fast hook. A **horizontal**
long-form explainer = longer holds, hard cuts on the word, room to breathe, and
continuity grammar back in play if there are talking heads.

---

## 4. Continuity grammar — conditional, not dropped

The continuity-grammar rules assume actors + camera coverage. Whether they apply
is a **content-type decision, not a format one** — but the two correlate:

- **Stock-footage montage** (typical of vertical short-form, and any cutaway
  b-roll): **drop** the 180-degree rule, 30-degree rule, and eyeline match —
  there are no consistent on-screen subjects/space to preserve. Keep only
  **match-on-action** (= R1's "cut in movement").
- **Consistent on-screen subjects** (talking heads, interview, narrative — more
  common in horizontal long-form): **re-enable** 180/eyeline so the viewer stays
  spatially oriented.
- Decision input: `style-analysis` content type + `orientation`. Default to the
  montage case (drop) unless the material has stable subjects.
- Source / rationale: [StudioBinder continuity](https://www.studiobinder.com/blog/what-is-continuity-editing-in-film/).
  Adapt the canon, don't copy feature-film grammar wholesale.

---

## Sources
- Walter Murch, *In the Blink of an Eye* (Rule of Six) — StudioBinder, FilmDaft
- Edward Dmytryk, *On Film Editing* (7 rules of cutting) — NYFA, Pond5
- J-cut / L-cut / audio bridge — Filmmakers Academy, StudioBinder
- Rhythm & pacing — Fiveable, Backstage
- Continuity grammar (what we drop) — StudioBinder
