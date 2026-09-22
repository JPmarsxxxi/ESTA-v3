---
description: Interview the user in depth about a feature/project, then write a SPEC.md before any code is touched
argument-hint: [one-line description of what you want to build]
---

You are about to plan work, not write code. Do not create, edit, or run anything yet.

Initial brief from the user: $ARGUMENTS

If the brief above is empty, ask for one sentence describing what they want built before continuing.

## Step 1 — Interview

Use the AskUserQuestion tool to interview the user in detail about this feature/project. Cover:
- Technical implementation approach and constraints
- UI/UX (if applicable)
- Edge cases and failure modes
- Explicit non-goals — what this should NOT do or handle
- Tradeoffs where more than one reasonable approach exists

Don't ask obvious questions the brief already answers. Dig into the parts a first-pass prompt would gloss over — the nuance is the whole point of this step. Keep interviewing across multiple rounds until you're confident you understand the shape of the thing, not just the first pass.

## Step 2 — Write SPEC.md

Once the interview is done, write (or update) `SPEC.md` in the project root with these sections:

- **Goal** — what this does, in plain terms
- **Non-goals / out of scope** — explicit, not implied
- **Files & interfaces involved** — name them if known
- **Key decisions & tradeoffs** — what was chosen and why, from the interview
- **Edge cases** — what must be handled
- **Acceptance criteria** — a concrete, checkable list. Each item should be verifiable (a test, a command that must pass, a behavior you can observe) — not vague ("works well").

Keep it self-contained: someone with zero memory of this conversation should be able to implement correctly from the file alone.

## Step 3 — Hand off

Tell the user the spec is written, ask them to review/edit it directly, and recommend starting a **fresh session** (or `/clear`) before implementation — a clean context focused only on building against the spec beats one full of interview back-and-forth. Do not start implementing in this session unless they explicitly say to.
