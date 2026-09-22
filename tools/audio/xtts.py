"""XTTS v2 voice-cloning wrapper.

Lifted verbatim from notebook Cell 12. The torch.load monkey-patch
is intentional and REQUIRED — XTTS v2 model loading needs
weights_only=False, which newer torch versions disallow by default.
Without the patch, loading the XTTS model raises a torch error.

Requires the esta conda env with TTS==0.22.0, transformers==4.33.3,
torch==2.6.0 installed (and a multi-GB model download on first run,
cached after).
"""

import re
from datetime import datetime
from pathlib import Path


XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# Section markers like [HOOK] / [BODY] / [CTA] are structural tags for
# downstream parsing, NOT words to be spoken. Strip any standalone
# bracketed tag line before synthesis so XTTS doesn't read "hook" aloud.
_SECTION_TAG = re.compile(r"^\s*\[[^\]]+\]\s*$", re.MULTILINE)


def strip_section_tags(text: str) -> str:
    """Remove standalone [TAG] marker lines and collapse the blank gaps."""
    cleaned = _SECTION_TAG.sub("", text)
    # Collapse 3+ newlines (left by removed tag lines) down to a paragraph break.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def generate_xtts(
    script_text: str,
    voice_sample_path: Path,
    output_path: Path,
    gpu: bool = False,
    speed: float = 1.0,
    language: str = "en",
) -> dict:
    """Generate audio using Coqui XTTS v2 with voice cloning.

    Args:
        script_text: the full script to read aloud.
        voice_sample_path: path to a WAV file (6-12s recommended) that
            XTTS will clone.
        output_path: where to write the generated audio (.wav).
        gpu: whether to use GPU. CPU works but is significantly slower.
        speed: playback speed. Notebook default is 1.0.
        language: ISO 639-1 language code. "en" by default.

    Returns:
        Dict with generation info: model, speed, gpu, language,
        load_time_seconds, gen_time_seconds.
    """
    import torch
    from TTS.api import TTS

    # Patch torch.load to allow weights_only=False for XTTS model loading.
    # Required because TTS==0.22.0's checkpoint format predates the
    # safetensors-by-default change in newer torch.
    original_load = torch.load

    def load_with_trust(*args, **kwargs):
        kwargs["weights_only"] = False
        return original_load(*args, **kwargs)

    torch.load = load_with_trust
    load_start = datetime.now()
    try:
        tts = TTS(model_name=XTTS_MODEL, gpu=gpu)
    finally:
        torch.load = original_load
    load_time = (datetime.now() - load_start).total_seconds()

    gen_start = datetime.now()
    tts.tts_to_file(
        text=strip_section_tags(script_text),
        speaker_wav=str(voice_sample_path),
        language=language,
        file_path=str(output_path),
        speed=speed,
    )
    gen_time = (datetime.now() - gen_start).total_seconds()

    return {
        "model": XTTS_MODEL,
        "speed": speed,
        "gpu": gpu,
        "language": language,
        "load_time_seconds": load_time,
        "gen_time_seconds": gen_time,
    }
