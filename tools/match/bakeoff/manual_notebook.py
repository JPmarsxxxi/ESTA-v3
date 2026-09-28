"""Builds manual_run.ipynb: the bake-off as a notebook run by hand on kaggle.com,
for when the Kaggle API isn't at hand. It needs no credentials in the file:

- the answer key and the HF token are read back from the previous automated
  run's notebook (esta-bakeoff-main-kernel), attached as an input, which
  carries both inline;
- a Kaggle Secret named HF_TOKEN, if added, wins over that token;
- it prints the scores at the end and writes bakeoff_preds.json + gt.json,
  which `kaggle.py apply --skip-download --output-dir <dir> --gt <dir>/gt.json`
  merges into results.md like an API run.

Regenerate after changing kaggle.py or scoring.py:
    python tools/match/bakeoff/manual_notebook.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.match.bakeoff.kaggle import NOTEBOOK_CODE  # noqa: E402

HERE = Path(__file__).resolve().parent

SETTINGS = '''# ESTA bake-off, manual run. Before "Run all":
#  1. Settings (right panel, or the three-dot menu on a phone): Accelerator = GPU T4 x1, Internet = on.
#  2. Add Input > Your Work: the notebook "esta-bakeoff-main-kernel", and the datasets
#     "esta-bakeoff-cuts-data" and "esta-bakeoff-frames-data".
#  3. Optional: Add-ons > Secrets, add HF_TOKEN (your Hugging Face token) and tick it for this notebook.
# Then edit the two lines below if you want a different run.

JOBS = ["tags"]              # any of "cuts", "tags", "theme"
MODELS = ["gemma4-e4b"]      # [] = every candidate in those jobs; names: qwen3-vl-8b, qwen3-vl-4b,
                             # gemma3-4b, gemma4-e4b, siglip2, clip-vit-b32, dinov3-small, transnetv2, pyscenedetect
'''

RECOVER = '''# Read the answer key (and HF token) back from the previous automated run's notebook.
import ast, glob, json, os

def _find_previous_source():
    for path in glob.glob("/kaggle/input/**/*.ipynb", recursive=True) + glob.glob("/kaggle/input/**/*.py", recursive=True):
        try:
            text = open(path, encoding="utf-8").read()
        except Exception:
            continue
        if path.endswith(".ipynb"):
            try:
                text = "".join("".join(c.get("source", "")) for c in json.loads(text)["cells"] if c.get("cell_type") == "code")
            except Exception:
                continue
        if "GT = json.loads(" in text:
            return path, text
    raise RuntimeError("Attach the notebook esta-bakeoff-main-kernel as an input (Add Input > Your Work > Notebooks).")

_path, _src = _find_previous_source()
_values = {}
for node in ast.walk(ast.parse(_src)):
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
        if name == "GT" and isinstance(node.value, ast.Call) and node.value.args:
            _values["GT"] = ast.literal_eval(node.value.args[0])
        elif name == "HF_TOKEN":
            try:
                _values["HF_TOKEN"] = ast.literal_eval(node.value)
            except Exception:
                pass
_GT_JSON = _values["GT"]
_HF = _values.get("HF_TOKEN", "")
try:
    from kaggle_secrets import UserSecretsClient
    _HF = UserSecretsClient().get_secret("HF_TOKEN") or _HF
except Exception:
    pass
_gt = json.loads(_GT_JSON)
_first = next(iter(_gt))
_VIDEO_PROBE = _gt[_first]["video_file"]
_FRAME_PROBE = "%s__shot_%03d.jpg" % (_first, int(_gt[_first]["shots"][0]["shot_id"]))
os.makedirs("/kaggle/working", exist_ok=True)
json.dump(_gt, open("/kaggle/working/gt.json", "w"))
print("answer key from", _path, "-", sum(len(v["shots"]) for v in _gt.values()), "shots;", "HF token set" if _HF else "no HF token")
'''

SUMMARY = '''# Scores, as `kaggle.py apply` would compute them.
print()
for name, preds in results["tags"].items():
    out = score_tags(preds, GT)
    print(f"== {name} ({results['dtype'].get(name, '')}, {results['timing'].get('tags:' + name, {}).get('gpu_min', 0):.1f} GPU-min, {out['unparsed']} unparsed)")
    for field, sc in out["fields"].items():
        if sc.get("testable"):
            print(f"  {field:15s} balanced {sc['balanced_accuracy']:.3f}  accuracy {sc['accuracy']:.3f}  always-guess {sc['baseline']:.3f}")
        else:
            print(f"  {field:15s} untestable: {sc.get('reason')}")
for name, sims in results["theme"].items():
    print(f"== {name}: AUC {auc(sims['pos'], sims['neg']):.3f}")
for name, by_slug in results["cuts"].items():
    gt_cuts = {s: v["cuts"][1:-1] for s, v in GT.items()}
    w = {s: len(gt_cuts[s]) for s in GT}
    print(f"== {name}: F1 {sum(f1_cuts(by_slug.get(s, []), gt_cuts[s]) * n for s, n in w.items()) / (sum(w.values()) or 1):.3f}")
if results["errors"]:
    print("errors:", json.dumps(results["errors"], indent=1))
print("Files to keep: /kaggle/working/bakeoff_preds.json and /kaggle/working/gt.json (Output tab).")
'''


def build() -> Path:
    code = (NOTEBOOK_CODE
            .replace("__GT__", "_GT_JSON")
            .replace("__JOBS__", "JOBS")
            .replace("__MODELS__", "MODELS")
            .replace("__HF_TOKEN__", "_HF")
            .replace("__IN_VIDEOS_SLUG__", "'esta-bakeoff-cuts-data'")
            .replace("__IN_VIDEOS_PROBE__", "_VIDEO_PROBE")
            .replace("__IN_FRAMES_SLUG__", "'esta-bakeoff-frames-data'")
            .replace("__IN_FRAMES_PROBE__", "_FRAME_PROBE"))
    scoring = (HERE / "scoring.py").read_text(encoding="utf-8")
    cells = [SETTINGS, RECOVER, code, "# Scoring (tools/match/bakeoff/scoring.py)\n" + scoring, SUMMARY]
    nb = {
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                   "source": c.splitlines(keepends=True)} for c in cells],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10.0"},
            "kaggle": {"accelerator": "nvidiaTeslaT4", "isGpuEnabled": True, "isInternetEnabled": True,
                       "language": "python", "sourceType": "notebook"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = HERE / "manual_run.ipynb"
    out.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    print(build())
