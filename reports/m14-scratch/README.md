# M14 overnight scratch tools

The scripts the M14 overnight run (`reports/m14-targets-overnight-log.md`) used, copied verbatim from the user's D: drive. They hard-code local paths (`C:/Users/User/ESTA-v3`, `D:/esta-perf/m14t`) and are not run from here. SPEC.md Part 12 (F4, F6-F10, G) ports the useful ones into `tools/` with tests:

| script | what it did | ports to |
|---|---|---|
| `replan.py` | idea-first cut and build of `plan.json` from `ideas.txt` + `visuals.txt` | `tools/plan/ideas.py` (F4) |
| `snapwords.py` | snaps whisper words in `timestamps.json` to the script's tokens | `tools/timestamps/` (F8) |
| `lines_asr.py` | whisper per voiceover line, to catch TTS meaning flips | `tools/audio/` (F9) |
| `fit.py` | tempo and pause scaling to hit a target length | `tools/audio/` stitch `--target-seconds` (F10) |
| `fix_codecs.py` | H.264 window cuts of AV1/VP9 picks, appended to the feed | `tools/assets/run.py` (F6) |
| `export.mjs` | headless Chrome Build for export + Export, in-page capture to a local receiver | `tools/opencut/export_headless.mjs` (F7) |
| `mg_*.py`, `publish_mg.py` | the flat HyperFrames kits and slot configs per session, and publishing them to the feed | reference only |
| `picksheet.py`, `mgsheet.py` | contact sheets of picks and graphics | reference only |
| `write_scripts.py`, `write_tagged.py`, `write_style.py`, `style_all.sh` | session setup: scripts, tagged scripts, style analyses | reference only |
| `ideas/` | the per-session idea splits fed to `replan.py` | reference only |
