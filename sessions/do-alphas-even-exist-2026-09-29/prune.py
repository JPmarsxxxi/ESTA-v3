"""Delete source-pool candidates not picked for shots that already have a pick; keeps anything the new feed, the
pre-m9 backup edit, or a not-yet-picked shot's candidate list references."""
import json
from pathlib import Path

S = Path(__file__).parent
keep, picked = set(), set()
for f in (S / "assets_progress.jsonl", S / "match_backup" / "pre-m9" / "assets_progress.jsonl"):
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            keep.add(Path(str(r.get("file", ""))).name)
            if f.parent == S and r.get("ok"):
                picked.add(str(r["shot_number"]))
manifests = {m.stem[5:]: [Path(c["file"]).name for c in json.loads(m.read_text(encoding="utf-8")).get("candidates", [])]
             for m in (S / "assets" / "candidates").glob("shot_*.json")}
pending = {n for k, names in manifests.items() if k not in picked for n in names}
n = size = 0
for k, names in manifests.items():
    if k not in picked:
        continue
    for name in names:
        p = S / "assets" / "source_pool" / name
        if p.exists() and name not in keep and name not in pending:
            size += p.stat().st_size
            n += 1
            p.unlink()
print(f"pruned {n} files, {size / 1e9:.2f} GB")
