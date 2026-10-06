"""Re-route this session under SPEC.md Part 7 (M10, decision 8): stock is a capped last resort.

Run from the repo root with the system python, one step at a time:

    python sessions/do-alphas-even-exist-2026-09-29/reroute.py route    # plan sources + clear stock picks' manifests
    python sessions/do-alphas-even-exist-2026-09-29/reroute.py pick     # re-pick, chunk by chunk (long: launch detached)
    python sessions/do-alphas-even-exist-2026-09-29/reroute.py finish   # prune, render, final match score, review page
    python sessions/do-alphas-even-exist-2026-09-29/reroute.py report   # the M10.5 acceptance numbers

`pick` resumes where it stopped (reroute_state.json), so a reaped run is re-launched, not restarted:

    Start-Process -WindowStyle Hidden python -ArgumentList "sessions/do-alphas-even-exist-2026-09-29/reroute.py","pick" `
        -RedirectStandardOutput reroute_pick.log -RedirectStandardError reroute_pick.err

Shot numbers, cuts, refs, captions, overlays, graphics and user_directions are kept; only search_sources change,
and only the shots whose current pick is stock are re-picked. Non-stock picks and every graphic stay.
"""

import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

S = Path(__file__).resolve().parent
ROOT = S.parents[1]
sys.path.insert(0, str(ROOT))

from tools.assets.run import _DEFAULT_SOURCES, STOCK_SOURCES  # noqa: E402
from tools.match.adjust import sync_progress  # noqa: E402
from tools.match.autopick import is_stock, stock_budget, stock_used  # noqa: E402
from tools.match.score import _asset_rows  # noqa: E402

STATE = S / "reroute_state.json"
CHUNK = 20  # shots per autopick process: models reload per chunk, memory is freed between them
OVERRIDE_LEAD = {"pinterest", "giphy"}  # the aesthetic and meme overrides put these first


