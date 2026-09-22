# Motion Design Principles

Grounded reference for how ESTA authors motion graphics, so a generated card
reads as *art-directed* rather than as the average of every motion graphic ever
made. Third canon doc alongside `editing-principles.md` (the cut) and
`sound-design.md` (the mix) — this one governs anything drawn rather than
filmed.

**How this is used (intended):**
- `motion-graphics` reads this *before* authoring any slot — §0 sets the source
  of the design, §1 is enforceable, §2 is judgment.
- `plan` reads §2 lightly when deciding `MOTION_GRAPHICS` vs `overlay` (what the
  graphic is *for*), not how it looks.
- Principles are **style- and domain-parameterized** (§3): they scale with
  `style_analysis` and the video's subject. They are NOT a fixed look — a
  quant-finance video and a football video applying this doc correctly should
  look nothing like each other. That divergence is the point.

---

## 0. The master rule — steal the native surface

**Every topic already lives on a real surface. Reproduce that surface; don't
invent "a motion graphic."**

Before authoring any slot, answer one question: *where does this information
actually exist in the real world?* Build that, then break it for the joke or the
emphasis.

| Video about | Native surface | Not this |
|---|---|---|
| quant trading | trading terminal — monospace readouts, dot leaders, fills, blotter rows | a dark card with a neon number |
| football | broadcast scoreboard, lower-third, VAR overlay | a dark card with a neon number |
| a court case | filed document, exhibit stamp, docket header | a dark card with a neon number |
| a recipe | index card, handwriting, ingredient list | a dark card with a neon number |
| an app / product | the actual UI, its real chrome | a dark card with a neon number |
| a scientific claim | the paper — figure caption, error bars, DOI | a dark card with a neon number |

**Why this is the master rule:** a "sleek dark card with a glowing number" is not
a thing that exists anywhere. It has no referent, so it carries no meaning and
cannot be specific about anything — which is exactly why it's the modal output.
A terminal readout, by contrast, means *this is the machine that lied to me*. The
surface does narrative work a card cannot.

**The rule generalizes because the surface changes per video while the rule does
not.** No human picks a style per session; the domain picks it.

**Corollary — break the surface for the beat.** The surface is the setup; the
violation is the punchline. A terminal that types normally and then stamps
`DECEASED` across itself is funnier than either half alone. Establish the
convention before you break it.

---

## 1. Deterministic rules — always enforced

Codifiable craft. Violating any of these is a bug, not a style choice.

### M1 — Banned defaults (the regression-to-the-mean list)
These are the tells of an un-art-directed graphic. Never reach for them
*unless the native surface genuinely has them* (a real trading terminal IS
monospace-on-black — that's earned; a recipe card is not):

- **Glow as hierarchy.** `text-shadow: 0 0 20px <accent>` to make something feel
  important. Use size, weight, and space instead.
- **Neon-on-near-black by default.** `#0A0A0A` + `#00E676` is the house style of
  nothing.
- **Traffic-light palette.** Green/amber/red for "good/warning/bad" unless the
  surface is literally a status board.
- **Centered-everything.** A single centered stack in the middle of frame, every
  slot, forever. Centering is a choice for one moment, not a layout system.
- **ExtraBold ALL-CAPS with `letter-spacing: 0.2em`** as the label style.
- **The rounded-rect card** floating in the middle of the void with a subtle
  border and a drop shadow.
- **Count-ups on every number.** A number that ramps is emphasis; three ramping
  at once is noise.

### M2 — Type is a pairing, and it comes from the surface
Two families maximum: one from the surface (its real typeface or nearest free
equivalent), one neutral for anything the surface doesn't own. Weight contrast
carries hierarchy — pair the extremes (Regular against Black), never adjacent
weights. Never letter-space lowercase. Never fake a weight the family lacks.

### M3 — Layout on a grid, anchored off-center
Establish a margin and a baseline grid, then place against it. Asymmetry reads
as designed; dead-centering reads as default. Big number flush to a margin beats
a big number in the middle. Optical alignment beats mathematical for large type.

### M4 — Colour: one surface, one ink, one accent
Take the palette from the surface's real colours. One accent, used for exactly
one job (the thing that matters), never for decoration. If a second accent seems
necessary, the layout has failed. Contrast ≥ 4.5:1 for anything readable at
speed — a graphic that flashes past for 1.2s has no time to be squinted at.

### M5 — Motion serves reading order, not delight
Animate to control *what the eye reads first*, in the order the voiceover says
it. Nothing moves without a reason. Nothing moves that isn't being read.
No easing is ever `linear` except a machine-like effect the surface justifies
(a cursor blink, a scanline, a ticker). Reveals: `power2.out` / `power3.out`.

### M6 — Legibility floor
Any text must hold, fully-formed and static, for ≥ 0.8s. Applies after the
reveal completes — a 1.2s slot means the reveal is over by 0.4s. If the text
can't clear the floor, cut the text, not the hold. (Complements R6 in
`editing-principles.md`.)

