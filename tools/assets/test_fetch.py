"""Quick one-shot asset fetch for manual testing.

Usage:
    conda run -n esta python tools/assets/test_fetch.py
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.assets.run import _fetch_shot, _load_config

SHOTS = [
    {
        "shot_number": 1,
        "start_est": 0.0,
        "end_est": 4.0,
        "audio": "Mbeumo with a goal against Nottingham Forest",
        "visual": {
            "type": "REAL_FOOTAGE",
            "specificity": "high",
            "search_sources": [
                {"source": "youtube", "queries": [
                    "Mbeumo goal vs Nottingham Forest 2026",
                    "Mbeumo goal Nottingham Forest Brentford",
                    "Mbeumo goal recent 2026",
                ]},
            ],
            "description": "Mbeumo scoring a goal against Nottingham Forest",
            "search_query": "mbeumo goal vs nottingham recently",
        },
    },
]

out_dir = Path("test_assets")
out_dir.mkdir(exist_ok=True)
config = _load_config()

for shot in SHOTS:
    result = _fetch_shot(shot, out_dir, config)
    print(json.dumps(result, indent=2))
