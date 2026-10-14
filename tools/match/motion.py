"""Camera move and boundary fades of each inspo shot, measured from frames (SPEC.md Part 3, M6.4, decision 12).

    python tools/match/motion.py --profile cache/inspo/<hash>

A similarity transform (ORB keypoints + RANSAC) between consecutive frames sampled across the middle 80 % of
the shot gives its zoom, pan and jitter; mean luma over the first and last frames gives fades. Written onto
each profile shot as `motion`; the plan copies it into `camera` / `transition_in` / `transition_out` and
render turns those into keyframes.

`motion.subject_motion` (none / low / high, SPEC.md Part 12 goal A) is the motion inside the frame once the camera
move is taken out: each frame is warped onto the next by that same transform, and the share of pixels that still
changed is averaged over the steps. One keyframe can't tell a cartoon from a still (39 of 41 Rick and Morty shots
came out `still`), so a shot tagged `still` that moves `high` is reclassified as moving.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import frames_at, probe, read_json, utf8_stdout, write_json  # noqa: E402

SAMPLES = 9
PUSH = 0.04        # net scale change that reads as a push
PAN = 0.03         # net translation, share of the frame, that reads as a pan or tilt
PUNCH = 0.10       # one-step scale jump that reads as a punch-in
PUNCH_WINDOW = 0.3
PUNCH_SHARE = 0.6
SHAKE = 0.02       # mean per-step translation with little net movement
DARK, BRIGHT = 8, 247
MIN_SPAN = 0.15      # inlier keypoints must spread over this share of the frame to count as a camera move
CHANGED = 25         # a pixel whose grey level moved this much after warping has really changed
SUBJECT_LOW, SUBJECT_HIGH = 0.01, 0.04   # share of changed pixels per step: none < low < high
FADE_SECONDS = 0.5   # fades often hold black a few frames before the cut


def transform(a, b):
    """The 2x3 similarity transform taking frame a to frame b (ORB + RANSAC), or None when untrackable."""
    import cv2
    import numpy as np
    ga, gb = (cv2.cvtColor(f, cv2.COLOR_RGB2GRAY) for f in (a, b))
    orb = cv2.ORB_create(800)
    ka, da = orb.detectAndCompute(ga, None)
    kb, db = orb.detectAndCompute(gb, None)
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(da, db)
    if len(matches) < 12:
        return None
    pa = np.float32([ka[m.queryIdx].pt for m in matches])
    pb = np.float32([kb[m.trainIdx].pt for m in matches])
    m, inliers = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None or inliers is None or inliers.sum() < 10:
        return None
    # Keypoints that agree on the move but cluster in a small part of the frame are a subject moving over a
    # flat background (a cartoon), not the camera: read that as no camera move.
    h, w = ga.shape
    pts = pb[inliers.ravel() > 0]
    span = (pts[:, 0].max() - pts[:, 0].min()) * (pts[:, 1].max() - pts[:, 1].min()) / (w * h)
    if span < MIN_SPAN:
        return None
    return m


def step(a, b) -> tuple[float, float, float] | None:
    """(scale, dx, dy) taking frame a to frame b, translation as a share of width/height; None when untrackable."""
    import numpy as np
    m = transform(a, b)
    if m is None:
        return None
    h, w = a.shape[:2]
    scale = float(np.hypot(m[0, 0], m[1, 0]))
    # Translation of the frame centre, so a pure zoom about the centre reads as no pan.
    cx, cy = w / 2, h / 2
    dx = (m[0, 0] * cx + m[0, 1] * cy + m[0, 2] - cx) / w
    dy = (m[1, 0] * cx + m[1, 1] * cy + m[1, 2] - cy) / h
    return scale, float(dx), float(dy)


def classify(steps: list[tuple[float, float, float] | None], dt: float) -> dict:
    """Name the move from per-step transforms of content between consecutive samples dt seconds apart."""
    import math
    good = [s for s in steps if s]
    if not good:
        return {"move": "static", "amount": 0.0}
    scale = math.prod(s[0] for s in good)
    dx, dy = sum(s[1] for s in good), sum(s[2] for s in good)
    jitter = sum(math.hypot(s[1], s[2]) for s in good) / len(good)
    jump = max(s[0] for s in good)
    # A punch is one sudden step: within the window when samples are that close, otherwise a single step
    # holding most of the shot's zoom (a smooth push spreads its zoom over every step).
    if jump > 1 + PUNCH and (dt <= PUNCH_WINDOW or (scale > 1 and math.log(jump) >= PUNCH_SHARE * math.log(scale))):
        return {"move": "punch_in", "amount": round(min(1.0, (jump - 1) / 0.3), 3)}
    if abs(scale - 1) > PUSH and abs(scale - 1) >= max(abs(dx), abs(dy)):
        return {"move": "push_in" if scale > 1 else "push_out", "amount": round(min(1.0, abs(scale - 1) / 0.3), 3)}
    if max(abs(dx), abs(dy)) > PAN:
        # Content drifting left means the camera pans right.
        move = ("pan_right" if dx < 0 else "pan_left") if abs(dx) >= abs(dy) else ("tilt_down" if dy < 0 else "tilt_up")
        return {"move": move, "amount": round(min(1.0, max(abs(dx), abs(dy)) / 0.3), 3)}
    if jitter > SHAKE and math.hypot(dx, dy) < jitter * len(good) / 3:
        return {"move": "shake", "amount": round(min(1.0, jitter / 0.08), 3)}
    return {"move": "static", "amount": 0.0}


def residual(a, b, m) -> float:
    """Share of pixels that changed between a and b once a is warped by the camera transform m (identity when
    the camera couldn't be tracked: flat cartoon frames often have too few keypoints, and their camera rarely moves)."""
    import cv2
    import numpy as np
    ga, gb = (cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32) for f in (a, b))
    h, w = ga.shape
    m = np.float32([[1, 0, 0], [0, 1, 0]]) if m is None else np.float32(m)
    warped = cv2.warpAffine(ga, m, (w, h), flags=cv2.INTER_LINEAR, borderValue=-1)
    valid = cv2.warpAffine(np.ones_like(ga), m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0) > 0
    # Edges move by a pixel under any resampling; blur both so only real change counts.
    diff = np.abs(cv2.GaussianBlur(warped, (5, 5), 0) - cv2.GaussianBlur(gb, (5, 5), 0))
    inner = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return float((diff[inner] > CHANGED).mean()) if inner.any() else 0.0


