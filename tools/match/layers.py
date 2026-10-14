"""Layers of an inspo: what sits across shots rather than inside one (SPEC.md Part 12, goals C and D).

    python tools/match/layers.py --profile cache/inspo/<hash>

Writes onto profile.json:
- `layers.presenter`: a face at a similar position and size over 40% or more of the duration, with its `share`,
  normalised `bbox` and `cutout` (matted over the art, or a full talking-head frame);
- `layers.logo_bug` / `layers.frame`: a region that stays the same across 50% or more of the shots;
- `captions`: the caption layer, read by matching OCR lines against the inspo's transcript (`words.json`):
  `present`, `band` {y0, y1}, `colour`, `highlight`, `font_class`, `case`, `words_per_chunk`, `animation`.
  On-screen display type that isn't speech is not a caption;
- `palette`: the duration-weighted dominant colours of the keyframes.

Faces come from OpenCV's YuNet (downloaded once to cache/models/, OpenCV's bundled Haar cascade without it),
OCR from rapidocr. Everything here is CPU.
"""

import argparse
import re
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import REPO_ROOT, frames_at, image_rgb, read_json, utf8_stdout, write_json  # noqa: E402

LAYERS_VERSION = 1
YUNET = REPO_ROOT / "cache" / "models" / "face_detection_yunet_2023mar.onnx"
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
PRESENTER_SHARE = 0.4
STABLE_SHARE = 0.5
CAPTION_SHARE = 0.3       # sampled moments that must show a caption line for the layer to exist
CAPTION_WORDS = 0.6       # share of an OCR line's tokens that must be spoken around that moment
CAPTION_WINDOW = 2.5      # seconds either side of the moment
SAMPLES = 60
FONT_CLASSES = ("serif", "sans", "condensed", "display", "mono")


def _tok(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ── faces ─────────────────────────────────────────────────────────────────────

_detector = {}


def face_boxes(frame) -> list[tuple[float, float, float, float]]:
    """Faces in an RGB frame as normalised (x, y, w, h), largest first."""
    import cv2
    h, w = frame.shape[:2]
    if "yunet" not in _detector:
        try:
            if not YUNET.exists():
                YUNET.parent.mkdir(parents=True, exist_ok=True)
                urllib.request.urlretrieve(YUNET_URL, YUNET)
            _detector["yunet"] = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7)
        except Exception:  # noqa: BLE001 - offline or an old OpenCV: the bundled Haar cascade
            YUNET.unlink(missing_ok=True)
            _detector["yunet"] = None
            _detector["haar"] = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    if _detector["yunet"] is not None:
        _detector["yunet"].setInputSize((w, h))
        _, found = _detector["yunet"].detect(bgr)
        boxes = [(f[0], f[1], f[2], f[3]) for f in (found if found is not None else [])]
    else:
        boxes = list(_detector["haar"].detectMultiScale(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(24, 24)))
    out = [(max(0.0, x / w), max(0.0, y / h), bw / w, bh / h) for x, y, bw, bh in boxes]
    return sorted(out, key=lambda b: -b[2] * b[3])


def presenter(shots: list[dict], faces: dict[str, tuple]) -> dict | None:
    """The presenter layer from each shot's largest face. A face counts when its centre lies within 0.15 of the
    median face centre and its size is within x0.6-1.6 of the median size. `cutout` is true when most of the
    presenter's duration is over art (a graphic, still or non-live-action material), false for a talking-head frame."""
    total = sum(s["dur"] for s in shots) or 1.0
    seen = [(s, faces[s["id"]]) for s in shots if faces.get(s["id"])]
    if not seen:
        return None
    cx = statistics.median(b[0] + b[2] / 2 for _, b in seen)
    cy = statistics.median(b[1] + b[3] / 2 for _, b in seen)
    size = statistics.median(b[2] * b[3] for _, b in seen)
    near = [(s, b) for s, b in seen if abs(b[0] + b[2] / 2 - cx) < 0.15 and abs(b[1] + b[3] / 2 - cy) < 0.15
            and 0.6 * size <= b[2] * b[3] <= 1.6 * size]
    share = sum(s["dur"] for s, _ in near) / total
    if share < PRESENTER_SHARE:
        # A full-frame talking head cuts between wide and punched-in framings, so its face size varies: footage
        # with a centred face in 40% or more of the shots is still a presenter, not cut out (Part 12 edge case).
        centred = [(s, b) for s, b in seen if (s.get("tags") or {}).get("kind") == "footage" and abs(b[0] + b[2] / 2 - 0.5) < 0.2]
        if len(centred) < PRESENTER_SHARE * len(shots):
            return None
        med = [round(statistics.median(b[i] for _, b in centred), 4) for i in range(4)]
        return {"share": round(sum(s["dur"] for s, _ in centred) / total, 3),
                "bbox": {"x": med[0], "y": med[1], "w": med[2], "h": med[3]}, "cutout": False, "shots": len(centred)}
    art = sum(s["dur"] for s, _ in near if (s.get("tags") or {}).get("kind") in ("graphic", "still")
              or (s.get("tags") or {}).get("material") not in ("", None, "live_action"))
    med = [round(statistics.median(b[i] for _, b in near), 4) for i in range(4)]
    return {"share": round(share, 3), "bbox": {"x": med[0], "y": med[1], "w": med[2], "h": med[3]},
            "cutout": art >= 0.5 * sum(s["dur"] for s, _ in near), "shots": len(near)}


