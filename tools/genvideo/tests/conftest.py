"""Keep push tests offline: the Hub check is a network call, tested on its own in test_anisora.py."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.genvideo import run as G  # noqa: E402


@pytest.fixture(autouse=True)
def offline_hub(monkeypatch):
    monkeypatch.setattr(G, "hub_missing", lambda model: ([], ""))
