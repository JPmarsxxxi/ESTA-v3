"""Expressive voice generation on Kaggle's free GPU.

IndexTTS2 (text -> speech, with emotion) and Seed-VC (a recorded guide take ->
the cloned voice) both want ~8 GB of VRAM and a multi-GB checkpoint download,
so they run on the same free-T4 lane as `tools/genvideo` rather than on this
machine's 4 GB laptop GPU. See tools/kaggle_lane.py for the push/status/output
mechanics and the kernel-title-must-be-the-slug rule.

One kernel run synthesises every line of `voice_script.json` into its own
`line_<id>.wav`, because per-line files are what make "redo line 4, angrier"
cost one line instead of the whole voiceover (`--only L04`).

    conda run -n esta python tools/audio/run.py expressive --session sessions/<id>
    conda run -n esta python tools/audio/run.py expressive --session sessions/<id> --only L04,L07
"""

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.kaggle_lane import (  # noqa: E402
    ACCELERATORS, REPO_ROOT, ensure_dataset, fetch_output, kaggle_username,
    kernel_status, notebook_code, push_kernel, use_utf8_stdout, wait_dataset_ready,
    write_kernel_dir,
)

NOTEBOOK = r'''# ESTA expressive VO - IndexTTS2 (+ Seed-VC for guide takes)
import subprocess, os, json, glob, shutil, traceback
OUT = "/kaggle/working"
TMP = "/kaggle/temp" if os.path.isdir("/kaggle/temp") else "/tmp/esta"
os.makedirs(TMP, exist_ok=True)
os.environ["HF_HOME"] = TMP + "/hf"
os.environ["GIT_LFS_SKIP_SMUDGE"] = "1"

INP = None
for root, _, files in os.walk("/kaggle/input"):
    if "voice_script.json" in files:
        INP = root
JOB = json.load(open(INP + "/voice_script.json"))
REF = INP + "/ref.wav"
LINES = [l for l in JOB["lines"] if l["id"] in set(__ONLY__)] if __ONLY__ else JOB["lines"]
print("[esta] lines to synthesise:", len(LINES), flush=True)
status = {}

def sh(cmd, cwd=None, log="run.log"):
    print("$", cmd, flush=True)
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    with open(OUT + "/" + log, "a") as fh:
        fh.write("$ " + cmd + "\n" + r.stdout + r.stderr + "\n")
    print((r.stdout + r.stderr)[-2000:], flush=True)
    if r.returncode:
        raise RuntimeError(cmd + " -> exit " + str(r.returncode))

sh("pip install -q uv")

# ---- IndexTTS2: every line without a guide take ------------------------------
TTS_LINES = [l for l in LINES if l["engine"] == "indextts2"]
IDX = TMP + "/index-tts"
IDX_SCRIPT = r"""
import json, sys, traceback
from indextts.infer_v2 import IndexTTS2
cfg = json.load(open(sys.argv[1]))
tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints",
                use_fp16=True, use_cuda_kernel=False, use_deepspeed=False)
done = {}
for line in cfg["lines"]:
    kw = {}
    if line.get("emo_vector"):
        # Explicit vector — skips the text classifier entirely.
        kw = dict(emo_vector=line["emo_vector"])
    elif line.get("emotion"):
        kw = dict(use_emo_text=True, emo_text=line["emotion"],
                  emo_alpha=line.get("emo_alpha") or 0.65)
    # A line may name its own speaker ({voice: ...}) — a quoted passage, a
    # second character. Everything else clones the session's ref.
    spk = cfg["inp"] + "/" + line["voice_file"] if line.get("voice_file") else cfg["ref"]
    try:
        tts.infer(spk_audio_prompt=spk, text=line["model_text"],
                  output_path=cfg["out"] + "/line_" + line["id"] + ".wav",
                  use_random=False, verbose=False, **kw)
        done[line["id"]] = "ok"
    except Exception:
        done[line["id"]] = traceback.format_exc()[-500:]
    print(line["id"], done[line["id"]][:120], flush=True)
json.dump(done, open(cfg["out"] + "/idx_lines.json", "w"), indent=1)
"""
if TTS_LINES:
    try:
        sh("git clone --depth 1 https://github.com/index-tts/index-tts " + IDX)
        sh("uv sync", cwd=IDX)
        sh("uv run python -c \"from huggingface_hub import snapshot_download; "
           "snapshot_download('IndexTeam/IndexTTS-2', local_dir='checkpoints')\"", cwd=IDX)
        open(IDX + "/esta_cfg.json", "w").write(json.dumps(
            {"lines": TTS_LINES, "ref": REF, "inp": INP, "out": OUT}))
        open(IDX + "/esta_run.py", "w").write(IDX_SCRIPT)
        sh("uv run python esta_run.py esta_cfg.json", cwd=IDX)
        status["indextts2"] = "ok"
    except Exception:
        status["indextts2"] = traceback.format_exc()[-1500:]

# ---- Seed-VC: lines the user acted out themselves -----------------------------
VC_LINES = [l for l in LINES if l["engine"] == "seedvc"]
SVC = TMP + "/seed-vc"
if VC_LINES:
    try:
        sh("git clone --depth 1 https://github.com/Plachtaa/seed-vc " + SVC)
        # plain pip, not uv: seed-vc's requirements.txt has a quoted `--pre` line uv can't parse
        sh("uv venv --python 3.10 --seed .venv", cwd=SVC)
        sh(".venv/bin/python -m pip install -q -r requirements.txt", cwd=SVC)
        done = {}
        for line in VC_LINES:
            src = INP + "/" + line.get("guide_file", "guide__" + os.path.basename(line["guide"]))
            try:
                sh(".venv/bin/python inference.py --source " + src + " --target " + REF +
                   " --output " + TMP + "/vc/" + line["id"] +
                   " --diffusion-steps 30 --length-adjust 1.0 --inference-cfg-rate 0.7"
                   " --f0-condition False --auto-f0-adjust False --semi-tone-shift 0"
                   " --fp16 True", cwd=SVC)
                got = sorted(glob.glob(TMP + "/vc/" + line["id"] + "/*.wav"))
                shutil.copy(got[-1], OUT + "/line_" + line["id"] + ".wav")
                done[line["id"]] = "ok"
            except Exception:
                done[line["id"]] = traceback.format_exc()[-500:]
        json.dump(done, open(OUT + "/vc_lines.json", "w"), indent=1)
        status["seedvc"] = "ok"
    except Exception:
        status["seedvc"] = traceback.format_exc()[-1500:]

status["produced"] = sorted(os.path.basename(p) for p in glob.glob(OUT + "/line_*.wav"))
json.dump(status, open(OUT + "/status.json", "w"), indent=1)
print("ESTA_VO_STATUS::" + json.dumps({k: v for k, v in status.items() if k != "produced"}), flush=True)
'''