def subject_level(share: float) -> str:
    return "high" if share >= SUBJECT_HIGH else "low" if share >= SUBJECT_LOW else "none"


def fade_kind(lumas: list[float]) -> str:
    """lumas ordered from the cut outward: 'black'/'white' when the first is near black/white and they ramp away."""
    if len(lumas) < 3:
        return "none"
    if lumas[0] < DARK and lumas[-1] > lumas[0] + 10 and all(b >= a - 1 for a, b in zip(lumas, lumas[1:])):
        return "black"
    if lumas[0] > BRIGHT and lumas[-1] < lumas[0] - 10 and all(b <= a + 1 for a, b in zip(lumas, lumas[1:])):
        return "white"
    return "none"


def measure(video: Path, start: float, end: float, fps: float) -> dict:
    import numpy as np
    dur = max(end - start, 1e-3)
    times = list(np.linspace(start + 0.1 * dur, end - 0.1 * dur, SAMPLES)) if dur > 0.3 else [start, end - 1e-3]
    frames = frames_at(video, times)
    dt = (times[1] - times[0]) if len(times) > 1 else dur
    pairs = list(zip(frames, frames[1:])) if len(frames) == len(times) else []
    out = classify([step(a, b) for a, b in pairs], dt)
    shares = [residual(a, b, transform(a, b)) for a, b in pairs]
    out["subject_share"] = round(float(np.mean(shares)), 4) if shares else 0.0
    out["subject_motion"] = subject_level(out["subject_share"])
    luma = lambda ts: [float(f.mean()) for f in frames_at(video, ts)]  # noqa: E731
    n = max(3, min(int(FADE_SECONDS * fps), int(dur * fps / 3)))
    out["fade_in"] = fade_kind(luma([start + i / fps for i in range(n)]))
    out["fade_out"] = fade_kind(luma([end - (i + 1) / fps for i in range(n)]))
    return out


def reclassify(shots: list[dict]) -> int:
    """A shot tagged `still` whose subject moves `high` is moving footage: its material says what kind (a cartoon
    stays `cel_animation`). The describe answer is kept as `kind_described`. Returns how many changed."""
    n = 0
    for s in shots:
        tags = s.get("tags") or {}
        if tags.get("kind") == "still" and (s.get("motion") or {}).get("subject_motion") == "high":
            tags["kind_described"] = "still"
            tags["kind"] = "footage"
            n += 1
    return n


def motion_profile(d: Path, log=print) -> int:
    """Measure every shot of a profile that has no `motion` (or no `subject_motion`) yet, then reclassify moving
    stills. Returns how many were measured."""
    prof = read_json(d / "profile.json")
    todo = [s for s in prof["shots"] if "subject_motion" not in (s.get("motion") or {})]
    if not todo:
        if reclassify(prof["shots"]):
            write_json(d / "profile.json", prof)
        return 0
    _, fps = probe(d / "video.mp4")
    log(f"[motion] {len(todo)} shots")
    for s in todo:
        try:
            s["motion"] = measure(d / "video.mp4", s["start"], s["end"], fps or 25.0)
        except Exception as e:  # noqa: BLE001 - an unreadable stretch is a static shot, not a failed profile
            s["motion"] = {"move": "static", "amount": 0.0, "fade_in": "none", "fade_out": "none",
                           "subject_motion": "none", "subject_share": 0.0, "error": str(e)[:120]}
    moved = reclassify(prof["shots"])
    if moved:
        log(f"[motion] {moved} shots tagged still move: reclassified as footage")
    write_json(d / "profile.json", prof)
    return len(todo)


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Measure camera moves and fades for an inspo profile")
    ap.add_argument("--profile", required=True)
    d = Path(ap.parse_args().profile)
    n = motion_profile(d)
    moves: dict = {}
    for s in read_json(d / "profile.json")["shots"]:
        moves[s["motion"]["move"]] = moves.get(s["motion"]["move"], 0) + 1
    print(f"{n} measured; {moves}")


if __name__ == "__main__":
    main()
