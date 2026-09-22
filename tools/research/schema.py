"""Schema and default skeleton for research.json.

This is the contract — any downstream skill (scriptwriter, brainbox, etc.)
that reads research.json should import from here so field names cannot
drift between skills.
"""

from datetime import datetime
from typing import Literal, TypedDict


class Source(TypedDict):
    url: str
    title: str
    snippet: str


class KeyFact(TypedDict):
    claim: str
    status: Literal["verified", "flagged"]
    confidence: Literal["high", "medium", "low", "none"]
    evidence: str
    sources: list[Source]
    flag: str  # one-sentence reason if flagged; empty string when verified


class Research(TypedDict, total=False):
    session_id: str
    researched_at: str    # iso8601 of the latest run
    topic_query: str      # exact search query used (topic only, no style)
    context_summary: str  # paragraph synthesizing broad context
    key_facts: list[KeyFact]
    open_questions: list[str]
    sources_seen: list[str]


def default_research(session_id: str) -> Research:
    """Empty skeleton with session_id and researched_at populated."""
    return {
        "session_id": session_id,
        "researched_at": datetime.now().isoformat(),
        "topic_query": "",
        "context_summary": "",
        "key_facts": [],
        "open_questions": [],
        "sources_seen": [],
    }
