"""Conductor — Phase 6 of notes/smart-pipeline-and-found-audio.md.

The hybrid orchestration layer. After requirements, it instantiates a flow
TEMPLATE (templates.json) into a per-session `pipeline.json`, adapting within
guardrails and validating the whole order against contracts.json before writing.
Then it answers "what runs next?" — derived from DISK (a step is done iff its
outputs exist), so there is no fragile status to drift.

The canonical `standard-vo` order remains the documented fallback: if a session
has no pipeline.json, skills follow CLAUDE.md's order as before. This file is
purely additive.

CLI:
    conductor.py templates
    conductor.py build  --session <dir> --template found-audio-collage
    conductor.py show   --session <dir>
    conductor.py next   --session <dir>
    conductor.py mark   --session <dir> --step audio:found-fetch --status skipped
    conductor.py approve --session <dir>
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import validate_flow as vf  # noqa: E402

TEMPLATES_PATH = Path(__file__).with_name("templates.json")


def _load_templates_full() -> dict:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))["templates"]


def _example_scripts_is_list(session_dir: Path) -> bool:
    try:
        ex = json.loads((session_dir / "requirements.json").read_text(encoding="utf-8")).get("example_scripts")
        return isinstance(ex, list) and len(ex) > 0
    except Exception:
        return False


def _keep_step(step: dict, session_dir: Path) -> bool:
    cond = step.get("when")
    if cond is None:
        return True
    if cond == "example_scripts_is_list":
        return _example_scripts_is_list(session_dir)
    return True  # unknown condition → keep (fail open)


def _artifact_present(session_dir: Path, artifact: str) -> bool:
    """Session artifacts live under session_dir. Repo-level needs (those with a
    '/' that aren't a trailing-slash dir, e.g. profile/preferences.md) are
    treated as optional → considered satisfied. Glob patterns (e.g.
    '*.openreel.json') are present iff any file in the session matches."""
    if artifact.endswith("/"):
        return (session_dir / artifact).is_dir()
    if "/" in artifact:
        return True  # repo-level optional need
    if any(ch in artifact for ch in "*?["):
        return any(session_dir.glob(artifact))
    return (session_dir / artifact).exists()


def build(session_dir: Path, template_name: str) -> dict:
    templates = _load_templates_full()
    if template_name not in templates:
        raise ValueError(f"unknown template '{template_name}' (have: {', '.join(templates)})")
    contracts = vf.load_contracts()

    raw_steps = [s for s in templates[template_name]["steps"] if _keep_step(s, session_dir)]

    tokens: list[str] = []
    steps: list[dict] = []
    for i, s in enumerate(raw_steps, 1):
        token = vf._step_token(s)
        tokens.append(token)
        needs, produces, errs = vf.resolve_step(contracts, token)
        if errs:
            raise ValueError(f"step '{token}': {'; '.join(errs)}")
        steps.append({
            "order": i, "skill": s["skill"], "mode": s.get("mode"),
            "token": token, "needs": needs, "produces": produces,
            "parallel": bool(s.get("parallel", False)), "status": "pending",
        })

    ok, errors = vf.validate_flow(contracts, tokens)
    if not ok:
        raise ValueError("template does not validate against contracts:\n  - " + "\n  - ".join(errors))

    pipeline = {
        "session_id": session_dir.name,
        "created_at": datetime.now().isoformat(),
        "template": template_name,
        "goal": contracts["goal_artifact"],
        "approved": False,
        "steps": steps,
    }
    (session_dir / "pipeline.json").write_text(
        json.dumps(pipeline, indent=2, ensure_ascii=False), encoding="utf-8")
    return pipeline


def _load_pipeline(session_dir: Path) -> dict:
    p = session_dir / "pipeline.json"
    if not p.exists():
        raise FileNotFoundError("pipeline.json missing — run `conductor.py build` first")
    return json.loads(p.read_text(encoding="utf-8"))


def _done(session_dir: Path, step: dict) -> bool:
    prod = step.get("produces", [])
    return bool(prod) and all(_artifact_present(session_dir, a) for a in prod)


def _ready(session_dir: Path, step: dict) -> bool:
    return all(_artifact_present(session_dir, a) for a in step.get("needs", []))


def next_step(session_dir: Path) -> dict:
    pipe = _load_pipeline(session_dir)
    pending = []
    for step in pipe["steps"]:
        if step.get("status") == "skipped" or _done(session_dir, step):
            continue
        pending.append(step)
        if _ready(session_dir, step):
            return {"next": step["token"], "skill": step["skill"], "mode": step["mode"],
                    "parallel": step["parallel"], "needs": step["needs"], "produces": step["produces"]}
    if not pending:
        return {"done": True, "goal": pipe["goal"]}
    blocked = pending[0]
    missing = [a for a in blocked["needs"] if not _artifact_present(session_dir, a)]
    return {"blocked": blocked["token"], "missing": missing}


def mark(session_dir: Path, token: str, status: str) -> dict:
    pipe = _load_pipeline(session_dir)
    hit = False
    for step in pipe["steps"]:
        if step["token"] == token:
            step["status"] = status
            hit = True
    if not hit:
        raise ValueError(f"no step '{token}' in pipeline.json")
    (session_dir / "pipeline.json").write_text(
        json.dumps(pipe, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "step": token, "status": status}


def approve(session_dir: Path) -> dict:
    pipe = _load_pipeline(session_dir)
    pipe["approved"] = True
    (session_dir / "pipeline.json").write_text(
        json.dumps(pipe, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "approved": True}


def show(session_dir: Path) -> dict:
    pipe = _load_pipeline(session_dir)
    rows = []
    for step in pipe["steps"]:
        if step.get("status") == "skipped":
            state = "skipped"
        elif _done(session_dir, step):
            state = "done"
        elif _ready(session_dir, step):
            state = "ready"
        else:
            state = "blocked"
        rows.append((step["order"], step["token"], state, "(parallel)" if step["parallel"] else ""))
    return {"template": pipe["template"], "approved": pipe["approved"], "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser(description="ESTA pipeline conductor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("templates", help="List available flow templates")
    b = sub.add_parser("build", help="Build pipeline.json from a template")
    b.add_argument("--session", required=True)
    b.add_argument("--template", required=True)
    for name in ("show", "next", "approve"):
        sp = sub.add_parser(name)
        sp.add_argument("--session", required=True)
    m = sub.add_parser("mark")
    m.add_argument("--session", required=True)
    m.add_argument("--step", required=True)
    m.add_argument("--status", required=True, choices=["pending", "skipped", "done"])
    args = ap.parse_args()

    try:
        if args.cmd == "templates":
            t = _load_templates_full()
            print(json.dumps({n: t[n]["description"] for n in t}, indent=2))
        elif args.cmd == "build":
            pipe = build(Path(args.session), args.template)
            print(json.dumps({"ok": True, "template": pipe["template"],
                              "steps": [s["token"] for s in pipe["steps"]]}))
        elif args.cmd == "show":
            r = show(Path(args.session))
            print(f"template: {r['template']}  approved: {r['approved']}")
            for order, token, state, par in r["rows"]:
                print(f"  {order:2d}. [{state:7s}] {token} {par}")
        elif args.cmd == "next":
            print(json.dumps(next_step(Path(args.session))))
        elif args.cmd == "mark":
            print(json.dumps(mark(Path(args.session), args.step, args.status)))
        elif args.cmd == "approve":
            print(json.dumps(approve(Path(args.session))))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