# ── stable regions ────────────────────────────────────────────────────────────

def stable_regions(frames: list) -> dict:
    """A logo bug (a small corner patch with detail) or a frame (a border band) that stays the same across 50% or
    more of the keyframes. A frame that is stable nearly everywhere is a static video, not a layer."""
    import cv2
    import numpy as np
    if len(frames) < 4:
        return {}
    small = np.stack([cv2.resize(f, (160, 90), interpolation=cv2.INTER_AREA).astype(np.int16) for f in frames])
    med = np.median(small, axis=0)
    same = (np.abs(small - med).max(axis=3) < 14).mean(axis=0) >= STABLE_SHARE
    if same.mean() > 0.6:
        return {}
    out = {}
    h, w = same.shape
    edges = cv2.Canny(med.astype(np.uint8), 60, 140) > 0
    ch, cw = int(0.22 * h), int(0.22 * w)
    for ys, xs in ((slice(0, ch), slice(0, cw)), (slice(0, ch), slice(w - cw, w)),
                   (slice(h - ch, h), slice(0, cw)), (slice(h - ch, h), slice(w - cw, w))):
        patch = same[ys, xs] & edges[ys, xs]
        if patch.mean() > 0.03:
            yy, xx = np.nonzero(same[ys, xs] & (cv2.dilate(edges.astype(np.uint8), np.ones((5, 5)))[ys, xs] > 0))
            if not len(yy):
                continue
            y0, x0 = ys.start + yy.min(), xs.start + xx.min()
            out["logo_bug"] = {"x": round(x0 / w, 3), "y": round(y0 / h, 3),
                               "w": round((xs.start + xx.max() + 1 - x0) / w, 3), "h": round((ys.start + yy.max() + 1 - y0) / h, 3)}
            break
    band = max(2, int(0.06 * h))
    border = np.concatenate([same[:band].ravel(), same[-band:].ravel(), same[:, :band].ravel(), same[:, -band:].ravel()])
    if border.mean() > 0.85:
        out["frame"] = {"band": round(band / h, 3)}
    return out


# ── captions ──────────────────────────────────────────────────────────────────

def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, c))) for c in rgb)


def text_colour(crop) -> tuple | None:
    """The fill colour of the text in a crop: of the crop's three main colours, the commonest one that isn't the
    colour along the crop's border (the caption's background or the picture behind it)."""
    import numpy as np
    from PIL import Image
    if crop.size == 0 or min(crop.shape[:2]) < 4:
        return None
    q = Image.fromarray(crop).quantize(colors=3, method=Image.Quantize.MEDIANCUT)
    pal = np.array(q.getpalette()[:9]).reshape(3, 3)
    idx = np.array(q)
    border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
    bg = np.bincount(border, minlength=3).argmax()
    counts = np.bincount(idx.ravel(), minlength=3)
    counts[bg] = -1
    return tuple(int(c) for c in pal[counts.argmax()])


def _case(texts: list[str]) -> str:
    letters = "".join(c for t in texts for c in t if c.isalpha())
    if not letters:
        return "sentence"
    up = sum(c.isupper() for c in letters) / len(letters)
    if up > 0.85:
        return "upper"
    if up < 0.05:
        return "lower"
    words = [w for t in texts for w in t.split() if w[:1].isalpha()]
    return "title" if words and sum(w[0].isupper() for w in words) / len(words) > 0.8 else "sentence"


