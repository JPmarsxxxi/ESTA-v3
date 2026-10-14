# M14 targets overnight log (2026-10-13 → 14)

Four ~60 s videos, one per inspo in `Downloads/targets`, script to export with no user input. Branch `m14-chat-native-editor` (the Qwen timeline code). Canon: `finding-alphas/alpha_log.md`. Voice: clone from `voice_do-alphas-even-exist_2026-09-17.wav`. Vision: Qwen only.

| session | inspo | format | topic |
|---|---|---|---|
| the-clock-was-wrong-2026-10-13 | Rick and Morty clip | 16:9 | #044: a sealed-test pass that was a clock bug |
| fade-the-crowd-2026-10-13 | "Ozempic for the brain" reel | 9:16 | #047: fade-the-crowd signal that inverted |
| five-ways-backtest-lies-2026-10-13 | "10/10 ways" collage reel | 9:16 | 5 ways a backtest lies (commission, vendor data, clock, blank columns, killing early) |
| the-label-was-the-defect-2026-10-13 | buffmotion showreel | 16:9 | #046: 111 models, the label was the defect |

## Progress
- 22:17 sessions created; scripts (132-154 words, tuned to the clone's ~117 wpm), research from alpha_log, tagged scripts self-approved; style extraction done for all 4 (webm has no audio track, so no transcript); voiceovers pushed to Kaggle two at a time; config vision.backend set to qwen
- 22:23 BLOCKED: HuggingFace file downloads return HTTP 500 globally (gpt2, Qwen3.5-9B, IndexTTS-2 all fail; hf-mirror too). Both Kaggle VO kernels died at the IndexTTS-2 checkpoint download. The Qwen server loads from HF too. Polling HF every 2 min; resuming VO the moment it's back.
- 22:30 HF back. Kaggle caps batch GPU sessions at 2, so VO ran two at a time.
- 23:05 All four voiceovers done (IndexTTS2, clone voice). Every line checked by a whisper-medium pass on the line wav. Fixes: "can't" was heard as "can" (meaning flip) -> rewrote as "cannot"; "toll" heard as "toe" -> "beaten its cost"; "previous close" heard as "clothes" -> "the night before". Lines regenerated with --only.
- Length: first stitches were 68-83 s at the clone's natural pace. Dropped one line each from clock ("Rules written down...t-stat of nine point five") and five-ways ("I've done all five, so trust me"), then tempo x1.10-1.15 and pauses x0.6 at stitch, then tighten: clock 62.3 s, five-ways 62.3 s, fade 60.9 s, label 59.5 s.
- 23:26 clock: profile (26 inspo shots, nearly all animated stills, median 3.1 s), idea-first plan 24 shots -> match plan 84.3 PASS after one adjust round (merged to 18 shots), autopick 16/16 from Pinterest (Rick and Morty stills), 2 HyperFrames graphics (profit windows strip, +1.07 -> -0.17), mix + render done. Validator left 4 end punchline shots long vs the inspo's fast ending (accepted).
- 23:49 five-ways: plan 29 shots (24 collage graphics, 5 footage), match plan 80.4 FAIL (theme 64.7: descs vs a talking-head inspo); 24 HyperFrames collage slots rendered. fade: plan 22 shots (17 psychedelic graphics, 5 footage), match plan 80.1 PASS. label: plan 43 shots (27 graphics, 15 footage, 1 still), match plan 74.3 FAIL (shot duration 57: inspo median 0.77 s, ours 1.1 s; the narration's word spacing sets the floor). Clock match final crashed on low memory (paging file), to rerun.
- 00:08 renders done for all four. match final: clock 77.7 FAIL (theme 53, colour 74 after grades), five-ways 77.5 FAIL (colour 61; adjust kept 20 grade changes). fade/label finals running. Fade shot 18 re-picked: first pick was a political figure handing over a trophy, swapped for a neutral stage-lights clip. Label MG text on dark fields rendered black (inherited colour); fixed in the kit and re-rendered.
- 00:28 match final: fade 70.5 FAIL (colour 48.5, theme 44.9: every inspo frame has the presenter cut out over the art; we have no face footage, so the graphics carry the full frame), label 76.2 FAIL (shot duration 57). Export: the user's Chrome window is minimized, and Chrome defers media loading in hidden tabs, so Build for export stalled on the voiceover. Switched to a separate headless Chrome (own profile, puppeteer-core, D:/esta-perf/m14t/export.mjs) driving the same Edit stage: Build for export (originals) -> Export. Clock exported in ~1 min (1080p H.264 + AAC, 62.3 s). Found that match:final's adjust had re-picked clock shots 5, 9, 11 with live-action Pinterest photos and its revert left them in the feed; restored the cartoon picks and re-exported. Recorded checkpoint approvals in each pipeline.json ui.approvals as by: claude-overnight.
- 00:53 Export fix: Chrome's own download of the blob stalled once at .crdownload and the headless GPU process ballooned to 4.6 GB; export.mjs now runs with --use-angle=d3d11 --enable-gpu, captures the export in-page and posts it to a local receiver, and waits for a fresh 'Built' stamp. Clock re-exported clean (all cartoon shots). Exporting five-ways, fade, label.
- 02:04 All four exported. Label stalled twice at ~70% in headless export: hardware video decoders run out with 43 clips. Fixed by launching the export Chrome with --disable-accelerated-video-decode (SWDEC=1). Also cut the picked AV1/VP9 YouTube clips to short H.264 windows (fix_codecs.py) on the way. Fade re-exported after moving the graphics' green words to the top of frame: they collided with the karaoke subtitles.

## Results (morning)

Videos: `C:\Users\User\Downloads\esta-exports-2026-10-14\` (H.264 + AAC, built from originals).

| video | format | length | match plan | match final | look |
|---|---|---|---|---|---|
| the-clock-was-wrong | 1920x1080 | 62.3 s | 84.3 pass | 77.7 fail (theme 53) | Rick and Morty stills from Pinterest + 2 cartoon-palette charts |
| five-ways-backtest-lies | 1080x1920 | 62.3 s | 80.4 fail | 77.5 fail (colour 61) | red/cream/black cut-paper collage, numbered tags, 5 footage inserts |
| fade-the-crowd | 1080x1920 | 60.9 s | 80.1 pass | 70.5 fail (colour 49, theme 45) | psychedelic plates (rings, rays, capsules, grid) + 5 footage beats |
| the-label-was-the-defect | 1920x1080 | 59.6 s | 74.3 fail | 76.2 fail (shot length 57) | flat colour fields, kinetic type, abstract b-roll |

What worked unattended: script -> clone VO (IndexTTS2, Kaggle) -> whisper -> idea-first mapped plan -> Qwen-judged autopick -> HyperFrames graphics -> render -> Build for export -> Export.

Engine issues found (worth fixing in code, none fixed in the repo tonight):
1. **match:final's adjust leaks re-picks.** When a round is reverted, the plan is restored but autopick's new feed lines stay, so the export showed off-style stock photos (clock shots 5, 9, 11). Restored by hand.
2. **Headless/hidden export.** The Edit stage can't build in a hidden or minimized tab (Chrome defers media loading), and long timelines exhaust hardware decoders. Software decode fixed both in headless.
3. **Talking-head inspos.** Two inspos (fade, five-ways) put a presenter over every frame; with no face footage, colour and theme can't match, which is most of fade's 70.5.
4. **Shot-length floor.** The showreel inspo cuts every 0.77 s; narration word spacing limits idea-first cuts to ~1.1 s median, so section e can't pass.
5. **Karaoke subtitle band in vertical** sits around y 1150-1300, not the bottom 400 px that motion-design.md assumes. Graphics placed per the canon collide with it.
6. **ASR errors.** Whisper output went straight into subtitles and alignment ("seal test", "0 .53", "back test"). Snapping words back to the script (snapwords.py) fixed both. Two TTS lines changed meaning ("can't" heard as "can"); caught with a per-line whisper check.

Scratch tooling (not committed): D:/esta-perf/m14t/ (replan.py, snapwords.py, fit.py, mg_*.py, publish_mg.py, fix_codecs.py, export.mjs). config.yaml vision.backend is back to claude. Nothing committed; sessions are gitignored.