### M7 — Motion completes before the cut
All animation completes by `duration − 1.0s`; the last second holds the finished
frame. Render trims the tail via `outPoint` — this is insurance against a cut
landing mid-motion, which reads as a mistake.

---

## 2. Judgment principles — reason with these

### J1 — The graphic must say what the voiceover cannot
If the narration already says "Sharpe of 3.71," a card reading `SHARPE 3.71` is
subtitles with extra steps. The graphic earns its place by showing the thing the
words can't carry: the *shape* of the lie, the scale, the comparison. Prefer
showing 3.71 sitting on a curve that's obviously one bump over printing the
number.

### J2 — One idea per graphic
A slot has one job. Three stats stacked in a card is three graphics wearing a
trenchcoat — pick the one that matters, or give each its own beat.

### J3 — The surface persists; the content changes
Across a session, every slot is the same world seen again. The terminal in slot 3
and the terminal in slot 17 are the *same terminal*, later. This is what makes a
set of graphics read as one system — not a shared hex value, a shared *place*.
Continuity of surface is the strongest cohesion available, and it's free.

### J4 — Callbacks are physical
When a later slot references an earlier one, the reference should be an action
performed on the original object (the stamp lands on the card; the row gets
struck from the blotter), not a redrawing of it. The audience remembers objects.

### J5 — Restraint reads as expensive
When unsure, remove. The cheapest-looking graphics are the busiest ones. Stillness
is affordable to us and reads as confidence.

---

## 3. Style + domain parameterization

Three input sources supply the dials.

**Domain** (`requirements.json` → topic) — picks the surface (§0). This is the
dominant dial; it changes everything downstream.

**Style** (`style_analysis.json`):

| signal | drives |
|---|---|
| energy level | reveal speed, stagger tightness, hold length (M6) |
| visual_style (meme-heavy ↔ minimal) | how hard the surface gets broken (§0 corollary); meme-heavy earns the violation, minimal keeps the surface intact |
| keywords | texture and grain — a "collage" video tolerates print artefacts a "clean explainer" does not |

**Format** (`requirements.json` → `orientation`):

| | Vertical / short | Horizontal / long |
|---|---|---|
| safe area | ≥90px margins, clear of the bottom ~400px (karaoke subs live there) | standard thirds, lower-third band available |
| density | one idea, large | can carry a real table or chart |
| reveal budget | ~0.4s — the slot is 1–3s | can breathe, sequence multiple beats |

Domain and style compose: a **meme-heavy quant** video = terminal surface,
violated hard and often (stamps, glitches, sarcastic comments in the margin). A
**minimal explainer** on the same topic = the same terminal, never broken, calm
type-on, the restraint doing the talking.

---

## 4. Maps to ESTA machinery

- `motion-graphics` authors HyperFrames HTML/CSS/GSAP per slot — M1–M7 are
  checkable in the composition before render; `npx hyperframes snapshot` dumps
  keyframes to eyeball M1/M3 cheaply.
- Full-frame slots (`visual.type: MOTION_GRAPHICS`) own the whole frame; the
  surface can be edge-to-edge.
- Overlay slots (a shot's `overlay` block) float over footage — the surface must
  be a *fragment* of itself (a terminal row, not the whole terminal), inside the
  safe area, with no full-bleed scrim.
- `render` places both; M7's hold tail is what its `outPoint` trims.

---

## Sources
- Josef Müller-Brockmann, *Grid Systems in Graphic Design* — M3
- Ellen Lupton, *Thinking with Type* (pairing, weight contrast) — M2
- Disney/Thomas & Johnston easing & anticipation, adapted for UI — M5
- Diegetic-interface design (film UI/UX: *Alien*, *Minority Report* lineage) — §0
- WCAG contrast ratios — M4
