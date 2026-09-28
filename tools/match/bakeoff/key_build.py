"""Answer-key orchestration for the M5.1 bake-off, driven conversationally by Claude.

Claude reads frame_strips/*.jpg (via the Read tool) to confirm/reject each cut
candidate, and contact_sheets/*.jpg to scan for cuts none of the three
detectors proposed, then calls freeze-cuts. It reads shot_frames/*.jpg to
draft per-shot labels, then calls label-batch. `review` renders a static page
for the user's own spot-check; `check` records which shots they confirmed.
`freeze` is the final gate `kaggle.py push` (the real bake-off, not the
candidate kernel) requires before running.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.bakeoff.common import KEY_DIR, NEGATIVE_DIR, video_dir  # noqa: E402
from tools.match.bakeoff.extract import keyframes_for_shots, probe  # noqa: E402

MIN_TOTAL_SHOTS = 80
MIN_USER_CHECKED = 10
LABEL_FIELDS = ("kind", "text_on_screen", "panels", "overlay", "clips_in_shot")
VALID_KINDS = {"footage", "still", "graphic", "ai", "talking_head", "screen", "meme"}

# Deliberately the visual opposite of both answer-key videos (fast-cut sports
# highlights/reaction memes, and a fast AI-generated ad): slow, single continuous
# subject, muted palette. That contrast is what gives the theme-AUC bake-off metric
# something real to discriminate.
NEGATIVE_QUERY = "slow cinematic nature documentary 4k calm"
NEGATIVE_FRAME_COUNT = 15


def _video_path(slug: str) -> Path:
    meta = json.loads((video_dir(slug) / "meta.json").read_text(encoding="utf-8"))
    return Path(meta["path"])


def cmd_freeze_cuts(args: argparse.Namespace) -> None:
    slug = args.video
    out = video_dir(slug)
    cuts = sorted({round(float(x), 3) for x in args.cuts.split(",") if x.strip()})
    duration = probe(_video_path(slug))["duration"]
    full = [0.0] + [c for c in cuts if 0.0 < c < duration] + [round(duration, 3)]
    (out / "cuts.json").write_text(
        json.dumps({"cuts": full, "shots": len(full) - 1}, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "slug": slug, "shots": len(full) - 1}, ensure_ascii=False))


def cmd_keyframes(args: argparse.Namespace) -> None:
    slug = args.video
    out = video_dir(slug)
    cuts = json.loads((out / "cuts.json").read_text(encoding="utf-8"))["cuts"]
    written = keyframes_for_shots(_video_path(slug), cuts, out)
    print(json.dumps({"ok": True, "slug": slug, "shots": len(written)}, ensure_ascii=False))


def _load_shots(out: Path) -> dict:
    path = out / "shots.json"
    if path.exists():
        return {s["shot_id"]: s for s in json.loads(path.read_text(encoding="utf-8"))}
    return {}


def _save_shots(out: Path, shots: dict) -> None:
    ordered = [shots[k] for k in sorted(shots, key=int)]
    (out / "shots.json").write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8")


def _validate_label(entry: dict) -> None:
    if entry.get("kind") not in VALID_KINDS:
        raise ValueError(f"invalid kind {entry.get('kind')!r}; must be one of {sorted(VALID_KINDS)}")
    if entry.get("panels") not in (1, 2, 3):
        raise ValueError("panels must be 1, 2, or 3 (3 means 3+)")


def cmd_label_batch(args: argparse.Namespace) -> None:
    slug = args.video
    out = video_dir(slug)
    drafts = json.loads(Path(args.file).read_text(encoding="utf-8"))
    shots = _load_shots(out)
    for d in drafts:
        _validate_label(d)
        shot_id = str(d["shot_id"])
        shots[shot_id] = {"shot_id": shot_id, "user_checked": shots.get(shot_id, {}).get("user_checked", False),
                          **{k: d[k] for k in LABEL_FIELDS}}
    _save_shots(out, shots)
    print(json.dumps({"ok": True, "slug": slug, "labeled": len(drafts), "total": len(shots)}, ensure_ascii=False))


def cmd_label(args: argparse.Namespace) -> None:
    slug = args.video
    out = video_dir(slug)
    entry = {"shot_id": args.shot, "kind": args.kind, "text_on_screen": args.text_on_screen,
             "panels": args.panels, "overlay": args.overlay, "clips_in_shot": args.clips_in_shot}
    _validate_label(entry)
    shots = _load_shots(out)
    shot_id = str(entry["shot_id"])
    shots[shot_id] = {"shot_id": shot_id, "user_checked": shots.get(shot_id, {}).get("user_checked", False),
                      **{k: entry[k] for k in LABEL_FIELDS}}
    _save_shots(out, shots)
    print(json.dumps({"ok": True, "slug": slug, "shot_id": shot_id}, ensure_ascii=False))


def cmd_check(args: argparse.Namespace) -> None:
    slug = args.video
    out = video_dir(slug)
    shots = _load_shots(out)
    ids = [s.strip() for s in args.shots.split(",") if s.strip()]
    missing = [i for i in ids if i not in shots]
    if missing:
        raise ValueError(f"shots not yet labeled: {', '.join(missing)}")
    for i in ids:
        shots[i]["user_checked"] = True
    _save_shots(out, shots)
    checked = sum(1 for s in shots.values() if s["user_checked"])
    print(json.dumps({"ok": True, "slug": slug, "checked": checked, "total": len(shots)}, ensure_ascii=False))


def cmd_review(args: argparse.Namespace) -> None:
    rows = []
    for vdir in sorted(KEY_DIR.iterdir()):
        if not vdir.is_dir() or vdir.name == "negative_style" or not (vdir / "shots.json").exists():
            continue
        shots = json.loads((vdir / "shots.json").read_text(encoding="utf-8"))
        cuts = json.loads((vdir / "cuts.json").read_text(encoding="utf-8"))["cuts"]
        for s in shots:
            idx = int(s["shot_id"])
            frame = vdir / "shot_frames" / f"shot_{idx:03d}.jpg"
            rows.append({
                "video": vdir.name, "shot_id": s["shot_id"],
                "start": cuts[idx - 1], "end": cuts[idx],
                "frame": str(frame.relative_to(KEY_DIR)) if frame.exists() else "",
                **{k: s[k] for k in LABEL_FIELDS}, "checked": s["user_checked"],
            })

    sample = rows if args.sample == "all" else rows[:int(args.sample)]
    html = ["<!doctype html><meta charset='utf-8'><title>M5.1 answer key review</title>",
            "<style>body{font-family:sans-serif;background:#111;color:#eee}",
            "table{border-collapse:collapse;width:100%}td,th{border:1px solid #444;padding:4px;font-size:13px}",
            "img{width:160px}.checked{background:#163}</style>",
            f"<h2>Answer key review — {len(rows)} shots, {sum(r['checked'] for r in rows)} checked</h2>",
            "<table><tr><th>frame</th><th>video</th><th>shot</th><th>start-end</th>",
            "<th>kind</th><th>text</th><th>panels</th><th>overlay</th><th>clips</th><th>checked</th></tr>"]
    for r in sample:
        cls = ' class="checked"' if r["checked"] else ""
        img = f"<img src='{r['frame']}'>" if r["frame"] else "(no frame)"
        html.append(f"<tr{cls}><td>{img}</td><td>{r['video']}</td><td>{r['shot_id']}</td>"
                    f"<td>{r['start']:.2f}-{r['end']:.2f}</td><td>{r['kind']}</td>"
                    f"<td>{r['text_on_screen']}</td><td>{r['panels']}</td><td>{r['overlay']}</td>"
                    f"<td>{r['clips_in_shot']}</td><td>{'yes' if r['checked'] else ''}</td></tr>")
    html.append("</table>")
    (KEY_DIR / "review.html").write_text("\n".join(html), encoding="utf-8")
    print(json.dumps({"ok": True, "rows": len(rows), "shown": len(sample),
                      "path": str(KEY_DIR / "review.html")}, ensure_ascii=False))


def cmd_fetch_negative(args: argparse.Namespace) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "style_analysis"))
    from tools.style_analysis.downloader import search_youtube
    import requests

    # Video download (yt-dlp) proved unreliable here — repeated player-client/format
    # failures against current YouTube, and even a working path is slow enough to hit
    # this environment's background-task limits. A frame pool doesn't need one
    # continuous video: one thumbnail each from N different same-style videos is an
    # equally valid "different style" negative pool, and thumbnails are a plain
    # HTTP GET with no video decode at all.
    hits = search_youtube(args.query or NEGATIVE_QUERY, n=NEGATIVE_FRAME_COUNT + 5)
    if not hits:
        raise RuntimeError(f"no YouTube results for {args.query or NEGATIVE_QUERY!r}")
    NEGATIVE_DIR.mkdir(parents=True, exist_ok=True)
    frames_dir = NEGATIVE_DIR / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.jpg"):
        old.unlink()

    used = []
    for candidate in hits:
        if len(used) >= NEGATIVE_FRAME_COUNT:
            break
        vid = candidate["id"]
        for res in ("maxresdefault", "sddefault", "hqdefault"):
            url = f"https://i.ytimg.com/vi/{vid}/{res}.jpg"
            try:
                resp = requests.get(url, timeout=15)
            except Exception:
                continue
            if resp.status_code == 200 and len(resp.content) > 2000:
                (frames_dir / f"frame_{len(used) + 1:03d}.jpg").write_bytes(resp.content)
                used.append(candidate)
                break

    if not used:
        raise RuntimeError(f"no thumbnails fetched among {len(hits)} search hits for "
                           f"{args.query or NEGATIVE_QUERY!r}")

    (NEGATIVE_DIR / "meta.json").write_text(json.dumps({
        "sources": used, "query": args.query or NEGATIVE_QUERY, "frames": len(used),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ok": True, "frames": len(used),
                      "sources": [u["url"] for u in used]}, ensure_ascii=False))


def cmd_freeze(args: argparse.Namespace) -> None:
    gaps = []
    total_shots, total_checked = 0, 0
    for vdir in sorted(KEY_DIR.iterdir()):
        if not vdir.is_dir() or vdir.name == "negative_style":
            continue
        if not (vdir / "cuts.json").exists():
            gaps.append(f"{vdir.name}: no cuts.json")
            continue
        n_shots = json.loads((vdir / "cuts.json").read_text(encoding="utf-8"))["shots"]
        if not (vdir / "shots.json").exists():
            gaps.append(f"{vdir.name}: no shots.json")
            continue
        shots = json.loads((vdir / "shots.json").read_text(encoding="utf-8"))
        if len(shots) != n_shots:
            gaps.append(f"{vdir.name}: {len(shots)} labeled shots, cuts.json implies {n_shots}")
        total_shots += len(shots)
        total_checked += sum(1 for s in shots if s.get("user_checked"))

    shortfall = max(0, MIN_TOTAL_SHOTS - total_shots)
    if shortfall and not args.accept_shortfall:
        gaps.append(f"only {total_shots} total shots, need >= {MIN_TOTAL_SHOTS} "
                    f"(pass --accept-shortfall \"<reason>\" to freeze anyway)")
    if total_checked < MIN_USER_CHECKED:
        gaps.append(f"only {total_checked} user-checked shots, need >= {MIN_USER_CHECKED}")

    if gaps:
        print(json.dumps({"ok": False, "gaps": gaps, "total_shots": total_shots,
                          "total_checked": total_checked}, ensure_ascii=False))
        sys.exit(1)

    frozen = {
        "total_shots": total_shots, "total_checked": total_checked,
        "videos": [d.name for d in sorted(KEY_DIR.iterdir())
                  if d.is_dir() and d.name != "negative_style"],
    }
    if shortfall:
        frozen["accepted_shortfall"] = {"shots_under_target": shortfall, "reason": args.accept_shortfall}
    (KEY_DIR / "frozen.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, **frozen}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer-key orchestration for the M5.1 bake-off")
    sub = parser.add_subparsers(dest="mode", required=True)

    fc = sub.add_parser("freeze-cuts")
    fc.add_argument("--video", required=True)
    fc.add_argument("--cuts", required=True, help="Comma-separated confirmed cut seconds (interior only)")

    kf = sub.add_parser("keyframes")
    kf.add_argument("--video", required=True)

    lb = sub.add_parser("label-batch")
    lb.add_argument("--video", required=True)
    lb.add_argument("--file", required=True, help="JSON list of {shot_id, kind, text_on_screen, panels, overlay, clips_in_shot}")

    lbl = sub.add_parser("label")
    lbl.add_argument("--video", required=True)
    lbl.add_argument("--shot", required=True)
    lbl.add_argument("--kind", required=True, choices=sorted(VALID_KINDS))
    lbl.add_argument("--text-on-screen", type=lambda s: s.lower() == "true", required=True, dest="text_on_screen")
    lbl.add_argument("--panels", type=int, required=True, choices=[1, 2, 3])
    lbl.add_argument("--overlay", type=lambda s: s.lower() == "true", required=True)
    lbl.add_argument("--clips-in-shot", type=int, required=True, dest="clips_in_shot")

    ck = sub.add_parser("check")
    ck.add_argument("--video", required=True)
    ck.add_argument("--shots", required=True, help="Comma-separated shot_ids to mark user_checked")

    rv = sub.add_parser("review")
    rv.add_argument("--sample", default="all")

    fn = sub.add_parser("fetch-negative")
    fn.add_argument("--query", default="")

    fz = sub.add_parser("freeze")
    fz.add_argument("--accept-shortfall", default="",
                    help="Explicit reason to freeze below MIN_TOTAL_SHOTS anyway")

    args = parser.parse_args()
    try:
        {"freeze-cuts": cmd_freeze_cuts, "keyframes": cmd_keyframes, "label-batch": cmd_label_batch,
         "label": cmd_label, "check": cmd_check, "review": cmd_review,
         "fetch-negative": cmd_fetch_negative, "freeze": cmd_freeze}[args.mode](args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
