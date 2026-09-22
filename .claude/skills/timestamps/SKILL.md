---
name: timestamps
description: Extracts word-level timestamps from the session audio using faster-whisper. Reads audio.wav, writes timestamps.json with per-word start/end times, silence map, and transcription metadata. Invoked automatically after audio completes. Feeds assets and render with frame-accurate timing.
---

# Timestamps Skill

You align the script to the audio track at word level. The output — `timestamps.json` — is what lets assets and render know exactly when each word is spoken.

## Preflight

1. **Conda env check.** Run `conda env list` and confirm a line starting with `esta` exists. If not: *"The esta conda env is missing — run `.\setup.ps1` once to create it, then come back."* Stop.
2. **Audio check.** Confirm `sessions/<session-id>/audio.wav` exists. If not: *"No audio file yet — run the audio skill first."* Stop.
3. Read `config.yaml` for `whisper_model` (default: `small`).
4. Read `sessions/<session-id>/requirements.json` for topic context.

## Run

Tell the user: *"Transcribing with faster-whisper (`<model>` model, ~3-5 min on CPU). This one blocks — plan starts after."*

Run via Bash (blocking — do NOT use run_in_background):

```bash
conda run --no-capture-output -n esta python tools/timestamps/run.py transcribe \
  --session sessions/<id> \
  --model <whisper_model from config.yaml>
```

Parse the JSON stdout. On `"ok": false`, surface the error. Most common cause: audio.wav is corrupt or empty — tell the user to re-run the audio skill.

## Output

`tools/timestamps/run.py` writes `sessions/<session-id>/timestamps.json` directly. The stdout response confirms the write and includes summary stats for display.

## Reconcile plan timing

If `sessions/<session-id>/plan.json` exists, immediately run reconcile (no user interaction needed — this is automatic):

```bash
conda run --no-capture-output -n esta python tools/timestamps/run.py reconcile \
  --session sessions/<id>
```

Parse the JSON stdout:
- `"skipped": true` with `reason` → log it internally, don't tell the user (e.g. already reconciled, or plan not found)
- `"ok": false` → surface the error
- `"ok": true, "skipped": false` → note `shots_updated` / `total_shots` for the summary line

## Show + hand off

Show a concise summary:

> "Timestamps done. Xm Ys of audio, N words across M segments, P silence points. Language: English (99%). Took Xs."

If reconcile updated shots, append to the summary line:

> " · Shot timing updated in plan.json (N/M shots adjusted)."

Then announce next step:

> "Starting plan next — anything to check on the transcript first?"

Check whether `style_analysis.json` exists in the session folder. If yes → invoke the `plan` skill immediately. If no → *"Style-analysis is still running in the background — I'll kick off plan as soon as it lands."* Wait for the background notification, then invoke `plan`.

Read the user's reply per pipeline rules (tweak / redirect / green-light) before proceeding.

## Model reference

| Model | Accuracy | CPU time (approx) |
|---|---|---|
| base | ±120ms | ~2-3 min |
| small | ±100ms | ~3-5 min |
| medium | ±100ms | ~5-7 min |

±100ms is frame-accurate for 30fps video (one frame = 33ms). `small` is the default — `medium` rarely justifies the extra time.

## Code references

- `tools/timestamps/run.py` — CLI entry point. `transcribe` subcommand. Call via `conda run --no-capture-output -n esta`.
- `tools/timestamps/transcribe.py` — faster-whisper wrapper. Constants (CPU_THREADS=12, NUM_WORKERS=4, VAD params, beam_size=5) are ground truth from notebook Cell 8 — do not change.
- `tools/timestamps/schema.py` — TypedDicts: `Word`, `Segment`, `SilencePoint`, `TimestampsData`.
