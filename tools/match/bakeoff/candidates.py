"""Cut-candidate generation for the M5.1 answer key, on Kaggle's free GPU.

Runs before the key is frozen — its output (`cut_candidates.json` per video)
is what Claude confirms/rejects from frame strips to build `cuts.json`. This
kernel shares its detector code with the winner-selection kernel in
`kaggle.py` (imported, not duplicated) so "candidates offered to Claude" and
"candidates scored later" never drift apart.

AutoShot is attempted but expected to fail off-mainland: its only published
checkpoint is Baidu Pan with a passcode, no GitHub/HF mirror. Wrapped in the
same try/except as every other detector — a failure here just means one
fewer candidate in cut_candidates.json, not a broken run. `--autoshot-ckpt-url`
is a hook for if a reachable mirror ever exists; it does nothing today.

Same push/status/apply shape as tools/genvideo/run.py.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, ensure_dataset, fetch_output, kaggle_username, kernel_status,
    push_kernel, slugify, use_utf8_stdout, wait_dataset_ready, write_kernel_dir,
)
from tools.match.bakeoff.common import HERE, ensure_video_dir, slug_for  # noqa: E402

use_utf8_stdout()

MAX_NOTEBOOK_BYTES = 1 * 1024 * 1024  # inputs are dataset-mounted, not inlined — this stays small
CLUSTER_TOLERANCE = 0.15  # seconds; matches the spec's cut-candidate union tolerance

NOTEBOOK_CODE = '''# ESTA - cut-candidate bake-off (TransNetV2, AutoShot, PySceneDetect) on Kaggle's free GPU.
import subprocess, sys, json, os, glob, gc, traceback

VIDEOS = json.loads(__VIDEOS__)  # [{"slug", "file"}]
IN_DIR = __IN_DIR__
OUT = "/kaggle/working"
WORK = "/kaggle/temp"
os.makedirs(WORK, exist_ok=True)
AUTOSHOT_CKPT_URL = __AUTOSHOT_CKPT_URL__

def finish(results, errors):
    with open(os.path.join(OUT, "candidates_results.json"), "w") as fh:
        json.dump({"results": results, "errors": errors}, fh)
    print("ESTA_CAND_RESULT::" + json.dumps({"results": results, "errors": errors}))

def cluster(times, tol=__CLUSTER_TOLERANCE__):
    times = sorted(times)
    out = []
    for t in times:
        if out and t - out[-1] < tol:
            continue
        out.append(t)
    return out

def video_fps(path):
    import cv2
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.release()
    return fps

results = {v["slug"]: {"by_detector": {}, "union": []} for v in VIDEOS}
errors = {}

# -- PySceneDetect ----------------------------------------------------------
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "scenedetect[opencv]"], check=False)
try:
    from scenedetect import detect, AdaptiveDetector
    for v in VIDEOS:
        path = os.path.join(IN_DIR, v["file"])
        scenes = detect(path, AdaptiveDetector())
        times = [s[0].get_seconds() for s in scenes[1:]]  # boundary points, not scene 0's start
        results[v["slug"]]["by_detector"]["pyscenedetect"] = times
        print("[esta] pyscenedetect", v["slug"], len(times), "cuts", flush=True)
except Exception as e:
    errors["pyscenedetect"] = str(e)[:300]
    traceback.print_exc()
finish(results, errors)

# -- TransNetV2 ---------------------------------------------------------------
# The CLI's --output is a literal path, no auto-suffixing: default format is CSV
# with a start_time/end_time column already in seconds (read from package source,
# transnetv2_pytorch/cli.py::process_video_to_output / save_results). Weights ship
# inside the wheel, so plain pip install is enough. /kaggle/input is read-only, so
# run against a writable copy in WORK.
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "transnetv2-pytorch"], check=False)
try:
    import csv
    for v in VIDEOS:
        src = os.path.join(IN_DIR, v["file"])
        dst = os.path.join(WORK, v["file"])
        if not os.path.exists(dst):
            import shutil
            shutil.copy(src, dst)
        out_csv = os.path.join(WORK, v["slug"] + "_tn2.csv")
        r = subprocess.run(["transnetv2_pytorch", dst, "--output", out_csv, "--quiet"],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or not os.path.exists(out_csv):
            raise RuntimeError("transnetv2_pytorch failed: " + (r.stderr or r.stdout)[-300:])
        with open(out_csv, newline="") as fh:
            rows = list(csv.DictReader(fh))
        # Each row's end_time is a shot boundary; the last row's end_time is the
        # video's own end, not a cut, so it's dropped.
        times = [round(float(row["end_time"]), 3) for row in rows[:-1]]
        results[v["slug"]]["by_detector"]["transnetv2"] = times
        print("[esta] transnetv2", v["slug"], len(times), "cuts", flush=True)
except Exception as e:
    errors["transnetv2"] = str(e)[:300]
    traceback.print_exc()
finish(results, errors)

# -- AutoShot (best-effort; see module docstring) ------------------------------
try:
    if not AUTOSHOT_CKPT_URL:
        raise RuntimeError("no reachable AutoShot checkpoint configured (upstream is Baidu-only)")
    raise NotImplementedError("AutoShot inference wrapper not written — no verified checkpoint mirror yet")
except Exception as e:
    errors["autoshot"] = str(e)[:300]

for slug in results:
    all_times = [t for det in results[slug]["by_detector"].values() for t in det]
    results[slug]["union"] = cluster(all_times)

finish(results, errors)
'''


def _dataset_files(videos: list[str]) -> dict:
    return {slug_for(v): Path(v).name for v in videos}


def _state_path() -> Path:
    return HERE / "candidates_kernel.json"


def cmd_push(args: argparse.Namespace) -> None:
    videos = [v.strip() for v in args.videos.split(",") if v.strip()]
    if not videos:
        raise ValueError("--videos is required (comma-separated local paths)")
    for v in videos:
        if not Path(v).exists():
            raise FileNotFoundError(v)

    dataset_id = f"{kaggle_username()}/{slugify('esta-bakeoff-cuts-data')}"
    build_dir = HERE / "dataset_build"
    build_dir.mkdir(parents=True, exist_ok=True)
    for old in build_dir.glob("*"):
        if old.is_file() and old.name != "dataset-metadata.json":
            old.unlink()
    for v in videos:
        dest = build_dir / Path(v).name
        dest.write_bytes(Path(v).read_bytes())

    # Kaggle mounts a dataset at /kaggle/input/<slug-of-TITLE>/, same title-must-equal-
    # slug gotcha kaggle_lane.py documents for kernels — a mismatched title silently
    # mounts the dataset under a different folder name than dataset_id implies.
    ok, log = ensure_dataset(build_dir, dataset_id, dataset_id.split("/", 1)[-1])
    if not ok:
        raise RuntimeError(f"dataset upload failed: {log}")
    if not wait_dataset_ready(dataset_id):
        raise RuntimeError("dataset never reached ready state")

    slugs = {slug_for(v): Path(v).name for v in videos}
    video_specs = [{"slug": s, "file": f} for s, f in slugs.items()]

    code = (
        NOTEBOOK_CODE
        .replace("__VIDEOS__", repr(json.dumps(video_specs)))
        .replace("__IN_DIR__", repr(f"/kaggle/input/{dataset_id.split('/', 1)[-1]}"))
        .replace("__AUTOSHOT_CKPT_URL__", repr(args.autoshot_ckpt_url))
        .replace("__CLUSTER_TOLERANCE__", str(CLUSTER_TOLERANCE))
    )

    kernel_id = f"{kaggle_username()}/{slugify('esta-bakeoff-cuts-kernel')}"
    kernel_build = HERE / "kernel_build"
    nb_path = write_kernel_dir(kernel_build, code, kernel_id, ACCELERATORS["t4"])
    (kernel_build / "kernel-metadata.json").write_text(
        json.dumps({
            **json.loads((kernel_build / "kernel-metadata.json").read_text(encoding="utf-8")),
            "dataset_sources": [dataset_id],
        }, indent=2), encoding="utf-8")

    size = nb_path.stat().st_size
    if size > MAX_NOTEBOOK_BYTES:
        raise ValueError(f"notebook is {size / 1e6:.1f} MB — over the {MAX_NOTEBOOK_BYTES / 1e6:.0f} MB ceiling")

    ok, log = push_kernel(kernel_build)
    state = {"kernel": kernel_id, "dataset": dataset_id, "videos": slugs}
    _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps({
        "ok": ok, "kernel": kernel_id, "dataset": dataset_id, "videos": slugs,
        "url": f"https://www.kaggle.com/code/{kernel_id}", "log": log[-400:],
    }, ensure_ascii=False))


def _kernel_ref(explicit: str) -> str:
    if explicit:
        return explicit
    state = _state_path()
    if state.exists():
        ref = json.loads(state.read_text(encoding="utf-8")).get("kernel", "")
        if ref:
            return ref
    return f"{kaggle_username()}/{slugify('esta-bakeoff-cuts-kernel')}"


def cmd_status(args: argparse.Namespace) -> None:
    ref = _kernel_ref(args.kernel)
    state, raw = kernel_status(ref)
    print(json.dumps({"ok": bool(state), "kernel": ref, "state": state, "raw": raw}, ensure_ascii=False))


def cmd_apply(args: argparse.Namespace) -> None:
    ref = _kernel_ref(args.kernel)
    out_dir = Path(args.output_dir) if args.output_dir else HERE / "candidates_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_download:
        fetch_output(ref, out_dir)

    results_path = out_dir / "candidates_results.json"
    if not results_path.exists():
        raise FileNotFoundError(
            f"no candidates_results.json in {out_dir} — check `status` first")
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    results, errors = raw.get("results", {}), raw.get("errors", {})

    counts = {}
    for slug, data in results.items():
        out = ensure_video_dir(slug)
        (out / "cut_candidates.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        counts[slug] = {"union": len(data.get("union", [])),
                        "by_detector": {k: len(v) for k, v in data.get("by_detector", {}).items()}}

    print(json.dumps({"ok": True, "kernel": ref, "counts": counts, "errors": errors}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut-candidate bake-off input for the M5.1 answer key")
    sub = parser.add_subparsers(dest="mode", required=True)

    p = sub.add_parser("push")
    p.add_argument("--videos", required=True, help="Comma-separated local video paths")
    p.add_argument("--autoshot-ckpt-url", default="", help="Reachable AutoShot checkpoint mirror, if any")

    s = sub.add_parser("status")
    s.add_argument("--kernel", default="")

    a = sub.add_parser("apply")
    a.add_argument("--kernel", default="")
    a.add_argument("--output-dir", default="")
    a.add_argument("--skip-download", action="store_true")

    args = parser.parse_args()
    try:
        {"push": cmd_push, "status": cmd_status, "apply": cmd_apply}[args.mode](args)
    except Exception as exc:  # noqa: BLE001 — CLI contract is a JSON error object
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
