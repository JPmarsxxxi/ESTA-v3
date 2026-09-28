"""Local frame extraction for the M5.1 bake-off answer key.

Runs in the `esta` conda env, no GPU needed — cv2 + PIL only, same libraries
`tools/style_analysis/analyzer.py` already uses for cut detection and frame
sampling. Three products, built in order because each depends on the last:

  1. `contact_sheets` — 1s-interval grids over the whole video, for Claude to
     scan for cuts none of the three candidate detectors proposed.
  2. `strips` — one composite image per candidate cut timestamp (from
     candidates.py's cut_candidates.json), for Claude to confirm/reject.
  3. `keyframes` — one midpoint frame per confirmed shot (from a frozen
     cuts.json), for Claude to draft the per-shot labels from.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.bakeoff.common import ensure_video_dir, slug_for  # noqa: E402

CONTACT_INTERVAL_SEC = 1.0
CONTACT_PER_ROW = 6
CONTACT_THUMB = 240
STRIP_HALF_WINDOW = 0.3
STRIP_FRAMES = 5


def probe(video_path: Path) -> dict:
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cv2 could not open {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {"fps": fps, "frame_count": frame_count, "duration": frame_count / fps if fps else 0.0}


def write_meta(video_path: Path, out_dir: Path) -> dict:
    meta = {"path": str(Path(video_path).resolve()), **probe(video_path)}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _frame_at(cap, fps: float, t: float):
    import cv2
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, round(t * fps)))
    ok, frame = cap.read()
    return frame if ok else None


def _grid(frames_with_labels: list[tuple], thumb: int, per_row: int):
    """Assemble (frame, label) pairs into a labeled PIL grid image."""
    import cv2
    from PIL import Image, ImageDraw

    tiles = []
    for frame, label in frames_with_labels:
        h, w = frame.shape[:2]
        scale = thumb / w
        small = cv2.resize(frame, (thumb, round(h * scale)))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, len(label) * 6 + 4, 14], fill=(0, 0, 0))
        draw.text((2, 1), label, fill=(255, 255, 0))
        tiles.append(img)

    if not tiles:
        return None
    tw, th = tiles[0].size
    rows = [tiles[i:i + per_row] for i in range(0, len(tiles), per_row)]
    grid = Image.new("RGB", (tw * per_row, th * len(rows)), (20, 20, 20))
    for r, row in enumerate(rows):
        for c, tile in enumerate(row):
            grid.paste(tile, (c * tw, r * th))
    return grid


def contact_sheets(video_path: Path, out_dir: Path, interval: float = CONTACT_INTERVAL_SEC,
                    per_row: int = CONTACT_PER_ROW, thumb: int = CONTACT_THUMB) -> list[Path]:
    import cv2
    sheets_dir = out_dir / "contact_sheets"
    sheets_dir.mkdir(parents=True, exist_ok=True)
    for old in sheets_dir.glob("sheet_*.jpg"):
        old.unlink()

    meta = probe(video_path)
    duration = meta["duration"]
    timestamps = [round(t, 2) for t in _frange(0.0, duration, interval)]

    cap = cv2.VideoCapture(str(video_path))
    tiles = []
    for t in timestamps:
        frame = _frame_at(cap, meta["fps"], t)
        if frame is not None:
            tiles.append((frame, f"{t:.1f}s"))
    cap.release()

    written = []
    per_sheet = per_row * per_row
    for i in range(0, len(tiles), per_sheet):
        grid = _grid(tiles[i:i + per_sheet], thumb, per_row)
        if grid is None:
            continue
        dest = sheets_dir / f"sheet_{i // per_sheet + 1:03d}.jpg"
        grid.save(dest, quality=85)
        written.append(dest)
    return written


def _frange(start: float, stop: float, step: float):
    t = start
    while t < stop:
        yield t
        t += step


def strips(video_path: Path, out_dir: Path, candidates: list[float],
           half_window: float = STRIP_HALF_WINDOW, n: int = STRIP_FRAMES) -> list[Path]:
    import cv2
    strips_dir = out_dir / "frame_strips"
    strips_dir.mkdir(parents=True, exist_ok=True)
    for old in strips_dir.glob("cand_*.jpg"):
        old.unlink()

    meta = probe(video_path)
    cap = cv2.VideoCapture(str(video_path))
    written = []
    for i, t in enumerate(candidates):
        offsets = [-half_window + 2 * half_window * k / (n - 1) for k in range(n)]
        tiles = []
        for off in offsets:
            tt = max(0.0, min(meta["duration"], t + off))
            frame = _frame_at(cap, meta["fps"], tt)
            if frame is not None:
                tiles.append((frame, f"{tt:.2f}s"))
        grid = _grid(tiles, CONTACT_THUMB, n)
        if grid is None:
            continue
        dest = strips_dir / f"cand_{i:03d}.jpg"
        grid.save(dest, quality=90)
        written.append(dest)
    cap.release()
    return written


def keyframes_for_shots(video_path: Path, cuts: list[float], out_dir: Path) -> list[Path]:
    """One midpoint frame per shot. `cuts` is shot boundaries incl. 0 and duration."""
    import cv2
    shots_dir = out_dir / "shot_frames"
    shots_dir.mkdir(parents=True, exist_ok=True)
    for old in shots_dir.glob("shot_*.jpg"):
        old.unlink()

    meta = probe(video_path)
    cap = cv2.VideoCapture(str(video_path))
    written = []
    for i in range(len(cuts) - 1):
        mid = (cuts[i] + cuts[i + 1]) / 2
        frame = _frame_at(cap, meta["fps"], mid)
        if frame is None:
            continue
        dest = shots_dir / f"shot_{i + 1:03d}.jpg"
        cv2.imwrite(str(dest), frame)
        written.append(dest)
    cap.release()
    return written


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_meta(args: argparse.Namespace) -> None:
    slug = slug_for(args.video)
    out_dir = ensure_video_dir(slug)
    meta = write_meta(Path(args.video), out_dir)
    print(json.dumps({"ok": True, "slug": slug, **meta}, ensure_ascii=False))


def cmd_sheets(args: argparse.Namespace) -> None:
    slug = slug_for(args.video)
    out_dir = ensure_video_dir(slug)
    written = contact_sheets(Path(args.video), out_dir, args.interval, args.per_row, args.thumb)
    print(json.dumps({"ok": True, "slug": slug, "sheets": [str(p) for p in written]}, ensure_ascii=False))


def cmd_strips(args: argparse.Namespace) -> None:
    slug = slug_for(args.video)
    out_dir = ensure_video_dir(slug)
    cand_path = out_dir / "cut_candidates.json"
    if not cand_path.exists():
        raise FileNotFoundError(f"no cut_candidates.json for {slug} — run candidates.py apply first")
    union = json.loads(cand_path.read_text(encoding="utf-8"))["union"]
    written = strips(Path(args.video), out_dir, union)
    print(json.dumps({"ok": True, "slug": slug, "strips": [str(p) for p in written]}, ensure_ascii=False))


def cmd_keyframes(args: argparse.Namespace) -> None:
    slug = slug_for(args.video)
    out_dir = ensure_video_dir(slug)
    cuts_path = out_dir / "cuts.json"
    if not cuts_path.exists():
        raise FileNotFoundError(f"no cuts.json for {slug} — run key_build.py freeze-cuts first")
    cuts = json.loads(cuts_path.read_text(encoding="utf-8"))["cuts"]
    written = keyframes_for_shots(Path(args.video), cuts, out_dir)
    print(json.dumps({"ok": True, "slug": slug, "shots": len(written)}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Frame extraction for the M5.1 bake-off answer key")
    sub = parser.add_subparsers(dest="mode", required=True)

    m = sub.add_parser("meta")
    m.add_argument("--video", required=True)

    s = sub.add_parser("sheets")
    s.add_argument("--video", required=True)
    s.add_argument("--interval", type=float, default=CONTACT_INTERVAL_SEC)
    s.add_argument("--per-row", type=int, default=CONTACT_PER_ROW)
    s.add_argument("--thumb", type=int, default=CONTACT_THUMB)

    st = sub.add_parser("strips")
    st.add_argument("--video", required=True)

    k = sub.add_parser("keyframes")
    k.add_argument("--video", required=True)

    args = parser.parse_args()
    try:
        {"meta": cmd_meta, "sheets": cmd_sheets,
         "strips": cmd_strips, "keyframes": cmd_keyframes}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
