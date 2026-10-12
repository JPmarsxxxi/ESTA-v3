# ESTA vision server (SPEC.md Part 10): Qwen3.5-9B on Kaggle's free 2xT4, live behind an ngrok static domain.
# run.py pushes this file as a notebook with CONFIG filled in. A front server on :8000 checks the bearer
# token, answers /health and /shutdown, and forwards /v1/chat/completions to vLLM (:8001) or, when vLLM won't
# run the model on the T4s, to a transformers worker that batches waiting requests.
import base64
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONFIG = {}  # replaced by run.py
MODEL = CONFIG.get("model", "Qwen/Qwen3.5-9B")
TOKEN = CONFIG.get("token", "")
IDLE_SECS = CONFIG.get("idle_secs", 1200)
MAX_SECS = CONFIG.get("max_secs", 41400)
BATCH, WINDOW, BATCH_IMAGES = 8, 0.15, 24
T0 = time.time()
STATE = {"ready": False, "stage": "starting", "mode": "", "model": MODEL, "error": "", "served": 0, "failed": 0,
         "gpus": [], "log": []}
LAST = [time.time()]
JOBS: "queue.Queue" = queue.Queue()
os.environ["HF_HOME"] = "/kaggle/temp/hf"
if CONFIG.get("hf_token"):
    os.environ["HF_TOKEN"] = CONFIG["hf_token"]


def log(msg):
    line = "%6.0fs %s" % (time.time() - T0, msg)
    print(line, flush=True)
    STATE["log"] = (STATE["log"] + [line])[-30:]


def stage(s):
    STATE["stage"] = s
    log("stage: " + s)


def stop(code=0):
    log("shutting down")
    try:
        from pyngrok import ngrok
        ngrok.kill()
    except Exception:
        pass
    os._exit(code)


class Front(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self._send(401, {"error": "bad token"})
            return False
        return True

    def do_GET(self):
        if not self._authed():
            return
        if self.path.startswith("/health"):
            return self._send(200, {**STATE, "uptime_s": round(time.time() - T0), "idle_s": round(time.time() - LAST[0])})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._authed():
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path.startswith("/shutdown"):
            self._send(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(1), stop()), daemon=True).start()
            return
        if not self.path.startswith("/v1/chat/completions"):
            return self._send(404, {"error": "not found"})
        if not STATE["ready"]:
            return self._send(503, {"error": "not ready: " + STATE["stage"]})
        LAST[0] = time.time()
        try:
            if STATE["mode"] == "vllm":
                req = urllib.request.Request("http://127.0.0.1:8001/v1/chat/completions", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=600) as r:
                    out = json.loads(r.read())
            else:
                slot = {"req": json.loads(body), "done": threading.Event()}
                JOBS.put(slot)
                slot["done"].wait(900)
                if "out" not in slot:
                    raise RuntimeError(slot.get("error", "timed out in queue"))
                out = slot["out"]
            STATE["served"] += 1
            self._send(200, out)
        except Exception as e:
            STATE["failed"] += 1
            log("request failed: %s" % e)
            self._send(500, {"error": str(e)[:300]})
        LAST[0] = time.time()


def watchdog():
    while True:
        time.sleep(30)
        if time.time() - T0 > MAX_SECS:
            log("max runtime reached")
            stop()
        if STATE["ready"] and time.time() - LAST[0] > IDLE_SECS:
            log("idle for %ds" % IDLE_SECS)
            stop()


def tunnel():
    secret = ""
    try:
        from kaggle_secrets import UserSecretsClient
        for name in ("NGROK_AUTHTOKEN", "NGROK_TOKEN"):
            try:
                secret = UserSecretsClient().get_secret(name)
                if secret:
                    log("ngrok token from Kaggle secret " + name)
                    break
            except Exception:
                pass
    except Exception:
        pass
    token = secret or CONFIG.get("ngrok_token", "")
    if not token:
        STATE["error"] = "NGROK_AUTHTOKEN secret missing: attach it in the kernel editor"
        log(STATE["error"])
        stop(1)
    from pyngrok import conf, ngrok
    conf.get_default().auth_token = token
    try:
        t = ngrok.connect(8000, "http", domain=CONFIG["domain"])
    except Exception as e:
        STATE["error"] = "ngrok failed (domain in use?): %s" % e
        log(STATE["error"])
        stop(1)
    log("tunnel up: %s" % t.public_url)


