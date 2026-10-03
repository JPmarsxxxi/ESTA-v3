"""Look references (SPEC.md Part 5, M8.1): add, describe, resolve."""

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tools.look import refs as R  # noqa: E402


def img(path: Path, size=(2000, 1000), colour=(200, 40, 120), fmt=None) -> Path:
    Image.new("RGB", size, colour).save(path, format=fmt)
    return path


@pytest.fixture
def session(tmp_path):
    s = tmp_path / "s"
    s.mkdir()
    (s / "requirements.json").write_text(json.dumps({"look": "cartoon", "look_style": ""}))
    return s


def test_add_normalises_skips_duplicates_and_rejects(session, tmp_path):
    a = img(tmp_path / "a.png")
    b = img(tmp_path / "b.webp", (600, 900), (10, 10, 200), "WEBP")
    junk = tmp_path / "notes.jpg"
    junk.write_text("not an image")
    out = R.add(session, [a, b, a, junk, tmp_path / "x.gif"])
    assert out["added"] == ["r01.jpg", "r02.jpg"] and out["duplicates"] == ["a.png"]
    assert [r["file"] for r in out["rejected"]] == ["notes.jpg", "x.gif"]
    assert Image.open(session / "look_refs" / "r01.jpg").size == (1024, 512)
    assert Image.open(session / "look_refs" / "r02.jpg").format == "JPEG"
    assert R.add(session, [img(tmp_path / "c.jpg", colour=(1, 2, 3))])["added"] == ["r03.jpg"]


def fake_ask(answer, calls):
    def ask(content, system, model):
        calls.append(content)
        return {"answer": answer, "cost": 0.01}
    return ask


def test_describe_sets_roles_and_fills_empty_look_style(session, tmp_path):
    R.add(session, [img(tmp_path / "a.png"), img(tmp_path / "b.png", colour=(0, 0, 0))])
    R.set_role(session, "r02.jpg", "world")
    calls = []
    style = " ".join(["word"] * 40)
    ans = {"images": {"r01": {"role": "character", "note": "turnaround"}, "r02": {"role": "character", "note": "street"}},
           "look_style": style}
    out = R.describe(session, ask=fake_ask(ans, calls))
    idx = R.load(session)
    assert [im["role"] for im in idx["images"]] == ["character", "world"]   # the user's role stands
    assert idx["images"][1]["note"] == "street"
    assert len(out["look_style_auto"].split()) == R.MAX_STYLE_WORDS and out["requirements_filled"]
    assert json.loads((session / "requirements.json").read_text())["look_style"] == out["look_style_auto"]
    assert sum(1 for c in calls[0] if c["type"] == "image") == 2
    assert R.describe(session, ask=fake_ask(ans, calls))["cached"] and len(calls) == 1


def test_describe_never_overwrites_a_written_look_style(session, tmp_path):
    (session / "requirements.json").write_text(json.dumps({"look_style": "mine"}))
    R.add(session, [img(tmp_path / "a.png")])
    out = R.describe(session, ask=fake_ask({"images": {}, "look_style": "auto"}, []))
    assert not out["requirements_filled"] and R.load(session)["look_style_auto"] == "auto"
    assert json.loads((session / "requirements.json").read_text())["look_style"] == "mine"


def test_describe_failure_keeps_state(session, tmp_path):
    R.add(session, [img(tmp_path / "a.png")])
    out = R.describe(session, ask=lambda *a: {"error": "boom"})
    assert out["error"] == "boom" and R.load(session)["images"][0]["role"] == "world" and "described" not in R.load(session)


def test_resolve_purposes_override_fallback_and_cap(session, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CHARACTERS_DIR", tmp_path / "characters")
    files = [img(tmp_path / f"{i}.png", colour=(i, i, i)) for i in range(7)]
    R.add(session, files)
    for i in range(1, 6):
        R.set_role(session, f"r{i:02d}.jpg", "character")
    names = lambda ps: [p.name for p in ps]  # noqa: E731
    assert names(R.resolve(session, "design")) == ["r01.jpg", "r02.jpg", "r03.jpg", "r04.jpg"]
    assert names(R.resolve(session, "keyframe")) == ["r06.jpg", "r07.jpg"]
    assert names(R.resolve(session, "scene")) == ["r01.jpg", "r02.jpg", "r03.jpg", "r04.jpg", "r06.jpg", "r07.jpg"]
    own = tmp_path / "characters" / "kai" / "style_refs"
    own.mkdir(parents=True)
    img(own / "k1.jpg")
    assert names(R.resolve(session, "design", "Kai")) == ["k1.jpg"]
    R.remove(session, "r06.jpg")
    R.remove(session, "r07.jpg")
    assert names(R.resolve(session, "keyframe")) == ["r01.jpg", "r02.jpg", "r03.jpg", "r04.jpg"]   # world borrows
    assert R.resolve(None, "scene") == [] and R.resolve(tmp_path / "empty", "design") == []