def caption_lines(obs: dict, words: list[dict]) -> list[dict]:
    """The OCR lines in one sampled moment whose tokens are mostly spoken around that moment."""
    near = {_tok(w["word"]) for w in words if abs((w["start"] + w["end"]) / 2 - obs["t"]) <= CAPTION_WINDOW}
    out = []
    for line in obs["lines"]:
        toks = [t for t in map(_tok, line["text"].split()) if t]
        if toks and sum(t in near for t in toks) / len(toks) >= CAPTION_WORDS:
            out.append(line)
    return out


def caption_layer(observations: list[dict], words: list[dict]) -> dict:
    """observations: [{t, w, h, spoken: the word at t, lines: [{text, box: (x0, y0, x1, y1), colour, word_colour}]}].
    `word_colour` is the colour of the spoken word's part of the line, when the line has other words too."""
    if not words or not observations:
        return {"present": False, "reason": "no speech" if not words else "nothing sampled"}
    hits = [(o, caption_lines(o, words)) for o in observations]
    with_caption = [(o, ls) for o, ls in hits if ls]
    if len(with_caption) < max(3, CAPTION_SHARE * len(observations)):
        return {"present": False, "reason": f"captions in {len(with_caption)} of {len(observations)} sampled moments"}
    ys0 = sorted(line["box"][1] / o["h"] for o, ls in with_caption for line in ls)
    ys1 = sorted(line["box"][3] / o["h"] for o, ls in with_caption for line in ls)
    pick = lambda xs, q: xs[min(len(xs) - 1, int(q * len(xs)))]  # noqa: E731
    texts = [line["text"] for _, ls in with_caption for line in ls]
    per_moment = [sum(len(line["text"].split()) for line in ls) for _, ls in with_caption]
    colours = [line["colour"] for _, ls in with_caption for line in ls if line.get("colour")]
    colour = _hex([statistics.median(c[i] for c in colours) for i in range(3)]) if colours else "#ffffff"
    lit = [(line["colour"], line["word_colour"]) for _, ls in with_caption for line in ls
           if line.get("word_colour") and line.get("colour") and len(line["text"].split()) > 1]
    differs = [wc for c, wc in lit if sum(abs(a - b) for a, b in zip(c, wc)) > 90]
    highlight = _hex([statistics.median(c[i] for c in differs) for i in range(3)]) if lit and len(differs) >= 0.4 * len(lit) else None
    chunk = statistics.median(per_moment)
    animation = "karaoke" if highlight else "word_pop" if chunk <= 1.5 else "static_line"
    return {"present": True, "band": {"y0": round(pick(ys0, 0.1), 3), "y1": round(pick(ys1, 0.9), 3)},
            "colour": colour, "highlight": highlight, "case": _case(texts), "words_per_chunk": round(chunk, 1),
            "animation": animation, "font_class": "sans", "samples": len(with_caption)}