def vllm():
    """vLLM in its own venv, so a failed install can't break the system torch the fallback needs."""
    stage("installing vllm")
    venv = "/kaggle/temp/vllm"
    # Kaggle's python has no ensurepip, so `python -m venv` fails; uv builds the venv without it.
    r = subprocess.run("%s -m pip install -q uv && %s -m uv venv %s && %s -m uv pip install -q --python %s/bin/python vllm"
                       % (sys.executable, sys.executable, venv, sys.executable, venv), shell=True,
                       capture_output=True, text=True, timeout=1500)
    if r.returncode:
        log("vllm install failed: " + (r.stderr or r.stdout)[-800:])
        return False
    stage("loading model in vllm")
    cmd = [venv + "/bin/vllm", "serve", MODEL, "--dtype", "half", "--tensor-parallel-size", "2", "--port", "8001",
           "--max-model-len", "16384", "--gpu-memory-utilization", "0.92", "--limit-mm-per-prompt", '{"image": 40}',
           "--max-num-seqs", "16", "--served-model-name", MODEL]
    logf = open("/kaggle/working/vllm.log", "w")
    proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env={**os.environ, "VLLM_USE_V1": "1"})
    deadline = time.time() + 1800
    while time.time() < deadline:
        if proc.poll() is not None:
            log("vllm exited %s: %s" % (proc.returncode, open("/kaggle/working/vllm.log").read()[-1500:]))
            return False
        try:
            with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=5) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(10)
    else:
        log("vllm never became healthy")
        proc.kill()
        return False
    # One real call: a server that loads but can't answer is no good.
    try:
        probe = json.dumps({"model": MODEL, "max_tokens": 8, "messages": [{"role": "user", "content": "Say ok"}],
                            "chat_template_kwargs": {"enable_thinking": False}}).encode()
        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8001/v1/chat/completions", data=probe,
                                                           headers={"Content-Type": "application/json"}), timeout=300) as r:
            log("vllm probe: %s" % json.loads(r.read())["choices"][0]["message"]["content"][:40])
    except Exception as e:
        log("vllm probe failed: %s" % e)
        proc.kill()
        return False
    return True


def transformers_worker():
    stage("loading model in transformers")
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor
    processor = AutoProcessor.from_pretrained(MODEL)
    processor.tokenizer.padding_side = "left"
    model = AutoModelForImageTextToText.from_pretrained(MODEL, dtype=torch.float16, device_map="auto")
    model.eval()

    def image(url):
        im = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
        im.thumbnail((768, 768))
        return im

    def prepare(req):
        msgs, images = [], []
        for m in req["messages"]:
            if isinstance(m["content"], str):
                msgs.append({"role": m["role"], "content": [{"type": "text", "text": m["content"]}]})
                continue
            parts = []
            for b in m["content"]:
                if b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                else:
                    images.append(image(b["image_url"]["url"]))
                    parts.append({"type": "image"})
            msgs.append({"role": m["role"], "content": parts})
        try:
            text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        except TypeError:
            text = processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        return text, images

    def generate(slots):
        prepped = [prepare(s["req"]) for s in slots]
        texts = [p[0] for p in prepped]
        flat = [im for p in prepped for im in p[1]]
        inputs = processor(text=texts, images=flat or None, return_tensors="pt", padding=True).to(model.device)
        max_new = min(max(int(s["req"].get("max_tokens") or 1024) for s in slots), 4096)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=max_new, do_sample=False, repetition_penalty=1.05)
        n_in = inputs["input_ids"].shape[1]
        for s, row in zip(slots, out):
            text = processor.decode(row[n_in:], skip_special_tokens=True)
            s["out"] = {"choices": [{"message": {"role": "assistant", "content": text}}],
                        "usage": {"prompt_tokens": int(n_in), "completion_tokens": int((row[n_in:] != processor.tokenizer.pad_token_id).sum())}}

    STATE.update(mode="transformers", ready=True)
    stage("ready")
    while True:
        slots = [JOBS.get()]
        end = time.time() + WINDOW
        while len(slots) < BATCH and time.time() < end:
            try:
                slots.append(JOBS.get(timeout=max(0.0, end - time.time())))
            except queue.Empty:
                break
        # Judge calls carry ~30 images each: cap the images per batch so one batch can't run the T4s out of memory.
        batches, cur, n_img = [], [], 0
        for s in slots:
            k = sum(1 for m in s["req"]["messages"] if not isinstance(m["content"], str)
                    for b in m["content"] if b["type"] == "image_url")
            if cur and n_img + k > BATCH_IMAGES:
                batches.append(cur)
                cur, n_img = [], 0
            cur.append(s)
            n_img += k
        batches.append(cur)
        for b in batches:
            try:
                generate(b)
            except Exception as e:
                torch.cuda.empty_cache()
                log("batch of %d failed (%s); one at a time" % (len(b), str(e)[:120]))
                for s in b:
                    try:
                        generate([s])
                    except Exception as e1:
                        torch.cuda.empty_cache()
                        s["error"] = str(e1)[:300]
            for s in b:
                s["done"].set()


def main():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pyngrok"], check=False)
    try:
        import torch
        STATE["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
    except Exception:
        pass
    log("gpus: %s" % STATE["gpus"])
    threading.Thread(target=ThreadingHTTPServer(("0.0.0.0", 8000), Front).serve_forever, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    tunnel()
    try:
        if CONFIG.get("try_vllm", True) and vllm():
            STATE.update(mode="vllm", ready=True)
            stage("ready")
            while True:
                time.sleep(60)
        log("falling back to the transformers batching server")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "transformers", "accelerate"], check=False)
        transformers_worker()
    except Exception:
        STATE["error"] = traceback.format_exc()[-1500:]
        log(STATE["error"])
        time.sleep(600)
        stop(1)


main()
