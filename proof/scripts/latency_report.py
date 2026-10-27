"""Safe to run any time (reads a local file only). Summarises acctwatch_latency.jsonl.

    .venv/bin/python proof/scripts/latency_report.py audit/acctwatch_latency.jsonl
"""
import json
import statistics
import sys

rows = [json.loads(x) for x in open(sys.argv[1], encoding="utf-8") if x.strip()]
for k in ("t_verified", "t_checked", "t_call_request"):
    v = sorted(r[k] for r in rows if k in r)
    if v:
        print(f"{k}: n={len(v)} median={statistics.median(v):.1f} ms p95={v[int(0.95 * (len(v) - 1))]:.1f} ms "
              f"max={v[-1]:.1f} ms")
