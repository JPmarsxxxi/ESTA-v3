from ddgs import DDGS
results = list(DDGS().images("Donald Trump funny face", max_results=3))
for r in results:
    print(r.get("title", "")[:60], "|", r.get("image", "")[:80])
