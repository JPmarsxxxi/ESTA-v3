"""Start, check and stop the live Qwen vision server on Kaggle (SPEC.md Part 10).

    python tools/vision_server/run.py up        # push the kernel, wait until /health says ready
    python tools/vision_server/run.py status    # /health plus the Kaggle kernel status
    python tools/vision_server/run.py down      # POST /shutdown

System python (the Kaggle CLI lives there). The kernel slug is fixed, so a Kaggle secret attached to it once
stays attached. The bearer token is new on every `up` and lives in .esta/vision_server.json.
"""

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import ACCELERATORS, kaggle_username, kernel_status, push_kernel, use_utf8_stdout, write_kernel_dir  # noqa: E402
from tools.match.common import load_config  # noqa: E402
from tools.vision_server import client  # noqa: E402

use_utf8_stdout()
HERE = Path(__file__).resolve().parent
SLUG = "esta-vision-server"
BUILD = client.REPO_ROOT / "cache" / "vision_server" / "kernel_build"


def _state() -> dict:
    try:
        return json.loads(client.STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def up(wait_min: int, try_vllm: bool) -> int:
    cfg = load_config()
    url = client.config()["url"]
    if not url:
        sys.exit("set vision.url in config.yaml (the ngrok static domain, https://...)")
    h = client.health(10)
    if h and h.get("ready"):
        print(f"already up: {h['mode']} {h['model']} on {h['gpus']}")
        return 0
    kernel = f"{kaggle_username()}/{SLUG}"
    token = secrets.token_urlsafe(24)
    conf = {"model": client.MODEL, "token": token, "domain": url.split("://", 1)[-1],
            "hf_token": (cfg.get("apis") or {}).get("hf_token") or "",
            # Used only when no NGROK_AUTHTOKEN / NGROK_TOKEN Kaggle secret is attached (the kernel stays private).
            "ngrok_token": cfg.get("ngrok_token") or "", "try_vllm": try_vllm}
    code = (HERE / "kernel.py").read_text(encoding="utf-8").replace("CONFIG = {}  # replaced by run.py",
                                                                      "CONFIG = " + repr(conf), 1)
    write_kernel_dir(BUILD, code, kernel, ACCELERATORS["t4"])
    client.STATE.parent.mkdir(parents=True, exist_ok=True)
    client.STATE.write_text(json.dumps({"token": token, "kernel": kernel, "pushed_at": time.time()}), encoding="utf-8")
    ok, out = push_kernel(BUILD)
    if not ok:
        sys.exit(f"kernel push failed: {out}")
    print(f"pushed {kernel}; waiting for {url}/health (up to {wait_min} min)", flush=True)
    t0, last = time.time(), ""
    while time.time() - t0 < wait_min * 60:
        time.sleep(30)
        h = client.health(15)
        if h:
            if h.get("stage") != last:
                last = h.get("stage")
                print(f"  {round((time.time() - t0) / 60, 1)} min: {last} {h.get('mode') or ''}", flush=True)
            if h.get("ready"):
                print(f"ready: {h['mode']} {h['model']} on {h['gpus']}")
                return 0
            if h.get("error"):
                print(f"kernel error: {h['error']}")
        else:
            state, _ = kernel_status(kernel)
            if state in ("error", "complete", "cancel"):
                print(f"kernel stopped ({state}) before the server came up; see https://www.kaggle.com/code/{kernel}")
                return 1
    print("timed out waiting for the server")
    return 1


def status() -> int:
    st = _state()
    h = client.health(15)
    k = kernel_status(st["kernel"])[0] if st.get("kernel") else ""
    print(json.dumps({"kernel": st.get("kernel"), "kaggle": k, "health": h}, indent=1))
    return 0 if h and h.get("ready") else 1


def down() -> int:
    try:
        client._request("/shutdown", {}, 15)
        print("shutdown sent")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"shutdown failed: {e}")
        return 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["up", "status", "down"])
    ap.add_argument("--wait", type=int, default=60, help="minutes to wait for ready")
    ap.add_argument("--no-vllm", action="store_true", help="go straight to the transformers batching server")
    a = ap.parse_args()
    sys.exit(up(a.wait, not a.no_vllm) if a.cmd == "up" else status() if a.cmd == "status" else down())


if __name__ == "__main__":
    main()
