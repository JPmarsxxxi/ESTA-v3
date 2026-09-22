"""CLI entry point for the timestamps skill.

Called by SKILL.md via:
    conda run -n esta python tools/timestamps/run.py transcribe --session sessions/<id> [--model small]

Prints a single JSON object to stdout. Exits 0 on success, 1 on error.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def cmd_transcribe(args: argparse.Namespace) -> None:
    from tools.timestamps.transcribe import transcribe

    session_dir = Path(args.session)
    audio_path = session_dir / "audio.wav"

    if not audio_path.exists():
        print(json.dumps({"ok": False, "error": f"audio.wav not found at {audio_path}"}))
        sys.exit(1)

    result = transcribe(audio_path=audio_path, model_size=args.model)

    output_path = session_dir / "timestamps.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(json.dumps({
        "ok": True,
        "output": str(output_path),
        "total_duration": result["total_duration"],
        "num_segments": result["num_segments"],
        "num_words": result["num_words"],
        "num_silence_points": len(result["silence_points"]),
        "language": result["metadata"]["language"],
        "language_probability": result["metadata"]["language_probability"],
        "transcription_time_seconds": result["metadata"]["transcription_time_seconds"],
        "model": result["metadata"]["model"],
    }))


def cmd_reconcile(args: argparse.Namespace) -> None:
    from tools.timestamps.reconcile import reconcile

    session_dir = Path(args.session)
    result = reconcile(session_dir)

    print(json.dumps(result))
    if not result.get("ok"):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="ESTA timestamps tool")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_transcribe = sub.add_parser("transcribe", help="Transcribe audio to word-level timestamps")
    p_transcribe.add_argument("--session", required=True, help="Path to session dir (e.g. sessions/foo-2026-05-11)")
    p_transcribe.add_argument("--model", default="small", choices=["base", "small", "medium"],
                              help="Whisper model size (default: small)")

    p_reconcile = sub.add_parser("reconcile", help="Update plan.json shot timing from timestamps.json")
    p_reconcile.add_argument("--session", required=True, help="Path to session dir")

    args = parser.parse_args()

    try:
        if args.mode == "transcribe":
            cmd_transcribe(args)
        elif args.mode == "reconcile":
            cmd_reconcile(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
