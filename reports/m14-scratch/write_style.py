import json, datetime, pathlib, sys
ROOT = pathlib.Path(r"C:\Users\User\ESTA-v3\sessions")
A = {
"the-clock-was-wrong-2026-10-13": dict(energy_level="medium", pacing="moderate", visual_style="cinematic",
  dominant_content_type="text graphics or title cards",
  shot_patterns="2D cel animation (Rick and Morty): wide establishing interiors and exteriors held 3-8 s, two-shot dialogue at the kitchen table or on the porch at sunset, tight close-up reaction shots on a character's face, quick bursts of cuts on a gag (a gadget explosion), a lonely bedroom night shot, an end card",
  audio_character="character dialogue carries everything, sitcom timing, a few sound effects on gags, music only on the end card",
  keywords=["2d animation", "sitcom", "dialogue scenes", "reaction close-ups", "warm interiors", "sunset exterior", "deadpan"]),
"fade-the-crowd-2026-10-13": dict(energy_level="high", pacing="fast", visual_style="graphic-heavy",
  dominant_content_type="text graphics or title cards",
  shot_patterns="vertical explainer: one surreal, saturated illustration or 3D render per beat behind the narrator (psychedelic heads, giant eyes, pills, hands, radiating rays, neon gradients, vintage collage faces), a short real-footage insert now and then (gym, close-up face), green serif word-by-word captions in the middle of the frame, a big serif title card to open",
  audio_character="fast, confident explainer narration with money figures, no music bed audible under the voice",
  keywords=["psychedelic", "surreal illustration", "neon gradient", "3d render", "money numbers", "word-by-word captions", "explainer"]),
"five-ways-backtest-lies-2026-10-13": dict(energy_level="medium", pacing="fast", visual_style="graphic-heavy",
  dominant_content_type="tutorial or educational content",
  shot_patterns="vertical reverse-advice listicle: editorial collage art in red, black and cream (cut-paper heads, giant eyes, marionettes, a red balloon, crowds of grey figures, a man pushing a boulder), a white numbered title tag per item ('1. Buy EVERY tool you need'), product screenshots and real photos as collage pieces, a talking head cut out over the art, quoted inner-voice lines on black",
  audio_character="dry sarcastic narration, each item announced by number, small captions; ends on 'follow for part two'",
  keywords=["listicle", "editorial collage", "red black cream", "numbered title cards", "sarcastic", "reverse advice"]),
"the-label-was-the-defect-2026-10-13": dict(energy_level="high", pacing="fast", visual_style="graphic-heavy",
  dominant_content_type="text graphics or title cards",
  shot_patterns="motion-design showreel: kinetic typography (words that warp, type on, slide in), abstract 3D objects on flat pastel or saturated colour fields (glass spheres, capsules, stacked pills, grids of tiles), flat geometric shapes overlapping, number reveals on black, an arrow, a few real live-action inserts (a hand at an EV charger, a couple on a stoop, a woman in a tunnel), clean wipes between colour fields",
  audio_character="music-driven (upbeat electronic), no narration; whooshes and hits on transitions",
  keywords=["kinetic typography", "3d objects", "flat colour fields", "clean", "geometric", "number reveals", "showreel"]),
}
for sid in sys.argv[1:] or A:
    e = json.loads((ROOT / sid / "style_extraction.json").read_text(encoding="utf-8"))["extractions"][0]["timing"]
    out = {"session_id": sid, "source": "user_provided", "videos_analyzed": 1,
           "pacing_patterns": {"cuts_per_minute": e["cuts_per_minute"], "avg_shot_duration": e["avg_shot_duration"]},
           **A[sid], "timestamp": datetime.datetime.now().isoformat()}
    (ROOT / sid / "style_analysis.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(sid, e["cuts_per_minute"])
