"""Deterministic watermark check for a candidate pick (SPEC.md Part 12, F5).

The vision judge is asked to reject watermarks but passed a site URL, a photo credit and a show logo. This runs
before it: OCR on 3 frames of the used window, and any text in the outer 15% border band that isn't the shot's
planned caption rejects the candidate when it reads as a URL or domain, a copyright mark, a credit line or a
channel handle. A small corner region with dense edges that stays still while the picture moves flags a logo.

    check_frames(frames, caption="") -> {"reject": bool, "reason": str, "text": [...], "logo": bool}

Frames are RGB uint8 arrays. OCR is rapidocr (CPU); without it the text check is skipped (`ocr: false`).
"""

import re
from functools import lru_cache

BAND = 0.15
URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]{2,}\.(?:com|net|org|co|io|tv|in|uk|de|fr|ru|me|info|biz|app|xyz)\b", re.I)
CREDIT = re.compile(r"©|\(c\)|copyright|\bphoto(?:graph)?\s*(?:by|:|credit)|\bcredit\b|\bcourtesy\b|\bimage\s*(?:by|:)|"
                    r"\bvia\b|\ball rights\b|\bgetty\b|\bshutterstock\b|\balamy\b|\bistock\b|\bdreamstime\b|\bstoryblocks\b", re.I)
HANDLE = re.compile(r"(?<![\w.])@[\w.]{3,}")
MIN_SCORE = 0.5


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    return RapidOCR()


def ocr(frame) -> list[tuple[str, tuple[float, float, float, float]]] | None:
    """[(text, (x0, y0, x1, y1))] in pixels, or None when no OCR engine is installed."""
    import numpy as np
    eng = _engine()
    if eng is None:
        return None
    frame = np.asarray(frame)
    if frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 16:
        return []
    try:
        res, _ = eng(np.ascontiguousarray(frame, dtype=np.uint8))
    except Exception:  # noqa: BLE001 - an unreadable frame has no readable watermark either
        return []
    out = []
    for box, text, score in res or []:
        if float(score) < MIN_SCORE:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append((str(text), (min(xs), min(ys), max(xs), max(ys))))
    return out


def in_band(box, w: int, h: int) -> bool:
    """The whole box lies in the outer band on some side: a watermark hugs an edge, a caption or title doesn't."""
    x0, y0, x1, y1 = box
    return x1 <= BAND * w or x0 >= (1 - BAND) * w or y1 <= BAND * h or y0 >= (1 - BAND) * h


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def offending(text: str) -> str:
    if URL.search(text):
        return "url"
    if CREDIT.search(text):
        return "credit"
    if HANDLE.search(text):
        return "handle"
    return ""


def logo_corner(frames) -> bool:
    """A corner holding a cluster of edges that don't move while the frame as a whole does."""
    import cv2
    import numpy as np
    if len(frames) < 2:
        return False
    try:
        grey = [cv2.cvtColor(np.asarray(f, dtype=np.uint8), cv2.COLOR_RGB2GRAY) for f in frames]
    except cv2.error:
        return False
    h, w = grey[0].shape
    if any(g.shape != (h, w) for g in grey):
        return False
    stack = np.stack(grey).astype(np.int16)
    moving = (stack.max(axis=0) - stack.min(axis=0)) > 12
    if moving.mean() < 0.1:
        return False  # a still or a static shot: stillness says nothing about a logo
    edges = cv2.Canny(grey[0], 80, 160) > 0
    static_edges = edges & ~moving
    ph, pw = int(h * BAND), int(w * BAND)
    for ys, xs in ((slice(0, ph), slice(0, pw)), (slice(0, ph), slice(w - pw, w)),
                   (slice(h - ph, h), slice(0, pw)), (slice(h - ph, h), slice(w - pw, w))):
        if static_edges[ys, xs].mean() > 0.02:
            return True
    return False


def check_frames(frames, caption: str = "") -> dict:
    out = {"reject": False, "reason": "", "text": [], "logo": False, "ocr": True}
    if not frames:
        return out
    planned = _norm(caption)
    for f in frames:
        found = ocr(f)
        if found is None:
            out["ocr"] = False
            break
        h, w = f.shape[:2]
        for text, box in found:
            if not in_band(box, w, h) or (planned and _norm(text) and _norm(text) in planned):
                continue
            kind = offending(text)
            if kind:
                out["text"].append(text)
                if not out["reject"]:
                    out["reject"], out["reason"] = True, f"watermark ({kind}): {text}"
    out["logo"] = logo_corner(frames)
    return out


def check(path, in_point: float = 0.0, out_point: float = 0.0, caption: str = "") -> dict:
    from tools.match.common import media_frames
    try:
        frames = media_frames(path, in_point, out_point, n=3, max_side=960)
    except Exception:  # noqa: BLE001 - an unreadable file is caught by the pick's own checks
        frames = []
    return check_frames(frames, caption)
