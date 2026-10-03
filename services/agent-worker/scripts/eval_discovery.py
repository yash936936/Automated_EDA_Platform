"""
Manual relevance check for Phase 1.2's criterion "relevant datasets appear in
the top results for at least 8/10 queries". Relevance is a human judgement, so
this prints the top results per query and lets YOU score them.

    python scripts/eval_discovery.py            # needs API + worker + KAGGLE_API_TOKEN
Then write your score (n/10) in docs/debug.md.
"""
import os
import time

import requests
from dotenv import load_dotenv

load_dotenv()
API = os.environ.get("API_BASE_URL", "http://localhost:4000")
QUERIES = [
    "housing prices india", "customer churn telecom", "credit card fraud detection",
    "e-commerce orders returns", "stock market daily prices", "heart disease prediction",
    "student performance", "airline passenger satisfaction", "retail sales forecasting",
    "movie ratings",
]

for q in QUERIES:
    t0 = time.time()
    r = requests.get(f"{API}/api/discovery/search", params={"q": q}, timeout=120).json()
    dt = time.time() - t0
    if not r.get("ok"):
        print(f"\n## {q}\n  ERROR: {r.get('error')}")
        continue
    print(f"\n## {q}  ({dt:.1f}s, cacheHit={r['cacheHit']}, expansion={r['expansion']}, extra={r['expandedQueries']})")
    for i, d in enumerate(r["results"][:5], 1):
        print(f"  {i}. {d['title']}  [{d['ref']}]  dl={d['downloads']} license={d['license']}")
print("\nScore each query: relevant dataset in the top 5? Target >= 8/10. Re-run to confirm repeat queries are cache hits.")
