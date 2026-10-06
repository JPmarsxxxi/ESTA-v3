"""Shared results.md writer for the M5.1 bake-off, used by kaggle.py apply and
local_check.py so both write into the same file without duplicating table logic."""

import json
from pathlib import Path

from tools.match.bakeoff.common import HERE

RESULTS_PATH = HERE / "results.md"

BARS = {"cuts": 0.90, "tags": 0.85, "theme": 0.80}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def write_job_table(job_name: str, metric_name: str, bar: float, rows: list[dict],
                    winner: str, why: str, dropped: list[str] | None = None) -> None:
    """rows: [{"candidate", "score", "sec_per_min", "gpu_min", "support"(optional)}]."""
    table_rows = []
    for r in sorted(rows, key=lambda x: -x["score"]):
        passed = "PASS" if r["score"] >= bar else "fail"
        mark = " **<- winner**" if r["candidate"] == winner else ""
        support = f", n={r['support']}" if "support" in r else ""
        table_rows.append([r["candidate"], f"{r['score']:.3f}{support}",
                          f"{r.get('sec_per_min', 0):.1f}", f"{r.get('gpu_min', 0):.2f}",
                          passed + mark])
    section = [f"### {job_name} (bar: {metric_name} >= {bar})", "",
              _table(["candidate", metric_name, "sec/min video", "GPU-min", "status"], table_rows),
              "", f"**Winner: {winner or 'none'}** — {why}"]
    if dropped:
        section.append("")
        section.append("Dropped (no candidate cleared the bar): " + ", ".join(dropped))
    _append("\n".join(section) + "\n")


def append_local_timing(job_name: str, model_name: str, seconds_per_min: float, device: str) -> None:
    _append(f"\n**Local timing ({job_name}, {model_name}):** {seconds_per_min:.2f} s/min "
           f"of video, on {device}.\n")


def append_writeback_log(winners: dict, timestamp: str, dropped: list[str]) -> None:
    lines = ["\n## Config write-back", "", f"Approved {timestamp}. Winners written to "
            "`config.yaml` `match.models`:", ""]
    for k, v in winners.items():
        lines.append(f"- `{k}`: `{v}`")
    if dropped:
        lines.append("")
        lines.append("Dropped (no passing candidate): " + ", ".join(dropped))
    _append("\n".join(lines) + "\n")


def _append(text: str) -> None:
    with open(RESULTS_PATH, "a", encoding="utf-8") as fh:
        fh.write(text)


def start_fresh(summary: dict) -> None:
    RESULTS_PATH.write_text(
        f"# M5.1 bake-off results\n\n{json.dumps(summary, indent=2)}\n\n", encoding="utf-8")
