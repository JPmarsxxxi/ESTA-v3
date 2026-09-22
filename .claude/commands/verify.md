---
description: Fresh-context check of the current changes against SPEC.md's acceptance criteria before you call the work done
---

This is a gate, not a formality — the goal is to catch "looks done" passing for "is done" before it reaches you.

## Step 1 — Locate ground truth

Find `SPEC.md` in the project root. If it doesn't exist, tell the user there's no spec to verify against and stop (suggest `/spec` first, or ask them what the acceptance criteria should be for this change).

## Step 2 — Gather the diff

Get the current changes: uncommitted diff (`git status` + `git diff`), plus any commits made since the spec was written that aren't on the base branch yet.

## Step 3 — Fresh-context review

Spawn a **new, fresh subagent** (Agent tool, general-purpose type — not a fork, it must NOT inherit this session's reasoning or context) and give it only:
- The full contents of SPEC.md
- The diff/commits from Step 2
- Instruction: check each acceptance criterion in SPEC.md against the actual changes. For each one, run whatever verification the spec specifies (tests, a command, reading the code) rather than assuming.

Tell the reviewer explicitly: flag ONLY gaps that mean an acceptance criterion is unmet, a stated edge case is unhandled, or the change contradicts a stated non-goal. Do not flag style preferences, hypothetical future issues, or nitpicks outside what SPEC.md actually asks for — a reviewer told to find gaps will always find some, and chasing all of them leads to over-engineering, not correctness.

## Step 4 — Report

Report back as a checklist: one line per acceptance criterion, pass/fail, with a one-line reason for any fail. If everything passes, say so plainly — don't manufacture caveats. If something fails, report it and stop; do not silently start fixing things unless the user asks you to.