def observe(video: Path, words: list[dict], log=print) -> tuple[list[dict], list]:
    """OCR at up to SAMPLES spoken moments: (observations for caption_layer, caption crops for the font call)."""
    from tools.media.watermark import ocr
    spoken = [w for w in words if _tok(w["word"])]
    if not spoken:
        return [], []
    step = max(1, len(spoken) // SAMPLES)
    obs, crops = [], []
    for w in spoken[::step][:SAMPLES]:
        t = (w["start"] + w["end"]) / 2
        frames = frames_at(video, [t])
        if not frames:
            continue
        f = frames[0]
        found = ocr(f)
        if found is None:
            log("[layers] rapidocr not installed: captions not read")
            return [], []
        lines = []
        for text, (x0, y0, x1, y1) in found:
            crop = f[int(y0):int(y1), int(x0):int(x1)]
            line = {"text": text, "box": (x0, y0, x1, y1), "colour": text_colour(crop)}
            toks = text.split()
            if len(toks) > 1 and _tok(w["word"]) in [_tok(x) for x in toks]:
                # Split the line by character count to find the spoken word's span.
                k = [_tok(x) for x in toks].index(_tok(w["word"]))
                chars = [len(x) + 1 for x in toks]
                a = x0 + (x1 - x0) * sum(chars[:k]) / sum(chars)
                b = x0 + (x1 - x0) * sum(chars[:k + 1]) / sum(chars)
                line["word_colour"] = text_colour(f[int(y0):int(y1), int(a):int(b)])
            lines.append(line)
        o = {"t": t, "w": f.shape[1], "h": f.shape[0], "spoken": w["word"], "lines": lines}
        obs.append(o)
        if len(crops) < 4:
            crops += [f[int(line["box"][1]):int(line["box"][3]), int(line["box"][0]):int(line["box"][2])]
                      for line in caption_lines(o, words)][:4 - len(crops)]
    return obs, crops


FONT_PROMPT = ("The images above are crops of one video's captions. Classify the caption typeface. Reply with ONLY "
               '{"font_class": "serif" | "sans" | "condensed" | "display" | "mono"} (condensed: tall narrow sans '
               "like Anton or Impact; display: decorative, rounded, handwritten or heavily stylised).")


def font_class(crops: list, ask=None) -> str:
    """One vision call over a few caption crops; "sans" when there are none or the call fails."""
    if not crops:
        return "sans"
    try:
        import tempfile
        from tools.match.common import match_config, save_jpg
        from tools.match.describe import SYSTEM, image_block
        if ask is None:
            from tools.match.describe import ask
        with tempfile.TemporaryDirectory() as tmp:
            content = [image_block(save_jpg(c, Path(tmp) / f"c{i}.jpg", 512), 512) for i, c in enumerate(crops)]
            res = ask(content + [{"type": "text", "text": FONT_PROMPT}], SYSTEM, match_config()["describe"]["model"])
        fc = str((res.get("answer") or {}).get("font_class", "")).lower()
        return fc if fc in FONT_CLASSES else "sans"
    except Exception:  # noqa: BLE001 - the class only picks a family; sans is the safe default
        return "sans"


# ── palette ───────────────────────────────────────────────────────────────────

def palette(images: list, weights: list[float], k: int = 5) -> list[str]:
    """The k commonest colours over the images, each image counted by its weight (its shot's duration)."""
    import numpy as np
    from PIL import Image
    tally: dict = {}
    for im, wt in zip(images, weights):
        q = Image.fromarray(im).resize((64, 36)).quantize(colors=6, method=Image.Quantize.MEDIANCUT)
        pal = np.array(q.getpalette()[:18]).reshape(6, 3)
        for i, n in enumerate(np.bincount(np.array(q).ravel(), minlength=6)):
            key = tuple(int(c) // 32 * 32 + 16 for c in pal[i])
            tally[key] = tally.get(key, 0.0) + n * wt
    return [_hex(c) for c, _ in sorted(tally.items(), key=lambda x: -x[1])[:k]]


# ── the pass ──────────────────────────────────────────────────────────────────

def layers_profile(d: Path, log=print, ask=None) -> bool:
    """Run the layers pass on a profile once (LAYERS_VERSION). Returns True when it ran."""
    prof = read_json(d / "profile.json")
    if prof.get("layers_version") == LAYERS_VERSION:
        return False
    shots = prof["shots"]
    keyframes = {s["id"]: image_rgb(d / s["keyframe"]) for s in shots if s.get("keyframe") and (d / s["keyframe"]).exists()}
    log(f"[layers] faces and stable regions over {len(keyframes)} keyframes")
    faces = {sid: (face_boxes(im) or [None])[0] for sid, im in keyframes.items()}
    layers = {}
    p = presenter(shots, faces)
    if p:
        layers["presenter"] = p
    layers.update(stable_regions(list(keyframes.values())))
    words = read_json(d / "words.json", []) or []
    obs, crops = observe(d / "video.mp4", words, log) if (d / "video.mp4").exists() else ([], [])
    captions = caption_layer(obs, words)
    if captions["present"]:
        captions["font_class"] = font_class(crops, ask)
    layers["captions"] = captions
    prof["layers"] = layers
    prof["captions"] = captions
    ids = [s["id"] for s in shots if s["id"] in keyframes]
    prof["palette"] = palette([keyframes[i] for i in ids], [next(s["dur"] for s in shots if s["id"] == i) for i in ids])
    prof["layers_version"] = LAYERS_VERSION
    write_json(d / "profile.json", prof)
    log(f"[layers] presenter: {bool(p)}; captions: {captions['present']}; palette {prof['palette']}")
    return True


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Detect an inspo profile's layers")
    ap.add_argument("--profile", required=True)
    d = Path(ap.parse_args().profile)
    layers_profile(d)
    prof = read_json(d / "profile.json")
    print({k: prof.get(k) for k in ("layers", "palette")})


if __name__ == "__main__":
    main()
