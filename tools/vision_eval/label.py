"""Write a labelling page for an eval set (SPEC.md Part 8, decision 3).

    python tools/vision_eval/label.py --set D:/esta-perf/vision_eval/<name>

Opens as a local file (<set>/label.html; images load from <set>/items/). Two queues:

- validate: the frames and the shot's required content. M = match, N = mismatch.
- judge: the inspo frame and the candidates. 1-3 = the candidate you would use, 0 = none usable.

S skips, arrow keys move. Haiku's answer is hidden so it can't anchor you. Labels are kept
in the browser and "Download labels.jsonl" saves them; put the file in the set folder and
replay.py --score reads it.
"""

import argparse
import json
import re
from pathlib import Path

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Vision labels</title>
<style>
:root{--bg:#111;--fg:#eee;--mut:#999;--acc:#e8b84a;--ok:#4caf50;--no:#e05050}
body{margin:0;background:var(--bg);color:var(--fg);font:15px system-ui,sans-serif}
header{position:sticky;top:0;background:#000c;padding:10px 16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
button{background:#333;color:var(--fg);border:1px solid #555;padding:6px 12px;border-radius:6px;cursor:pointer}
button.on{background:var(--acc);color:#000}
main{padding:16px;max-width:1400px;margin:auto}
.desc{font-size:18px;margin:8px 0 14px;line-height:1.4}.mut{color:var(--mut);font-size:13px}
.grid{display:flex;gap:10px;flex-wrap:wrap}.grid figure{margin:0;flex:1 1 300px}
.grid img{width:100%;border-radius:6px;display:block}figcaption{color:var(--mut);font-size:13px;padding:4px 0}
.lab{font-size:22px;font-weight:700}.match{color:var(--ok)}.mismatch{color:var(--no)}
kbd{background:#333;border-radius:4px;padding:1px 6px}
</style></head><body>
<header><b>Vision labels</b>
<button id="qv">validate</button><button id="qj">judge</button>
<span id="pos"></span><span id="done" class="mut"></span>
<span class="mut"><kbd>M</kbd>/<kbd>N</kbd> or <kbd>1</kbd>-<kbd>3</kbd>/<kbd>0</kbd>, <kbd>S</kbd> skip, arrows move</span>
<button id="dl">Download labels.jsonl</button></header>
<main id="m"></main>
<script>
const ITEMS = __ITEMS__;
const KEY = "esta-vision-labels-" + __SET__;
let labels = {};
try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
let queue = "validate", idx = 0;
const list = () => ITEMS.filter(i => i.kind === queue);
function save() { try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} }
function render() {
  const L = list(); if (!L.length) { document.getElementById("m").textContent = "nothing to label"; return; }
  idx = Math.max(0, Math.min(idx, L.length - 1));
  const it = L[idx], lab = labels[it.id];
  document.getElementById("qv").className = queue === "validate" ? "on" : "";
  document.getElementById("qj").className = queue === "judge" ? "on" : "";
  document.getElementById("pos").textContent = (idx + 1) + " / " + L.length;
  document.getElementById("done").textContent = L.filter(i => labels[i.id]).length + " labelled";
  const m = document.getElementById("m"); m.innerHTML = "";
  const d = document.createElement("div"); d.className = "desc"; d.textContent = it.desc; m.appendChild(d);
  if (it.extra) { const e = document.createElement("div"); e.className = "mut"; e.textContent = it.extra; m.appendChild(e); }
  const g = document.createElement("div"); g.className = "grid";
  it.images.forEach((src, k) => {
    const f = document.createElement("figure"), im = document.createElement("img"), c = document.createElement("figcaption");
    im.src = src; im.loading = "lazy"; c.textContent = it.captions[k] || ""; f.append(im, c); g.appendChild(f);
  });
  m.appendChild(g);
  const l = document.createElement("div"); l.className = "lab " + (lab || "");
  l.textContent = lab ? "label: " + lab : "unlabelled"; m.appendChild(l);
}
function setLabel(v) { const it = list()[idx]; if (!it) return; labels[it.id] = v; save(); idx++; render(); }
document.addEventListener("keydown", e => {
  const k = e.key.toLowerCase();
  if (queue === "validate" && k === "m") setLabel("match");
  else if (queue === "validate" && k === "n") setLabel("mismatch");
  else if (queue === "judge" && "0123".includes(k) && k.length === 1) {
    const n = +k, c = list()[idx].n_candidates; if (n <= c) setLabel(n ? "best_" + n : "none");
  }
  else if (k === "s" || k === "arrowright") { idx++; render(); }
  else if (k === "arrowleft") { idx--; render(); }
});
document.getElementById("qv").onclick = () => { queue = "validate"; idx = 0; render(); };
document.getElementById("qj").onclick = () => { queue = "judge"; idx = 0; render(); };
document.getElementById("dl").onclick = () => {
  const rows = Object.entries(labels).map(([id, label]) => JSON.stringify({id, label})).join("\\n") + "\\n";
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([rows], {type: "application/x-ndjson"}));
  a.download = "labels.jsonl"; a.click();
};
render();
</script></body></html>"""


def required(prompt: str) -> str:
    m = re.search(r'(?:REQUIRED VISUAL CONTENT|TARGET)[^\n]*\n\s*"(.*?)"\n', prompt, re.DOTALL)
    return m.group(1) if m else prompt[:300]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True)
    a = ap.parse_args()
    root = Path(a.set)
    rows = []
    for line in (root / "items.jsonl").read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        if it["kind"] == "validate":
            q = re.search(r'Search query[^\n]*\n\s*"(.*?)"', it["prompt"])
            rows.append({"id": it["id"], "kind": "validate", "desc": required(it["prompt"]),
                         "extra": f"query: {q.group(1)}" if q else "", "images": it["images"],
                         "captions": [f"frame {i + 1}" for i in range(len(it["images"]))]})
        elif it["kind"] == "judge":
            head = it["sequence"][0]
            caps = ["inspo frame" if "INSPO frame" in head else "candidate 1"]
            caps += [s.split(" ", 2)[-1].rstrip(":") for s in it["sequence"][1:] if isinstance(s, str)]
            rows.append({"id": it["id"], "kind": "judge", "desc": head.split(" INSPO frame")[0],
                         "extra": "Pick 1-3 for the candidate you'd use, 0 if none is usable.",
                         "images": it["images"], "captions": caps, "n_candidates": it["n_candidates"]})
    html = PAGE.replace("__ITEMS__", json.dumps(rows, ensure_ascii=False)).replace("__SET__", json.dumps(root.name))
    (root / "label.html").write_text(html, encoding="utf-8")
    print(f"{root / 'label.html'}: {sum(r['kind'] == 'validate' for r in rows)} validate, "
          f"{sum(r['kind'] == 'judge' for r in rows)} judge")


if __name__ == "__main__":
    main()
