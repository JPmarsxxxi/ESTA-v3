"""TypedDicts for timestamps.json output."""

from typing import TypedDict


class Word(TypedDict):
    word: str
    start: float
    end: float
    duration: float
    probability: float


class Segment(TypedDict):
    index: int
    start: float
    end: float
    duration: float
    text: str
    words: list[Word]


class SilencePoint(TypedDict):
    start: float
    end: float
    duration: float
    type: str  # "inter_segment" | "intra_segment"


class TimestampsMetadata(TypedDict):
    engine: str
    model: str
    accuracy: str
    language: str
    language_probability: float
    audio_file: str
    transcription_time_seconds: float
    vad_enabled: bool
    cpu_threads: int
    timestamp: str


class TimestampsData(TypedDict):
    full_text: str
    total_duration: float
    num_segments: int
    num_words: int
    segments: list[Segment]
    silence_points: list[SilencePoint]
    metadata: TimestampsMetadata
