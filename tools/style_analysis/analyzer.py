"""Video style analyser — OpenCV + CLIP + Whisper extraction.

Produces frame images and per-sequence audio transcripts so Claude can
analyze them in-conversation. No external LLM needed from Python.

Ground-truth constants from notebook Cell 9 (OptimizedVideoAnalyzer).
Do NOT change SCENE_CHANGE_THRESHOLD, NUM_SEQUENCES, FRAMES_PER_SEQ,
FRAME_INTERVAL_SEC, CLIP_DURATION, or CLIP_PRE_ROLL without re-validating.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# ── Notebook ground-truth constants ─────────────────────────────────────────
SCENE_CHANGE_THRESHOLD = 30
NUM_SEQUENCES = 8
FRAMES_PER_SEQ = 5
FRAME_INTERVAL_SEC = 0.2
CLIP_DURATION = 3.0
CLIP_PRE_ROLL = 0.5
MAX_CLIP_FRAMES = 12

CLIP_MODEL_ID = "openai/clip-vit-base-patch32"

CLIP_LABELS = [
    "sports footage with athletes",
    "talking head or interview",
    "gaming or esports footage",
    "cooking or food content",
    "urban street or cityscape",
    "nature or landscape",
    "crowd or large audience",
    "text graphics or title cards",
    "memes or reaction content",
    "documentary footage",
    "music video or concert",
    "tutorial or educational content",
]

# Suppress HuggingFace symlink warning on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


class VideoAnalyzer:
    def __init__(self, hf_token: str = ""):
        self.clip_ready = False
        try:
            from transformers import CLIPModel, CLIPProcessor
            print("[analyzer] Loading CLIP (~350 MB, first run only)...", flush=True)
            kwargs = {"token": hf_token} if hf_token else {}
            self._clip_model = CLIPModel.from_pretrained(CLIP_MODEL_ID, **kwargs)
            self._clip_proc = CLIPProcessor.from_pretrained(CLIP_MODEL_ID, **kwargs)
            self.clip_ready = True
            print("[analyzer] CLIP loaded.", flush=True)
        except Exception as exc:
            print(f"[analyzer] CLIP unavailable ({exc}) — skipping.", flush=True)

        self.ffmpeg_ready = self._check_ffmpeg()

    def _check_ffmpeg(self) -> bool:
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            print("[analyzer] ffmpeg not found.", flush=True)
            return False

    # ── Public entry point ───────────────────────────────────────────────────

    def extract(self, video_path: Path, output_dir: Path) -> dict:
        """Extract all data Claude needs to do the analysis in-conversation.

        Saves sequence frames as JPEGs under output_dir/seq_NNN/.
        Returns extraction dict written to style_extraction.json.
        """
        print(f"\n[analyzer] Extracting: {video_path.name}", flush=True)

        timing = self._extract_cuts(video_path)
        sequences = self._sample_sequences(video_path)
        frame_paths = self._save_frames(sequences, output_dir)

        all_frames = [f for seq in sequences for f in seq["frames"]]
        clip_results = self._analyze_with_clip(all_frames[:MAX_CLIP_FRAMES]) if self.clip_ready else {}

        # Whisper transcription with timestamps — slice per sequence
        timed_segments = []
        if self.ffmpeg_ready:
            timed_segments = self._transcribe_with_timestamps(video_path)

        seq_transcripts = self._slice_transcripts_to_sequences(
            timed_segments, sequences
        )

        return {
            "video_file": str(video_path),
            "timing": timing,
            "frame_paths": frame_paths,
            "clip_content_types": clip_results,
            "seq_transcripts": seq_transcripts,
            "full_transcript": " ".join(s["text"] for s in timed_segments),
            "timestamp": datetime.now().isoformat(),
        }

    # ── OpenCV cut detection ─────────────────────────────────────────────────

    def _extract_cuts(self, video_path: Path) -> dict:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps

        prev_gray = None
        cuts = []
        idx = 0
        interval = max(1, frame_count // 20)

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % interval == 0:
                print(f"[analyzer] cut detection {idx / frame_count * 100:.0f}%", end="\r", flush=True)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray).mean()
                if diff > SCENE_CHANGE_THRESHOLD:
                    cuts.append(round(idx / fps, 3))
            prev_gray = gray
            idx += 1

        cap.release()
        print(flush=True)

        cuts_per_min = (len(cuts) / duration) * 60 if duration > 0 else 0
        avg_shot = duration / len(cuts) if cuts else duration

        print(f"[analyzer] {len(cuts)} cuts, {cuts_per_min:.1f} CPM, {avg_shot:.2f}s avg shot", flush=True)
        return {
            "duration": round(duration, 3),
            "fps": round(fps, 2),
            "cuts": cuts,
            "cut_count": len(cuts),
            "cuts_per_minute": round(cuts_per_min, 2),
            "avg_shot_duration": round(avg_shot, 3),
        }

    # ── Sequence sampling ────────────────────────────────────────────────────

    def _sample_sequences(self, video_path: Path) -> list:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        section = total_frames // NUM_SEQUENCES
        frame_step = max(1, int(fps * FRAME_INTERVAL_SEC))

        sequences = []
        for seq_idx in range(NUM_SEQUENCES):
            seq_start = seq_idx * section
            seq_time = seq_start / fps
            frames = []
            for i in range(FRAMES_PER_SEQ):
                pos = seq_start + i * frame_step
                if pos >= total_frames:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                if ret:
                    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if frames:
                sequences.append({"seq_number": seq_idx + 1, "start_time": seq_time, "frames": frames})

        cap.release()
        print(f"[analyzer] sampled {len(sequences)} sequences ({sum(len(s['frames']) for s in sequences)} frames)", flush=True)
        return sequences

    # ── Save frames as JPEG ──────────────────────────────────────────────────

    def _save_frames(self, sequences: list, output_dir: Path) -> dict:
        """Save frames as JPEG. Returns {seq_number: [abs_path, ...]}."""
        from PIL import Image

        frame_paths = {}
        for seq in sequences:
            seq_dir = output_dir / f"seq_{seq['seq_number']:03d}"
            seq_dir.mkdir(parents=True, exist_ok=True)
            paths = []
            for i, frame in enumerate(seq["frames"]):
                dest = seq_dir / f"frame_{i+1:02d}.jpg"
                Image.fromarray(frame).save(dest, format="JPEG", quality=85)
                paths.append(str(dest))
            frame_paths[seq["seq_number"]] = paths
            print(f"[analyzer] seq {seq['seq_number']} frames saved", flush=True)
        return frame_paths

    # ── Whisper transcription with timestamps ────────────────────────────────

    def _transcribe_with_timestamps(self, video_path: Path) -> list:
        """Transcribe audio with per-segment timestamps. Returns [{start, end, text}]."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        try:
            subprocess.run([
                "ffmpeg", "-y", "-i", str(video_path),
                "-ar", "16000", "-ac", "1", "-t", "120",
                tmp.name,
            ], capture_output=True, check=True)

            from faster_whisper import WhisperModel
            # device="cpu" pin — without it faster-whisper auto-tries CUDA and
            # dies on a missing cublas DLL on GPU-less machines (timestamps does this).
            wm = WhisperModel("tiny", device="cpu", compute_type="int8")
            segments, _ = wm.transcribe(tmp.name, beam_size=3, vad_filter=True)
            result = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
            total_words = sum(len(s["text"].split()) for s in result)
            print(f"[analyzer] transcribed {total_words} words in {len(result)} segments", flush=True)
            return result
        except Exception as exc:
            print(f"[analyzer] transcription skipped: {exc}", flush=True)
            return []
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass

    def _slice_transcripts_to_sequences(self, timed_segments: list, sequences: list) -> dict:
        """Map Whisper segments to each sequence window. Returns {seq_number: text}."""
        if not timed_segments or not sequences:
            return {}

        total_duration = sequences[-1]["start_time"] + CLIP_DURATION
        seq_window = total_duration / len(sequences)

        result = {}
        for seq in sequences:
            window_start = seq["start_time"] - CLIP_PRE_ROLL
            window_end = seq["start_time"] + CLIP_DURATION
            words = [
                s["text"] for s in timed_segments
                if s["start"] < window_end and s["end"] > window_start
            ]
            result[seq["seq_number"]] = " ".join(words).strip()
        return result

    # ── CLIP content classification ──────────────────────────────────────────

    def _analyze_with_clip(self, frames: list) -> dict:
        import torch
        from PIL import Image

        pil_frames = [Image.fromarray(f) for f in frames]
        inputs = self._clip_proc(text=CLIP_LABELS, images=pil_frames, return_tensors="pt", padding=True)

        with torch.no_grad():
            outputs = self._clip_model(**inputs)
            probs = outputs.logits_per_image.softmax(dim=1)

        avg_probs = probs.mean(dim=0).tolist()
        return {label: round(prob, 4) for label, prob in zip(CLIP_LABELS, avg_probs)}
