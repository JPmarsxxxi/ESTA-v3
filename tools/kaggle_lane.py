"""Shared Kaggle-as-free-GPU plumbing.

Both `tools/genvideo` (animate a shot) and `tools/genchar` (design a character)
offload to Kaggle's free GPU the same way, so the push/status/output mechanics
live here once. See tools/genvideo/run.py's module docstring for why Kaggle and
not Colab.

The one non-obvious rule, learned the expensive way: **the kernel title must BE
the slug.** Kaggle derives the real kernel slug by slugifying the title and
silently ignores an `id` in kernel-metadata.json that disagrees. A prettier
title parks the notebook at an address `status`/`output` can't reach, and the
failure surfaces as a misleading "Permission 'kernels.get' was denied".
"""

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The `kaggle` console script isn't reliably executable from this repo's shells
# on Windows, but the module entry point always is.
KAGGLE = [sys.executable, "-m", "kaggle"]

# Kaggle machine_shape values, from the kernel-metadata schema. Both free
# accelerators are 16 GB and neither has native bf16 (T4 is Turing, P100 Pascal).
ACCELERATORS = {"t4": "NvidiaTeslaT4", "p100": "NvidiaTeslaP100"}


def use_utf8_stdout() -> None:
    """Pin utf-8 on stdout/stderr.

    These CLIs emit JSON containing prompt text straight out of plan.json —
    em-dashes, smart quotes — and Windows defaults stdout to cp1252, which
    raises on them.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # already wrapped, or not a TextIO
            pass


def run_kaggle(*args: str, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run the Kaggle CLI with UTF-8 forced inside the child process.

    Decoding its output as utf-8 isn't enough: `kernels output` *writes* the run
    log to disk itself, and on Windows it does that in cp1252 and dies on any
    non-Latin-1 byte — which a PyTorch traceback reliably contains. PYTHONUTF8
    makes the child use utf-8 for its own file I/O too.
    """
    import os
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([*KAGGLE, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=env)


def kaggle_username() -> str:
    for path in (Path.home() / ".kaggle" / "kaggle.json",
                 Path.home() / ".config" / "kaggle" / "kaggle.json"):
        if path.exists():
            name = json.loads(path.read_text(encoding="utf-8")).get("username", "")
            if name:
                return name
    raise RuntimeError("no kaggle.json found — put your API token in ~/.kaggle/kaggle.json")


def slugify(*parts: str, prefix: str = "") -> str:
    """Kaggle kernel slugs are lowercase alphanumeric + dashes, max ~50 chars."""
    joined = "-".join(p for p in parts if p)
    s = re.sub(r"[^a-z0-9]+", "-", joined.lower()).strip("-")
    return (prefix + s)[:50].rstrip("-")


def write_kernel_dir(build_dir: Path, code: str, kernel_id: str,
                     accelerator: str, enable_internet: bool = True) -> Path:
    """Write the .ipynb + kernel-metadata.json that `kaggle kernels push` wants.

    The title is derived from `kernel_id` on purpose — see the module docstring.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    slug = kernel_id.split("/", 1)[-1]
    notebook = {
        "cells": [{
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": code.splitlines(keepends=True),
        }],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.10.0"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    nb_path = build_dir / "kernel.ipynb"
    nb_path.write_text(json.dumps(notebook), encoding="utf-8")

    (build_dir / "kernel-metadata.json").write_text(json.dumps({
        "id": kernel_id,
        "title": slug,          # must equal the slug — see module docstring
        "code_file": "kernel.ipynb",
        "language": "python",
        "kernel_type": "notebook",
        "is_private": "true",
        "enable_gpu": "true",
        "enable_internet": "true" if enable_internet else "false",
        "machine_shape": accelerator,
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
    }, indent=2), encoding="utf-8")
    return nb_path


def push_kernel(build_dir: Path) -> tuple[bool, str]:
    res = run_kaggle("kernels", "push", "-p", str(build_dir))
    blob = ((res.stdout or "") + (res.stderr or "")).strip()
    return res.returncode == 0 and "successfully pushed" in blob.lower(), blob[-500:]


def kernel_status(ref: str) -> tuple[str, str]:
    """-> (state, raw). state is one of queued/running/complete/error/cancel/''.

    `''` means "no state could be read" — a transport failure, not a verdict —
    and callers should keep polling rather than treat it as terminal.

    Two traps this has to avoid, both hit for real. (1) A failed API call must
    never be read as a failed KERNEL: an SSL drop prints a message containing
    the word "error", and substring-matching that killed a poller while the run
    itself carried on for another half hour. So a non-zero exit returns no state
    at all. (2) The real output is `... has status "KernelWorkerStatus.RUNNING"`,
    so the quoted token is parsed first; loose substring matching stays only as
    a fallback for older CLI phrasings, and is ordered longest-first so
    "cancelRequested" can't be shadowed.
    """
    res = run_kaggle("kernels", "status", ref, timeout=120)
    blob = ((res.stdout or "") + (res.stderr or "")).strip()
    if res.returncode != 0:
        return "", blob[-400:]

    if m := re.search(r"KernelWorkerStatus\.([A-Z_]+)", blob):
        token = m.group(1).lower()
        return ({"cancelacknowledged": "cancel", "cancelrequested": "cancel"}
                .get(token, token)), blob[-400:]

    for candidate in ("complete", "running", "queued", "cancel", "error"):
        if candidate in blob.lower():
            return candidate, blob[-400:]
    return "", blob[-400:]


def fetch_output(ref: str, out_dir: Path, timeout: int = 1800) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    res = run_kaggle("kernels", "output", ref, "-p", str(out_dir), "-o", timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"kernels output failed: {(res.stderr or res.stdout)[-300:]}")


def ensure_dataset(build_dir: Path, dataset_id: str, title: str,
                   notes: str = "update") -> tuple[bool, str]:
    """Create the dataset, or push a new version if it already exists.

    Datasets are how bulk files reach a kernel — anything past a few hundred KB
    is too big to inline in the notebook source. Private by default (the CLI's
    default; we never pass --public), and mounted read-only at
    /kaggle/input/<slug>/ for any kernel listing it in `dataset_sources`.
    """
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "dataset-metadata.json").write_text(json.dumps({
        "id": dataset_id,
        "title": title,
        "licenses": [{"name": "CC0-1.0"}],
    }, indent=2), encoding="utf-8")

    create = run_kaggle("datasets", "create", "-p", str(build_dir), "-q", timeout=1800)
    blob = ((create.stdout or "") + (create.stderr or "")).strip()
    if create.returncode == 0 and "error" not in blob.lower():
        return True, blob[-400:]

    # Already exists (or a create race) — push a version instead.
    version = run_kaggle("datasets", "version", "-p", str(build_dir),
                         "-m", notes, "-q", "--dir-mode", "skip", timeout=1800)
    vblob = ((version.stdout or "") + (version.stderr or "")).strip()
    return version.returncode == 0, (blob + " || " + vblob)[-400:]


def wait_dataset_ready(dataset_id: str, timeout: int = 600, interval: int = 15) -> bool:
    """Block until a freshly uploaded dataset finishes processing.

    Necessary because `datasets create` returns as soon as the bytes are up, but
    the dataset can't be attached to a kernel until Kaggle has processed it.
    Push a kernel too early and it succeeds while silently dropping the source —
    "The following are not valid dataset sources" is a warning, not an error, so
    the run starts and then fails with no input data.
    """
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = run_kaggle("datasets", "status", dataset_id, timeout=120)
        state = ((res.stdout or "") + (res.stderr or "")).strip().lower()
        if "ready" in state:
            return True
        if "error" in state:
            return False
        time.sleep(interval)
    return False


def notebook_code(template: str, **subs: str) -> str:
    """Fill a notebook template by __PLACEHOLDER__ substitution.

    Substitution rather than an f-string because these templates are full of
    dict literals, and doubling every brace to survive .format() is how this
    kind of template rots.
    """
    code = template
    for key, value in subs.items():
        code = code.replace(f"__{key.upper()}__", value)
    return code
