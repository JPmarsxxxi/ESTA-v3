"""Look references: the images that show a session's world and characters (SPEC.md Part 5, M8).

    python tools/look/refs.py add      --session sessions/<id> <files...>
    python tools/look/refs.py role     --session sessions/<id> --file r01.jpg --role world|character
    python tools/look/refs.py remove   --session sessions/<id> --file r01.jpg
    python tools/look/refs.py describe --session sessions/<id>
    python tools/look/refs.py list     --session sessions/<id>

Images live in sessions/<id>/look_refs/, indexed by look_refs.json. Haiku proposes each image's role and writes
look_style; genchar and genvideo feed the images themselves to an SDXL IP-Adapter through `resolve`.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.match.common import REPO_ROOT, read_json, utf8_stdout, write_json  # noqa: E402

ROLES = ("world", "character")
MAX_SIDE = 1024
MAX_PER_ROLE = 4
MAX_STYLE_WORDS = 30   # SDXL reads ~75 prompt tokens, shared with the trigger, desc and scene
CHARACTERS_DIR = REPO_ROOT / "characters"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
SHIP_SIDE = 768        # refs travel base64 inside a Kaggle notebook
STYLE_SCALE, LAYOUT_SCALE = 1.0, 0.6   # InstantStyle blocks; unverified until the first Kaggle grid

# Notebook code shared by genchar and genvideo's keyframe pass. Expects `pipe` (an SDXL pipeline), REFS (base64
# JPEGs) and REF_SCALE; leaves IPA_KW for the pipe call and REF_ERROR. A failure runs on without refs.
NOTEBOOK_IPA = '''
IPA_KW, REF_ERROR = {}, ""
try:
    import base64 as _b64, io as _io
    from PIL import Image as _Image
    _refs = [_Image.open(_io.BytesIO(_b64.b64decode(b))).convert("RGB") for b in REFS]
    pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models", weight_name="ip-adapter_sdxl.bin")
    # InstantStyle: only the style block (up.block_0, middle attention) and the layout block (down.block_2)
    # see the refs, so they carry the look and proportions without pasting in what the refs show.
    pipe.set_ip_adapter_scale({"down": {"block_2": [0.0, REF_SCALE["layout"]]},
                               "up": {"block_0": [0.0, REF_SCALE["style"], 0.0]}})
    IPA_KW = {"ip_adapter_image": [_refs]}
    print("[esta] IP-Adapter on", len(_refs), "refs", REF_SCALE, flush=True)
except Exception as e:
    REF_ERROR = "refs not applied: " + (str(e) or repr(e))[:200]
    print("[esta]", REF_ERROR, flush=True)
'''
SYSTEM = "You read style reference images for an animation pipeline. Reply with only the requested JSON."
PROMPT = (
    "These images are style references for one video. For each image decide its role: \"character\" if it mainly "
    "shows a character (face, body, turnaround, costume), else \"world\" (places, light, colour, props). Give each "
    "a short note on what it shows about the look. Then write one look_style line of at most 30 words that would make "
    "an image generator draw in this look: medium, rendering, shading, line, texture, palette, proportions. Describe "
    "the style only; never name a film, studio, franchise or character."
)


def index_path(session: Path) -> Path:
    return session / "look_refs.json"


def load(session: Path) -> dict:
    return read_json(index_path(session), {}) or {"images": []}


def add(session: Path, files: list[Path]) -> dict:
    from PIL import Image
    d = session / "look_refs"
    d.mkdir(parents=True, exist_ok=True)
    idx = load(session)
    shas = {im.get("sha") for im in idx["images"]}
    n = max((int(im["file"][1:-4]) for im in idx["images"]), default=0)
    added, skipped, rejected = [], [], []
    for f in files:
        f = Path(f)
        if f.suffix.lower() not in IMAGE_EXT:
            rejected.append({"file": f.name, "why": "not png, jpg or webp"})
            continue
        try:
            raw = f.read_bytes()
            im = Image.open(f)
            im.load()
        except Exception as e:  # noqa: BLE001 - any unreadable file is rejected with its reason
            rejected.append({"file": f.name, "why": f"unreadable: {str(e)[:80]}"})
            continue
        sha = hashlib.sha1(raw).hexdigest()[:16]
        if sha in shas:
            skipped.append(f.name)
            continue
        n += 1
        name = f"r{n:02d}.jpg"
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        im.save(d / name, format="JPEG", quality=90)
        idx["images"].append({"file": name, "source": f.name, "sha": sha, "role": "world", "role_source": "default", "note": ""})
        shas.add(sha)
        added.append(name)
    write_json(index_path(session), idx)
    return {"added": added, "duplicates": skipped, "rejected": rejected}


def set_role(session: Path, file: str, role: str) -> dict:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    idx = load(session)
    im = next((im for im in idx["images"] if im["file"] == file), None)
    if not im:
        raise FileNotFoundError(f"no look ref {file}")
    im["role"], im["role_source"] = role, "user"
    write_json(index_path(session), idx)
    return im


def remove(session: Path, file: str) -> dict:
    idx = load(session)
    idx["images"] = [im for im in idx["images"] if im["file"] != file]
    (session / "look_refs" / file).unlink(missing_ok=True)
    write_json(index_path(session), idx)
    return {"removed": file, "left": len(idx["images"])}


def set_hash(idx: dict) -> str:
    return hashlib.sha1("|".join(sorted(im["sha"] for im in idx["images"])).encode()).hexdigest()[:16]


def describe(session: Path, model: str = "haiku", ask=None) -> dict:
    """One Haiku call over every ref: roles (never over a user's), notes and look_style. Cached on the image set."""
    idx = load(session)
    if not idx["images"]:
        return {"described": 0, "why": "no look refs"}
    h = set_hash(idx)
    if idx.get("described") == h:
        return {"described": 0, "cached": True, "look_style_auto": idx.get("look_style_auto", "")}
    if ask is None:
        from tools.match.describe import ask
    from tools.match.describe import image_block
    content = []
    for im in idx["images"]:
        content.append({"type": "text", "text": f"Image {im['file'][:-4]}:"})
        content.append(image_block(session / "look_refs" / im["file"], 512))
    content.append({"type": "text", "text": PROMPT + '\n\nReply with ONLY: {"images": {"' + idx["images"][0]["file"][:-4]
                    + '": {"role": "world|character", "note": "..."}}, "look_style": "..."}'})
    res = ask(content, SYSTEM, model)
    if "error" in res:
        return {"described": 0, "error": res["error"][:300]}
    ans = res["answer"]
    for im in idx["images"]:
        a = (ans.get("images") or {}).get(im["file"][:-4]) or {}
        im["note"] = str(a.get("note") or im.get("note") or "")[:200]
        if im.get("role_source") != "user" and a.get("role") in ROLES:
            im["role"], im["role_source"] = a["role"], "haiku"
    style = " ".join(str(ans.get("look_style") or "").split()[:MAX_STYLE_WORDS]).rstrip(",.")
    idx["look_style_auto"], idx["described"] = style, h
    write_json(index_path(session), idx)
    reqs_path = session / "requirements.json"
    reqs = read_json(reqs_path, None)
    filled = False
    if reqs is not None and style and not str(reqs.get("look_style") or "").strip():
        reqs["look_style"] = style
        write_json(reqs_path, reqs)
        filled = True
    return {"described": len(idx["images"]), "look_style_auto": style, "requirements_filled": filled,
            "cost": res.get("cost", 0)}


def _role_files(session: Path | None, role: str) -> list[Path]:
    if not session:
        return []
    return [session / "look_refs" / im["file"] for im in load(session)["images"]
            if im["role"] == role and (session / "look_refs" / im["file"]).exists()]


def character_refs(character: str) -> list[Path]:
    from tools.kaggle_lane import slugify
    d = CHARACTERS_DIR / slugify(character) / "style_refs"
    return sorted(p for p in d.glob("*") if p.suffix.lower() in IMAGE_EXT) if d.is_dir() else []


def resolve(session: Path | None, purpose: str, character: str | None = None) -> list[Path]:
    """The refs for one generation purpose: design (a character's look), scene (a character in the world),
    keyframe (a shot with no character). A role with no images borrows the other's rather than going without."""
    chars = (character_refs(character) if character else []) or _role_files(session, "character")
    world = _role_files(session, "world")
    chars, world = chars[:MAX_PER_ROLE], world[:MAX_PER_ROLE]
    if purpose == "design":
        return chars or world
    if purpose == "keyframe":
        return world or chars
    if purpose == "scene":
        return chars + world
    raise ValueError(f"unknown purpose {purpose!r}")


def payload(paths: list[Path]) -> list[str]:
    import base64
    import io
    from PIL import Image
    out = []
    for p in paths:
        im = Image.open(p).convert("RGB")
        im.thumbnail((SHIP_SIDE, SHIP_SIDE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
    return out


def scales(strength: float) -> dict:
    return {"style": round(STYLE_SCALE * strength, 3), "layout": round(LAYOUT_SCALE * strength, 3)}


def main() -> None:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="Manage a session's look references")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--session", required=True)
    a.add_argument("files", nargs="+")
    r = sub.add_parser("role")
    r.add_argument("--session", required=True)
    r.add_argument("--file", required=True)
    r.add_argument("--role", required=True, choices=ROLES)
    rm = sub.add_parser("remove")
    rm.add_argument("--session", required=True)
    rm.add_argument("--file", required=True)
    for name in ("describe", "list"):
        sub.add_parser(name).add_argument("--session", required=True)
    args = ap.parse_args()
    session = Path(args.session)
    try:
        if args.cmd == "add":
            out = add(session, [Path(f) for f in args.files])
        elif args.cmd == "role":
            out = set_role(session, args.file, args.role)
        elif args.cmd == "remove":
            out = remove(session, args.file)
        elif args.cmd == "describe":
            out = describe(session)
        else:
            out = load(session)
        print(json.dumps({"ok": "error" not in out, **out}, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
