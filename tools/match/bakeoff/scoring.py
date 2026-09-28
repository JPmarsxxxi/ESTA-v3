"""Scoring for the M5.1 bake-off. The Kaggle kernel only records raw predictions
(bakeoff_preds.json); every metric is computed here, locally, so a change to how
a job is scored never costs another GPU run."""

from collections import Counter

# The answer key was labelled with seven kinds. No model can tell AI-generated
# footage from real, and screen recordings / AI clips play the same role as
# footage in an edit, so scoring folds them into five classes that map onto the
# plan's shot types.
KIND_MAP = {"footage": "footage", "screen": "footage", "ai": "footage", "still": "still",
            "graphic": "graphic", "talking_head": "talking_head", "meme": "meme"}
KINDS = ["footage", "still", "graphic", "talking_head", "meme"]
TAG_FIELDS = ["kind", "text_on_screen", "panels", "overlay", "clips_in_shot"]


def kind5(k: str) -> str:
    return KIND_MAP.get(str(k).strip().lower(), str(k).strip().lower())


def tag_value(field: str, label: dict):
    v = label.get(field)
    if field == "kind":
        return kind5(v)
    if field == "panels":
        return min(3, max(1, int(v or 1)))
    if field == "clips_in_shot":
        return "1" if int(v or 1) <= 1 else "2+"
    return bool(v)


def f1_cuts(pred: list, gt: list, tol: float = 0.1) -> float:
    used = [False] * len(gt)
    gt_sorted = sorted(gt)
    tp = 0
    for p in sorted(pred):
        best_j, best_d = -1, tol + 1e-9
        for j, g in enumerate(gt_sorted):
            d = abs(p - g)
            if not used[j] and d <= tol and d < best_d:
                best_d, best_j = d, j
        if best_j >= 0:
            used[best_j] = True
            tp += 1
    fp, fn = len(pred) - tp, len(gt) - tp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def score_field(pairs: list[tuple]) -> dict:
    """pairs: [(predicted, truth)]. Accuracy alone rewards always guessing the
    common answer, so the bar is on balanced accuracy (mean per-class recall),
    reported next to the always-guess-the-majority baseline. A field whose key
    holds a single value can't show a model is any better than that guess, so it
    is marked untestable instead of passing."""
    truths = Counter(t for _, t in pairs)
    n = len(pairs)
    if not n:
        return {"n": 0, "testable": False, "reason": "no predictions"}
    majority, majority_n = truths.most_common(1)[0]
    accuracy = sum(1 for p, t in pairs if p == t) / n
    recalls = {c: sum(1 for p, t in pairs if t == c and p == c) / k for c, k in truths.items()}
    out = {"n": n, "accuracy": accuracy, "baseline": majority_n / n, "baseline_answer": majority,
           "balanced_accuracy": sum(recalls.values()) / len(recalls),
           "per_class_recall": recalls, "support": dict(truths)}
    if len(truths) < 2:
        return {**out, "testable": False, "reason": f"every shot in the key is {majority!r}"}
    return {**out, "testable": True}


def score_tags(preds: dict, gt: dict) -> dict:
    """preds: {"<slug>/<shot_id>": label dict or None}; gt: {slug: {"shots": [...]}}.
    A shot the model gave no parseable answer for counts as wrong, not skipped."""
    fields = {}
    missing = 0
    for field in TAG_FIELDS:
        pairs = []
        for slug, v in gt.items():
            for s in v["shots"]:
                p = preds.get(f"{slug}/{s['shot_id']}")
                if p is None:
                    if field == "kind":
                        missing += 1
                    pairs.append(("<no answer>", tag_value(field, s)))
                else:
                    pairs.append((tag_value(field, p), tag_value(field, s)))
        fields[field] = score_field(pairs)
    return {"fields": fields, "unparsed": missing}


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability a same-style frame scores above an other-style one (ties half)."""
    if not pos or not neg:
        return 0.0
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def label_counts(gt: dict) -> dict:
    return {field: dict(Counter(str(tag_value(field, s)) for v in gt.values() for s in v["shots"]))
            for field in TAG_FIELDS}
