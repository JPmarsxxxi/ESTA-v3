"""Pinterest results harvested from the user's own browser session.

Why this exists: Pinterest serves anonymous visitors a redirect to the homepage,
so the headless Playwright scrape in `search.py` comes back empty — and its
fallback path goes through Google Images, which answers automated traffic with a
CAPTCHA. Neither is fixable from inside a scraper without either defeating an
anti-bot control or shipping the user's credentials into one.

So the session stays where it belongs: Claude drives the user's real, logged-in
Chrome (Claude in Chrome), runs the queries there, and drops the results here.
The pipeline then reads a plain cache file like any other source. No credentials
leave the browser, and the harvest happens with the user present.

The cache is repo-level rather than per-session on purpose — an aesthetic query
("dark academia study desk") is worth reusing across videos.

Harvest (in the browser, one call covers many queries) — see HARVEST_JS below;
write its output through `save(results)`.
"""

import json
import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = REPO_ROOT / "assets_cache" / "pinterest.json"

# Run this in a logged-in pinterest.com tab. It fetches each search page and
# regexes the pin hashes out of the HTML — no API token, no navigation per query.
# Pinterest encodes size in the path, so the hash upgrades to /originals/.
HARVEST_JS = r"""
async function pinScrape(q, want) {
  const r = await fetch("/search/pins/?q=" + encodeURIComponent(q), {credentials: "include"});
  if (!r.ok) return {q, error: r.status};
  const html = await r.text();
  const seen = new Map();
  const re = /i\.pinimg\.com\/(?:\d+x|originals)\/([0-9a-f]{2}\/[0-9a-f]{2}\/[0-9a-f]{2}\/[0-9a-f]{32})\.(jpg|png|webp)/g;
  let m;
  while ((m = re.exec(html)) && seen.size < want) seen.set(m[1], m[2]);
  return {q, urls: [...seen].map(([h, ext]) => "https://i.pinimg.com/originals/" + h + "." + ext)};
}
const QUERIES = __QUERIES__;
const out = [];
for (const q of QUERIES) { out.push(await pinScrape(q, __WANT__)); }
JSON.stringify(out);
"""


def _norm(query: str) -> str:
    """Loose key so 'Dark Academia desk' and 'dark academia desk' collide."""
    return " ".join(sorted(re.findall(r"[a-z0-9]+", query.lower())))


def load() -> dict:
    if not CACHE_PATH.exists():
        return {"harvested_at": None, "queries": {}}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def save(harvest: list[dict]) -> dict:
    """Merge a browser harvest ([{q, urls}]) into the cache."""
    cache = load()
    queries = cache.setdefault("queries", {})
    added = 0
    for entry in harvest:
        urls = entry.get("urls") or []
        if not urls:
            continue
        queries[_norm(entry["q"])] = {"query": entry["q"], "urls": urls}
        added += len(urls)
    cache["harvested_at"] = datetime.now().isoformat()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    return {"queries": len(queries), "urls_added": added, "path": str(CACHE_PATH)}


def lookup(query: str, max_results: int = 8) -> list:
    """Cache hit -> candidates in search.py's standard shape, else []."""
    cache = load()
    queries = cache.get("queries", {})
    entry = queries.get(_norm(query))

    if entry is None:
        # Fall back to the best token-overlap match — the plan's wording drifts
        # from whatever was harvested, and a near-miss beats no image at all.
        want = set(_norm(query).split())
        best, best_score = None, 0.0
        for key, val in queries.items():
            have = set(key.split())
            if not have:
                continue
            score = len(want & have) / len(want | have)
            if score > best_score:
                best, best_score = val, score
        if best_score < 0.5:
            return []
        entry = best

    out = []
    for i, url in enumerate(entry["urls"][:max_results]):
        out.append({
            "source": "pinterest", "type": "image",
            "url": url, "thumb": url.replace("/originals/", "/236x/"),
            "title": f"Pinterest {entry['query'][:40]} {i + 1}",
            "id": url.rsplit("/", 1)[-1].split(".")[0],
            # Real dims are unknown until download; originals are typically
            # ≥736px and the assets scorer treats 0 as "unknown", not "tiny".
            "width": 0, "height": 0, "duration": 0.0,
            "ext": url.rsplit(".", 1)[-1],
        })
    return out
