"""TypedDicts for style_analysis.json output."""

from typing import TypedDict


class CutTiming(TypedDict):
    duration: float
    fps: float
    cuts: list[float]
    cut_count: int
    cuts_per_minute: float
    avg_shot_duration: float


class SequenceAnalysis(TypedDict):
    time: float
    seq_number: int
    analysis: str


class StyleInsights(TypedDict):
    dominant_content_type: str   # sports|gaming|cooking|tech|lifestyle|comedy|educational|vlog|other
    energy_level: str            # high|medium|low
    visual_style: str            # real_footage|mixed|graphics_heavy|meme_content
    pacing: str                  # fast|moderate|slow
    keywords: list[str]


class VideoAnalysis(TypedDict):
    video_file: str
    timing: CutTiming
    sequence_analyses: list[SequenceAnalysis]
    synthesis: str
    insights: StyleInsights
    clip_content_types: dict[str, float]   # label → avg probability
    timestamp: str


class StyleAnalysis(TypedDict):
    session_id: str
    source: str                  # "user_provided" | "auto_search"
    videos_analyzed: int
    videos: list[VideoAnalysis]
    aggregate_insights: StyleInsights
    pacing_patterns: dict        # avg cuts_per_minute, avg_shot_duration across videos
    timestamp: str
