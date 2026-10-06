"""The editor's Grade effect (apps/editor/src/esta/opencut/grade.ts), the part
the colour adjust uses: midtone wheel, master curve and HSL saturation, in numpy.
It exists so a fitted grade's result is measured, not guessed, before Build
applies it; keep it in step with bakeGrade.
"""

import numpy as np


def curve_table(points) -> np.ndarray:
    pts = sorted([list(p) for p in points])
    if not pts or pts[0][0] > 0:
        pts.insert(0, [0.0, 0.0])
    if pts[-1][0] < 1:
        pts.append([1.0, 1.0])
    x = np.arange(256) / 255.0
    y = x.copy()
    # Reversed so a point on a segment boundary takes the earlier segment, as the TS loop's break does.
    for j in reversed(range(len(pts) - 1)):
        p0, p1, p2, p3 = pts[max(0, j - 1)], pts[j], pts[j + 1], pts[min(len(pts) - 1, j + 2)]
        m = (x >= p1[0]) & (x <= p2[0])
        t = np.where(p2[0] == p1[0], 0.0, (x - p1[0]) / max(p2[0] - p1[0], 1e-9))
        if len(pts) == 2:
            seg = p1[1] + t * (p2[1] - p1[1])
        else:
            seg = 0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t * t
                         + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t * t * t)
        y = np.where(m, seg, y)
    return np.clip(y, 0, 1)


def _lookup(table, v):
    x = np.clip(v, 0, 1) * 255
    i = np.minimum(254, np.floor(x)).astype(int)
    return table[i] + (table[i + 1] - table[i]) * (x - i)


def _rgb_to_hsl(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    l = (mx + mn) / 2
    d = mx - mn
    s = np.where(d == 0, 0, np.where(l > 0.5, d / np.maximum(2 - mx - mn, 1e-9), d / np.maximum(mx + mn, 1e-9)))
    dd = np.maximum(d, 1e-9)
    h = np.where(mx == r, (g - b) / dd + np.where(g < b, 6, 0), np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4))
    return np.where(d == 0, 0, h / 6), s, l


def _hue2rgb(p, q, t):
    t = np.where(t < 0, t + 1, np.where(t > 1, t - 1, t))
    return np.where(t < 1 / 6, p + (q - p) * 6 * t, np.where(t < 0.5, q, np.where(t < 2 / 3, p + (q - p) * (2 / 3 - t) * 6, p)))


def _hsl_to_rgb(h, s, l):
    q = np.where(l < 0.5, l * (1 + s), l + s - l * s)
    p = 2 * l - q
    out = np.stack([_hue2rgb(p, q, h + 1 / 3), _hue2rgb(p, q, h), _hue2rgb(p, q, h - 1 / 3)], -1)
    return np.where((s == 0)[..., None], l[..., None], out)


def apply_grade(img: np.ndarray, grade: dict) -> np.ndarray:
    """uint8 RGB in, uint8 RGB out."""
    rgb = img.astype("float32") / 255.0
    mid = grade["wheels"]["midtones"]
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    ease = lambda t: t * t * (3 - 2 * t)  # noqa: E731
    sw = 1 - ease(np.clip(luma / 0.5, 0, 1))
    hw = ease(np.clip((luma - 0.5) / 0.5, 0, 1))
    mw = 1 - sw - hw
    master = curve_table(grade["curves"]["rgb"])
    for c, k in enumerate("rgb"):
        rgb[..., c] = _lookup(master, np.clip(rgb[..., c] + mid[k] * mw, 0, 1))
    sat = grade["hsl"]["saturation"]
    if any(sat):
        h, s, l = _rgb_to_hsl(rgb)
        rng = (np.floor(h * 8) % 8).astype(int)
        rgb = _hsl_to_rgb(h, np.clip(s + np.asarray(sat)[rng], 0, 1), l)
    return np.clip(np.round(rgb * 255), 0, 255).astype("uint8")


def make_grade(offset: float, contrast: float, sat: float, warm: float, tint: float) -> dict:
    line = lambda x: float(np.clip((x - 0.5) * contrast + 0.5 + offset, 0, 1))  # noqa: E731
    return {
        "wheels": {"shadows": {"r": 0, "g": 0, "b": 0}, "midtones": {"r": warm / 2, "g": -tint, "b": -warm / 2},
                   "highlights": {"r": 0, "g": 0, "b": 0}, "lift": 0, "gamma": 1, "gain": 1},
        "curves": {"rgb": [[x, round(line(x), 4)] for x in (0, 0.25, 0.5, 0.75, 1)],
                   "red": [[0, 0], [1, 1]], "green": [[0, 0], [1, 1]], "blue": [[0, 0], [1, 1]]},
        "hsl": {"hue": [0] * 8, "saturation": [round(sat, 4)] * 8, "luminance": [0] * 8},
        "lutMix": 1,
    }


def fit_grade(frames, target: dict, scale: dict, strength: float = 0.7):
    """Coordinate search for the grade that moves these frames' colour features
    `strength` of the way to `target`. Returns (grade, expected features)."""
    from tools.match.common import colour_features
    import cv2
    small = [cv2.resize(f, (96, max(1, int(96 * f.shape[0] / f.shape[1])))) for f in frames]
    base = colour_features(small)
    goal = {k: base[k] + strength * (target[k] - base[k]) for k in target}

    def loss(p):
        g = make_grade(*p)
        feats = colour_features([apply_grade(f, g) for f in small])
        return sum(((feats[k] - goal[k]) / scale[k]) ** 2 for k in goal), feats

    bounds = [(-0.25, 0.25), (0.6, 1.6), (-0.5, 0.5), (-0.1, 0.1), (-0.1, 0.1)]
    p = [0.0, 1.0, 0.0, 0.0, 0.0]
    best, feats = loss(p)
    step = [0.08, 0.2, 0.15, 0.04, 0.04]
    for _ in range(4):
        for i in range(5):
            for d in (-1, 1):
                q = list(p)
                q[i] = float(np.clip(q[i] + d * step[i], *bounds[i]))
                val, f2 = loss(q)
                if val < best:
                    best, p, feats = val, q, f2
        step = [s / 2 for s in step]
    return make_grade(*p), feats, base
