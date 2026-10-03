"""Haiku lane: batches of keyframes through `claude -p`, same prompt as Gemma. Usage: python haiku.py [max_batches]"""
import base64
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path(__file__).parent
BATCH = 10
SYSTEM = "You label video keyframes. Read each image file you are given, then reply with only the requested JSON."


def run_batch(batch: list[dict]) -> dict:
    # Images go inline in one user message, so the batch is a single model turn
    # instead of one Read tool turn per image.
    content = []
    speech = json.loads((OUT / "speech.json").read_text(encoding="utf-8")) if (OUT / "speech.json").exists() else {}
    for s in batch:
        said = speech.get(s["id"], "")
        content.append({"type": "text", "text": f"Shot {s['id']}" + (f' (spoken over it: "{said}")' if said else "") + ":"})
        data = base64.b64encode((OUT / "frames" / f"{s['id']}.jpg").read_bytes()).decode()
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}})
    content.append({"type": "text", "text": (OUT / "prompt.txt").read_text(encoding="utf-8")
                    + "\n\nThe words spoken over a shot are the voiceover the editor was illustrating: use them to judge "
                    "what the shot is meant to show and where an editor would have found it. Stock sites hold generic "
                    "clean clips; youtube is for specific real people, events, shows and recognisable footage."
                    + f"\n\nThere are {len(batch)} keyframes above, one per shot. Reply with ONLY one JSON object "
                    "mapping each shot id to its answer object, e.g. {\"i001\": {\"description\": ..., "
                    "\"likely_sources\": [...]}}."})
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    t0 = time.time()
    r = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--input-format", "stream-json", "--output-format", "stream-json",
         "--verbose", "--system-prompt", SYSTEM, "--tools", "", "--max-turns", "1",
         # Without these every call carries ~29k tokens of MCP tool definitions and skills.
         "--strict-mcp-config", "--setting-sources", ""],
        input=msg + "\n", capture_output=True, text=True, encoding="utf-8", timeout=900, shell=True)
    try:
        env = [json.loads(line) for line in r.stdout.splitlines() if line.startswith("{")]
        env = next(e for e in env if e.get("type") == "result")
        text = env.get("result", "")
        ans = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except Exception as e:  # noqa: BLE001
        return {"ids": [s["id"] for s in batch], "error": f"{e}: {(r.stdout or r.stderr)[-300:]}", "secs": time.time() - t0}
    return {"answers": ans, "cost": env.get("total_cost_usd", 0), "secs": time.time() - t0,
            "usage": env.get("usage", {})}


def main() -> None:
    shots = json.loads((OUT / "shots.json").read_text(encoding="utf-8"))
    batches = [shots[i:i + BATCH] for i in range(0, len(shots), BATCH)]
    if len(sys.argv) > 1:
        batches = batches[: int(sys.argv[1])]
    t0 = time.time()
    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(run_batch, batches))
    answers, errors = {}, []
    for res in results:
        answers.update(res.get("answers", {}))
        if "error" in res:
            errors.append(res)
    summary = {"answers": answers, "errors": errors, "cost_usd": round(sum(r.get("cost", 0) for r in results), 4),
               "wall_secs": round(time.time() - t0, 1), "batch_secs": [round(r["secs"], 1) for r in results]}
    (OUT / "haiku_results.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(answers)} answers, {len(errors)} failed batches, ${summary['cost_usd']}, {summary['wall_secs']}s")


if __name__ == "__main__":
    main()