def _resolve_voice(session_dir: Path, name: str) -> Path:
    """`{voice: preset_brit_male}` -> a wav. Bare names live in voice_samples/."""
    for candidate in (Path(name), Path(name).with_suffix(".wav"),
                      REPO_ROOT / "voice_samples" / f"{name}.wav",
                      REPO_ROOT / "voice_samples" / name,
                      session_dir / name):
        if candidate.suffix and candidate.exists():
            return candidate
    raise FileNotFoundError(f"voice sample not found for {{voice: {name}}}")


def _stage_inputs(session_dir: Path, job: dict, sample: Path, only: list[str]) -> Path:
    """Collect ref.wav + voice_script.json + guide takes + alt voices into one upload dir.

    Everything is staged FLAT, with a prefix instead of a subdirectory, because
    the Kaggle CLI's `--dir-mode` defaults to `skip`: subdirectories are dropped
    from the upload silently, with no warning and a successful exit. A nested
    `voices/x.wav` therefore never reaches the kernel, and the only symptom is a
    FileNotFoundError deep in the model's audio loader, half an hour into a run.
    """
    stage = session_dir / "voice_build" / "inputs"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample, stage / "ref.wav")

    for line in job["lines"]:
        if only and line["id"] not in only:
            continue
        if line.get("voice"):
            # Resolve here, not in the kernel: the notebook only ever sees a
            # flat filename inside the uploaded dataset.
            src = _resolve_voice(session_dir, line["voice"])
            staged = f"voice__{src.name}"
            shutil.copy(src, stage / staged)
            line["voice_file"] = staged
        if line["guide"]:
            src = session_dir / line["guide"]
            if not src.exists():
                src = Path(line["guide"])
            staged = f"guide__{Path(line['guide']).name}"
            shutil.copy(src, stage / staged)
            line["guide_file"] = staged

    (stage / "voice_script.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    return stage


def _poll_until_done(kernel_id: str, poll_seconds: int) -> str:
    """Block until the kernel finishes, surviving transient status failures.

    `kernels status` intermittently hangs past its timeout while a long run is
    in flight. That is a flaky API call, not a dead kernel — letting it kill the
    poller strands a run that is still burning GPU minutes, and the only repair
    is to re-attach. So a single failure is noted and retried; only a sustained
    run of them gives up.
    """
    consecutive_errors = 0
    while True:
        try:
            state, raw = kernel_status(kernel_id)
            consecutive_errors = 0
        except Exception as exc:  # timeout, transport error, rate limit
            consecutive_errors += 1
            print(f"[{time.strftime('%H:%M:%S')}] status check failed "
                  f"({consecutive_errors}/5): {str(exc)[:90]}", flush=True)
            if consecutive_errors >= 5:
                raise RuntimeError(
                    f"lost contact with {kernel_id} after 5 tries; it may still be "
                    f"running — re-attach with `expressive --attach`") from exc
            time.sleep(poll_seconds)
            continue

        print(f"[{time.strftime('%H:%M:%S')}] {state or raw}", flush=True)
        if state in ("complete", "error", "cancel"):
            return state
        time.sleep(poll_seconds)


def generate(session_dir: Path, only: list[str] | None = None,
             poll_seconds: int = 45, attach: bool = False) -> dict:
    """Push one kernel, wait for it, and pull the per-line wavs into voice_build/lines/.

    `attach=True` skips the upload and push and re-joins a kernel already in
    flight — the repair path when the poller dies but the run does not.
    """
    job = json.loads((session_dir / "voice_script.json").read_text(encoding="utf-8"))
    sample = Path(job["voice_sample"])
    if not sample.exists():
        raise FileNotFoundError(f"voice sample not found: {sample}")

    user = kaggle_username()
    slug = session_dir.name.lower().replace("_", "-")[:28].strip("-")
    # Datasets and kernels share one per-user slug namespace on Kaggle. The
    # dataset uploads first, takes the name, and the kernel push then fails with
    # a bare "409 Conflict" — and the dataset survives the failure, so every
    # retry hits it again. Confirmed by `datasets status <slug>` returning
    # "ready" for a slug that `datasets list --mine` doesn't even show. The two
    # prefixes below must therefore never collide.
    dataset_id = f"{user}/esta-vo-in-{slug}"
    kernel_id = f"{user}/esta-vo-run-{slug}"

    if attach:
        print(f"[attach] re-joining {kernel_id} without re-pushing", flush=True)
    else:
        stage = _stage_inputs(session_dir, job, sample, only or [])
        ok, msg = ensure_dataset(stage, dataset_id, f"esta-vo-{slug}", notes="vo inputs")
        if not ok or not wait_dataset_ready(dataset_id):
            raise RuntimeError(f"input upload failed: {msg}")

        code = notebook_code(NOTEBOOK, only=json.dumps(only or []))
        build = session_dir / "voice_build" / "kernel"
        write_kernel_dir(build, code, kernel_id, ACCELERATORS["t4"])
        meta = build / "kernel-metadata.json"
        spec = json.loads(meta.read_text(encoding="utf-8"))
        spec["dataset_sources"] = [dataset_id]
        meta.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        ok, msg = push_kernel(build)
        if not ok:
            raise RuntimeError(f"kernel push failed: {msg}")
        time.sleep(30)

    state = _poll_until_done(kernel_id, poll_seconds)

    out_dir = session_dir / "voice_build" / "lines"
    fetch_output(kernel_id, out_dir)
    status_path = out_dir / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    produced = sorted(p.name for p in out_dir.glob("line_*.wav"))
    return {"ok": bool(produced), "kernel": kernel_id, "state": state,
            "produced": produced, "status": status}


def cmd_expressive(args) -> None:
    use_utf8_stdout()
    only = [s.strip() for s in (args.only or "").split(",") if s.strip()]
    print(json.dumps(generate(Path(args.session), only, attach=bool(getattr(args, "attach", False)))))
