cd /c/Users/User/ESTA-v3
for s in the-clock-was-wrong fade-the-crowd five-ways-backtest-lies the-label-was-the-defect; do
  id=$s-2026-10-13; p=$(python -c "import json;print(json.load(open('sessions/$id/inspo.json'))[0]['ref'])")
  echo "== $id"; conda run --no-capture-output -n esta python tools/style_analysis/run.py analyze --session sessions/$id --youtube-urls "" --local-paths "$p" --search-query "" 2>&1 | tail -3
done
