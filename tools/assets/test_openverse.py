import requests
r = requests.get(
    "https://api.openverse.org/v1/images/",
    params={"q": "Donald Trump", "page_size": 5},
    headers={"User-Agent": "ESTA-Pipeline/1.0"},
    timeout=10,
)
print(r.status_code)
data = r.json()
for img in data.get("results", [])[:3]:
    print(img.get("title", "")[:60], "|", img.get("url", "")[:80])