def load(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def reroute_sources(v: dict) -> list[dict] | None:
    """The shot's search_sources without stock, per decision 2; None when it lists no stock."""
    sources = v.get("search_sources") or []
    if not any(e.get("source") in STOCK_SOURCES for e in sources):
        return None
    kept = [e for e in sources if e.get("source") not in STOCK_SOURCES]
    stock_q = list(dict.fromkeys(q for e in sources if e.get("source") in STOCK_SOURCES for q in e.get("queries") or []))
    fallback_q = stock_q or (kept[0].get("queries") if kept else None) or [v.get("search_query", "")]
    order = [src for src, _ in _DEFAULT_SOURCES.get((v.get("type"), v.get("specificity", "low")),
                                                    _DEFAULT_SOURCES.get((v.get("type"), "low"), []))]
    have = {e["source"] for e in kept}
    out = kept + [{"source": src, "queries": fallback_q[:3]} for src in order if src not in have]
    lead = out[0] if sources and sources[0].get("source") in OVERRIDE_LEAD else None
    rank = {src: i for i, src in enumerate(order)}
    out = sorted((e for e in out if e is not lead), key=lambda e: rank.get(e["source"], len(rank)))
    return ([lead] if lead else []) + out


def route() -> None:
    plan_path = S / "plan.json"
    backup = S / "plan.json.pre-reroute.bak"
    if not backup.exists():
        shutil.copy(plan_path, backup)
    plan = load(plan_path)
    changed = 0
    for s in plan["shots"]:
        v = s.get("visual") or {}
        new = reroute_sources(v)
        if new is not None:
            v["search_sources"] = new
            changed += 1
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    sync_progress(S)
    left = [s["shot_number"] for s in plan["shots"]
            if any(e.get("source") in STOCK_SOURCES for e in (s.get("visual") or {}).get("search_sources") or [])]
    assert not left, f"stock still routed on shots {left}"

    rows = _asset_rows(S)
    stock = sorted(int(k) for k, r in rows.items() if k.isdigit() and r.get("ok") and is_stock(r))
    for n in stock:
        (S / "assets" / "candidates" / f"shot_{n}.json").unlink(missing_ok=True)
    chunks = [stock[i:i + CHUNK] for i in range(0, len(stock), CHUNK)]
    STATE.write_text(json.dumps({"routed_at": datetime.now().isoformat(), "rerouted_sources": changed,
                                 "repick": stock, "chunks": chunks, "done": []}, indent=1), encoding="utf-8")
    print(f"search_sources rerouted on {changed} shots; {len(stock)} stock picks to re-pick in {len(chunks)} chunks "
          f"(budget {stock_budget(S, len(plan['shots']))} of {len(plan['shots'])})")


def pick() -> None:
    state = load(STATE)
    if not state:
        sys.exit("run `route` first")
    # Sequential on purpose: the budget is read from the feed at pick time, so chunks must not race.
    for i, chunk in enumerate(state["chunks"]):
        if i in state["done"]:
            continue
        print(f"[reroute] chunk {i + 1}/{len(state['chunks'])}: shots {chunk[0]}-{chunk[-1]}", flush=True)
        later = [n for j, c in enumerate(state["chunks"]) if j > i and j not in state["done"] for n in c]
        r = subprocess.run([sys.executable, "tools/match/autopick.py", "--session", str(S.relative_to(ROOT)),
                            "--shots", ",".join(map(str, chunk)), "--repicking", ",".join(map(str, later))], cwd=ROOT)
        if r.returncode:
            sys.exit(f"[reroute] chunk {i + 1} failed (exit {r.returncode}); re-run `pick` to resume")
        state["done"].append(i)
        STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")
    pending = load(S / "assets" / "chrome_queue.json", {}) or {}
    waiting = [k for k, v in (pending.get("shots") or {}).items() if v.get("status") == "pending"]
    print(f"[reroute] all chunks picked. Google Images shots waiting on the Chrome pass: {waiting or 'none'}")


def finish() -> None:
    sid = str(S.relative_to(ROOT))
    for cmd in ([sys.executable, str(S / "prune.py")],
                ["conda", "run", "--no-capture-output", "-n", "esta", "python", "tools/render/run.py", "build", "--session", sid],
                [sys.executable, "tools/match/score.py", "--session", sid, "--stage", "final", "--force"]):
        print("[reroute]", " ".join(cmd[-4:]), flush=True)
        if subprocess.run(cmd, cwd=ROOT).returncode:
            sys.exit(f"[reroute] failed: {' '.join(cmd)}")
    report()


def report() -> None:
    plan = load(S / "plan.json")["shots"]
    rows = _asset_rows(S)
    total = len(plan)
    covered = sum(1 for s in plan if (rows.get(str(s["shot_number"])) or {}).get("ok"))
    used, budget = stock_used(rows, set()), stock_budget(S, total)
    project = load(S / f"{S.name}.openreel.json", {}) or {}
    media = (project.get("project") or {}).get("mediaLibrary", {}).get("items") or []
    shot_media = [m for m in media if str(m.get("id", "")).removeprefix("media-shot-").isdigit()]
    placeholders = sum(1 for m in shot_media if not m.get("originalUrl")) if shot_media else "n/a (render first)"
    final = load(S / "match_final.json", {}) or {}
    retyped = Counter((s.get("visual") or {}).get("retype_reason") for s in plan if (s.get("visual") or {}).get("retype_reason"))
    header = "stock:" in (S / "match_review.html").read_text(encoding="utf-8") if (S / "match_review.html").exists() else False
    print(json.dumps({"stock_picks": used, "budget": budget, "shots": total, "within_cap": used <= budget,
                      "covered": f"{covered}/{total}", "placeholders": placeholders,
                      "retyped_to_graphic": dict(retyped), "picks_by_source": Counter(r.get("source") for k, r in rows.items()
                                                                                       if k.isdigit() and r.get("ok")),
                      "final_score": final.get("overall"), "final_pass": final.get("pass"),
                      "review_header_shows_stock": header}, indent=1, default=str))


if __name__ == "__main__":
    steps = {"route": route, "pick": pick, "finish": finish, "report": report}
    if len(sys.argv) != 2 or sys.argv[1] not in steps:
        sys.exit(__doc__)
    steps[sys.argv[1]]()
