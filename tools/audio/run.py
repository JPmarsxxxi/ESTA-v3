"""CLI entry point for the audio skill.

Called by SKILL.md via:
    conda run -n esta python tools/audio/run.py <mode> [args]

Prints a single JSON object to stdout. Exits 0 on success, 1 on error
(with {"ok": false, "error": "<message>"} on stdout so the skill can parse it).
"""

import argparse
import json
import sys
from pathlib import Path

# Allow `from tools.audio.X import ...` when called from project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_xtts(args: argparse.Namespace) -> None:
    from tools.audio.xtts import generate_xtts

    session_dir = Path(args.session)
    script_text = (session_dir / "script.md").read_text(encoding="utf-8")
    output_path = session_dir / "audio.wav"

    info = generate_xtts(
        script_text=script_text,
        voice_sample_path=Path(args.sample),
        output_path=output_path,
        gpu=args.gpu,
        speed=args.speed,
    )
    print(json.dumps({"ok": True, "output": str(output_path), **info}))


def cmd_validate(args: argparse.Namespace) -> None:
    from tools.audio.validate import validate_wav

    info = validate_wav(Path(args.path))
    print(json.dumps({"ok": True, **info}))


def cmd_found_fetch(args: argparse.Namespace) -> None:
    from tools.audio.found_fetch import cmd_found_fetch as _run
    _run(args)


def cmd_assemble(args: argparse.Namespace) -> None:
    from tools.audio.assemble import cmd_assemble as _run
    _run(args)


def cmd_analyze_pool(args: argparse.Namespace) -> None:
    from tools.audio.analyze_pool import cmd_analyze_pool as _run
    _run(args)


def cmd_tag_check(args: argparse.Namespace) -> None:
    from tools.audio.tagged import cmd_tag_check as _run
    _run(args)


def cmd_expressive(args: argparse.Namespace) -> None:
    from tools.audio.kaggle_tts import cmd_expressive as _run
    _run(args)


def cmd_stitch(args: argparse.Namespace) -> None:
    from tools.audio.stitch import cmd_stitch as _run
    _run(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA audio tool")
    sub = parser.add_subparsers(dest="mode", required=True)

    # xtts mode
    p_xtts = sub.add_parser("xtts", help="Generate audio with XTTS voice cloning")
    p_xtts.add_argument("--session", required=True, help="Path to session dir (e.g. sessions/foo-2026-05-11)")
    p_xtts.add_argument("--sample", required=True, help="Path to voice sample WAV")
    p_xtts.add_argument("--gpu", action="store_true", default=False, help="Use GPU")
    p_xtts.add_argument("--speed", type=float, default=1.0, help="Playback speed")

    # validate mode
    p_val = sub.add_parser("validate", help="Inspect a WAV file")
    p_val.add_argument("--path", required=True, help="Path to WAV file")

    # found-fetch mode — build a found-audio pool (Phase 3)
    p_ff = sub.add_parser("found-fetch", help="Search + download a found-audio pool by theme")
    p_ff.add_argument("--session", required=True, help="Path to session dir")
    p_ff.add_argument("--queries", required=True, nargs="+", help="One or more search themes/queries")
    p_ff.add_argument("--sources", help="Comma-separated source override (e.g. freesound,archive,youtube)")
    p_ff.add_argument("--per-source", type=int, default=4, help="Max candidates per source per query")
    p_ff.add_argument("--no-download", action="store_true", help="Search only; don't download files")

    # assemble mode — stitch a found-audio arrangement into audio.wav (Phase 5)
    p_as = sub.add_parser("assemble", help="Stitch arrangement.json + pool into audio.wav")
    p_as.add_argument("--session", required=True, help="Path to session dir")

    # analyze-pool mode — transcribe the pool so the arranger understands content
    p_ap = sub.add_parser("analyze-pool", help="faster-whisper transcribe the audio pool")
    p_ap.add_argument("--session", required=True, help="Path to session dir")
    p_ap.add_argument("--model", default="small", choices=["base", "small", "medium"])

    # tag-check — parse script.tagged.md into voice_script.json (pre-approval preview)
    p_tc = sub.add_parser("tag-check", help="Parse the tagged script into per-line jobs")
    p_tc.add_argument("--session", required=True, help="Path to session dir")
    p_tc.add_argument("--sample", help="Path to the voice sample WAV to clone")

    # expressive — IndexTTS2 (+ Seed-VC guide takes) on Kaggle's free GPU
    p_ex = sub.add_parser("expressive", help="Generate per-line VO with IndexTTS2 on Kaggle")
    p_ex.add_argument("--session", required=True, help="Path to session dir")
    p_ex.add_argument("--only", help="Comma-separated line ids to regenerate, e.g. L04,L07")
    p_ex.add_argument("--attach", action="store_true",
                      help="Re-join a kernel already running (skip upload + push) — "
                           "the repair path when the poller dies but the run doesn't")

    # stitch — join the per-line wavs with pace + pauses into audio.wav
    p_st = sub.add_parser("stitch", help="Stitch per-line wavs into audio.wav")
    p_st.add_argument("--session", required=True, help="Path to session dir")

    args = parser.parse_args()

    try:
        if args.mode == "xtts":
            cmd_xtts(args)
        elif args.mode == "validate":
            cmd_validate(args)
        elif args.mode == "found-fetch":
            cmd_found_fetch(args)
        elif args.mode == "assemble":
            cmd_assemble(args)
        elif args.mode == "analyze-pool":
            cmd_analyze_pool(args)
        elif args.mode == "tag-check":
            cmd_tag_check(args)
        elif args.mode == "expressive":
            cmd_expressive(args)
        elif args.mode == "stitch":
            cmd_stitch(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
