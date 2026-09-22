"""Validate that an ordered pipeline flow satisfies every skill's I/O contract.

Phase 1 of notes/smart-pipeline-and-found-audio.md. This is the seed of the
conductor's "validate any custom order before running it" capability: a flow is
valid iff, walking it in order, every skill's `needs` are already produced by an
earlier skill (or were present at session start). It also confirms the flow
reaches the goal artifact (*.openreel.json).

Stdlib only — no conda env needed.

    python tools/pipeline/validate_flow.py                 # self-test the known flows
    python tools/pipeline/validate_flow.py requirements research scriptwriter:author \
        audio:clone timestamps style-analysis plan assets render
"""

import fnmatch
import json
import sys
from pathlib import Path

CONTRACTS_PATH = Path(__file__).with_name("contracts.json")
TEMPLATES_PATH = Path(__file__).with_name("templates.json")

# Artifacts that may already exist at session start (e.g. user-uploaded script),
# so a flow needing them is not automatically invalid. Empty for now.
SESSION_SEED: set[str] = set()


def load_contracts() -> dict:
    return json.loads(CONTRACTS_PATH.read_text(encoding="utf-8"))


def _step_token(step: dict) -> str:
    return f"{step['skill']}:{step['mode']}" if step.get("mode") else step["skill"]


def load_templates() -> dict[str, list[str]]:
    """Flow templates from templates.json, flattened to skill[:mode] step lists.
    Single source of truth shared with the conductor."""
    data = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))
    return {
        name: [_step_token(s) for s in tpl["steps"]]
        for name, tpl in data["templates"].items()
    }


def resolve_step(contracts: dict, step: str) -> tuple[list[str], list[str], list[str]]:
    """Return (needs, produces, errors) for a 'skill' or 'skill:mode' step."""
    errors: list[str] = []
    skill_name, _, mode = step.partition(":")
    skill = contracts["skills"].get(skill_name)
    if not skill:
        return [], [], [f"unknown skill '{skill_name}'"]

    base_needs = skill.get("needs", skill.get("base_needs", []))
    base_produces = skill.get("produces", skill.get("base_produces", []))
    modes = skill.get("modes")

    if modes:
        if not mode:
            mode = skill.get("default_mode", "")
        if not mode:
            return [], [], [f"skill '{skill_name}' requires a mode ({'/'.join(modes)})"]
        m = modes.get(mode)
        if not m:
            return [], [], [f"skill '{skill_name}' has no mode '{mode}' ({'/'.join(modes)})"]
        if m.get("status") == "not_built":
            errors.append(f"{step}: mode is not_built")
        needs = m.get("needs", base_needs)
        produces = m.get("produces", base_produces) + m.get("produces_dirs", [])
    elif mode:
        return [], [], [f"skill '{skill_name}' takes no mode (got '{mode}')"]
    else:
        needs = base_needs
        produces = base_produces + skill.get("produces_dirs", [])

    return needs, produces, errors


def _satisfied(produced: set[str], artifact: str) -> bool:
    """An artifact need is satisfied if literally produced, or if its glob
    pattern matches any produced item (and vice versa — a produced glob like
    '*.openreel.json' satisfies a literal '<x>.openreel.json' need)."""
    if artifact in produced:
        return True
    if any(ch in artifact for ch in "*?["):
        return any(fnmatch.fnmatchcase(p, artifact) for p in produced)
    return any(
        any(ch in p for ch in "*?[") and fnmatch.fnmatchcase(artifact, p)
        for p in produced
    )


def validate_flow(contracts: dict, steps: list[str]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    produced: set[str] = set(SESSION_SEED)
    goal = contracts["goal_artifact"]

    for step in steps:
        needs, produces, step_errs = resolve_step(contracts, step)
        errors.extend(step_errs)
        for need in needs:
            if not _satisfied(produced, need):
                errors.append(f"{step}: needs '{need}' but nothing earlier produces it")
        produced.update(produces)

    if not _satisfied(produced, goal):
        errors.append(f"flow never produces the goal artifact '{goal}'")

    return (len(errors) == 0), errors


def main() -> None:
    contracts = load_contracts()

    if len(sys.argv) > 1:
        steps = sys.argv[1:]
        ok, errors = validate_flow(contracts, steps)
        print(f"flow: {' -> '.join(steps)}")
        print("  VALID" if ok else "  INVALID")
        for e in errors:
            print(f"  - {e}")
        sys.exit(0 if ok else 1)

    # Self-test the known flows.
    all_ok = True
    for name, steps in load_templates().items():
        ok, errors = validate_flow(contracts, steps)
        all_ok = all_ok and ok
        print(f"[{'VALID  ' if ok else 'INVALID'}] {name}")
        for e in errors:
            print(f"    - {e}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
