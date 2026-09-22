---
name: conductor
description: Plans and drives the per-session pipeline. Runs right after requirements — picks a flow template (standard-vo or found-audio-collage), adapts it within guardrails, writes + validates pipeline.json, then answers "what runs next?" so skills no longer hardcode their successor. For normal videos it silently lays down the canonical rails; for out-of-norm requests (e.g. found-audio collages) it composes the custom order. Additive — sessions without pipeline.json fall back to CLAUDE.md's canonical order.
---

# Conductor Skill

You decide the *shape* of the pipeline for this session and drive it. Templates are the rails; you adapt at the edges within guardrails. Disk is the source of truth — a step is "done" when its outputs exist, so there's no status to babysit.

## When to invoke

Right after `requirements.json` is written, before research. Every new project. For a normal video this is near-frictionless (lay the `standard-vo` rails and move on); for an unusual request it's where the custom flow gets composed and approved.

## Preflight

Require `sessions/<id>/requirements.json`. If missing, run `requirements` first.

## 1. Pick the template

Read `requirements.json` (topic, style, comments). List options: `python tools/pipeline/conductor.py templates`. Decide:

- **`found-audio-collage`** — when the narration is built from found audio / there's no recorded voiceover. Signals in `comments`/`style`: "found audio", "Bumblebee", "no voiceover", "supercut", "collage", "clips/songs stitched", "movie lines".
- **`standard-vo`** — everything else (the default).

If the request is non-standard, propose the template you inferred and **confirm in one line** before building (this is the approval point). For `standard-vo`, proceed silently.

## 2. Build → show → approve

```bash
python tools/pipeline/conductor.py build --session sessions/<id> --template <name>
python tools/pipeline/conductor.py show  --session sessions/<id>
```

`build` validates the whole order against `contracts.json` before writing `pipeline.json` — it will refuse to write an order whose dependencies don't line up. Show the plan in plain language (ordered steps; note which run in parallel). For a non-standard flow, get a green light, then `conductor.py approve --session sessions/<id>`.

Template adaptation is automatic where defined (e.g. `voice-profiler` is pruned when `example_scripts` is the sentinel, kept when it's a list).

**Hands-on plan mode:** if the user asked to approve shots one by one — signals: "hands-on", "manual mode", "I want to approve each shot/line", "show me before you fetch" — set the plan step to `plan:manual` after building: edit `pipeline.json`'s plan step to `"mode": "manual"`, `"token": "plan:manual"` (contract-valid; bare `plan` means `plan:bulk` via `default_mode`). The user can also flip modes mid-session in conversation — the plan skill honors it and updates the token.

## 3. Drive the pipeline

Instead of each skill hardcoding "next is X", ask the conductor after each step:

```bash
python tools/pipeline/conductor.py next --session sessions/<id>
```

- `{"next": "skill:mode", "parallel": ...}` → invoke that skill in that mode. If `parallel: true`, you may launch it in the background and call `next` again for the following step.
- `{"blocked": "<token>", "missing": [...]}` → those artifacts aren't ready yet; finish the producing step first.
- `{"done": true}` → pipeline complete (`<session-id>.openreel.json` exists).

`done` is derived from disk, so once a step writes its output, `next` advances automatically — no manual status updates. Use `conductor.py mark --step <token> --status skipped` only when the user explicitly skips a step.

## Adaptation within guardrails

You may reorder / insert / skip at the edges, but any custom order MUST validate first:

```bash
python tools/pipeline/validate_flow.py requirements research audio:found-fetch scriptwriter:arranger audio:assemble timestamps style-analysis plan assets render
```

Never run an order that fails validation (a step whose `needs` aren't produced upstream).

## Fallback

If a session has no `pipeline.json`, skills follow CLAUDE.md's canonical order exactly as before. The conductor is purely additive — it never breaks an existing session.

## Code references

- `tools/pipeline/conductor.py` — `build` / `show` / `next` / `mark` / `approve` / `templates`.
- `tools/pipeline/templates.json` — flow templates (the rails).
- `tools/pipeline/contracts.json` + `tools/pipeline/validate_flow.py` — skill I/O contracts + order validator the conductor builds and validates against.
