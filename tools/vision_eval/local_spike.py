"""Run the local llama-server replay (SPEC.md Part 8) only while the user's pipeline jobs leave the GPU free.

Waits until no autopick/assets/render python process has existed for 5 minutes, starts
llama-server for one model, replays the sample, and pauses (kills the server) whenever
a pipeline job reappears. Resumable: replay.py skips items already done.
"""
import subprocess, sys, time, json
from pathlib import Path

LLAMA = Path(r"D:\esta-perf\llama\llama-server.exe")
MODELS = Path(r"D:\esta-perf\models")
REPO = Path(r"D:\ESTA-v3-perf")
SET = r"D:\esta-perf\vision_eval\do-alphas"
RUNS = [
    ("qwen3vl-4b-local", "Qwen3-VL-4B-Instruct-GGUF__Qwen3VL-4B-Instruct-Q4_K_M.gguf", "Qwen3-VL-4B-Instruct-GGUF__mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf", []),
    ("qwen35-4b-local", "Qwen3.5-4B-GGUF__Qwen3.5-4B-Q4_K_M.gguf", "Qwen3.5-4B-GGUF__mmproj-F16.gguf", ["--chat-template-kwargs", '{"enable_thinking": false}']),
]
PER_KIND = int(sys.argv[1]) if len(sys.argv) > 1 else 30
BUSY = ("autopick.py", "assets/run.py", "assets\\run.py", "render/run.py", "match/run.py", "motiongraphics")


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def pipeline_busy() -> bool:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ForEach-Object { $_.CommandLine }"],
                         capture_output=True, text=True).stdout
    return any(b in out for b in BUSY)


def wait_free():
    quiet_since = None
    while True:
        if pipeline_busy():
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.time()
        elif time.time() - quiet_since > 300:
            return
        time.sleep(30)


def done_count(name):
    p = Path(SET) / f"results_{name}.jsonl"
    return sum(1 for x in p.read_text(encoding="utf-8").splitlines() if x.strip()) if p.exists() else 0


for name, model, mmproj, extra in RUNS:
    while done_count(name) < 3 * PER_KIND:
        log(f"{name}: waiting for a free GPU ({done_count(name)}/{3 * PER_KIND} done)")
        wait_free()
        log(f"{name}: starting llama-server")
        srv = subprocess.Popen([str(LLAMA), "-m", str(MODELS / model), "--mmproj", str(MODELS / mmproj), "-c", "6144",
                                "--port", "8080", "--host", "127.0.0.1", *extra],
                               stdout=open(rf"D:\esta-perf\llama\server-{name}.log", "w"), stderr=subprocess.STDOUT)
        import urllib.request
        for _ in range(200):
            try:
                if b'"ok"' in urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5).read():
                    break
            except Exception:
                pass
            time.sleep(3)
        rep = subprocess.Popen([sys.executable, "tools/vision_eval/replay.py", "--set", SET, "--backend", "openai",
                                "--name", name, "--per-kind", str(PER_KIND), "--workers", "1"], cwd=REPO)
        while rep.poll() is None:
            if pipeline_busy():
                log(f"{name}: a pipeline job started, yielding the GPU")
                rep.kill()
                break
            time.sleep(20)
        srv.kill()
        srv.wait()
        time.sleep(5)
    log(f"{name}: done")
log("all local runs done")
