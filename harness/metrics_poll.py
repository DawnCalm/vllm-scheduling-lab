"""Poll vLLM /metrics into a time-series CSV (engine-side signals).

Runs alongside run_load.py; run.sh starts it in the background and SIGTERMs it
when the load finishes. Rows are flushed every poll, so a killed poller still
leaves a complete CSV.

Metric names below were confirmed by curl against the pinned v0.24.0 container
on Day 0 (see PROGRESS.md) -- do not trust remembered names, these are real.
"""

from __future__ import annotations

import argparse
import csv
import re
import signal
import sys
import time

import httpx

# Prometheus exposition line: name{labels} value  [timestamp]
_LINE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eE]+)")

# metric name -> CSV column. Gauges are read directly; the counter
# (num_preemptions_total) is monotonic -- plot.py takes its delta over the run.
METRICS = {
    "vllm:num_preemptions_total": "preemptions_total",
    "vllm:kv_cache_usage_perc": "kv_usage",
    "vllm:num_requests_running": "running",
    "vllm:num_requests_waiting": "waiting",
    "vllm:gpu_cache_usage_perc": "gpu_cache_usage",
}


def scrape(text: str) -> dict[str, float]:
    """Sum values across label sets for each metric of interest (single engine
    here, so this is just a robust way to ignore labels)."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line:
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name = m.group(1)
        if name in METRICS:
            out[METRICS[name]] = out.get(METRICS[name], 0.0) + float(m.group(3))
    return out


_stop = False


def _handle(_signum, _frame):
    global _stop
    _stop = True


def main() -> None:
    ap = argparse.ArgumentParser(description="Poll vLLM /metrics to CSV.")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--interval", type=float, default=0.25)
    ap.add_argument("--out", default="results/metrics.csv")
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    cols = ["t", "wall"] + list(METRICS.values())
    t0 = time.perf_counter()
    n = 0
    with open(args.out, "w", newline="") as f, httpx.Client(timeout=5.0) as client:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        while not _stop:
            tick = time.perf_counter()
            try:
                text = client.get(f"{args.base_url}/metrics").text
                row = scrape(text)
                row["t"] = round(tick - t0, 4)
                row["wall"] = time.time()
                w.writerow({c: row.get(c, "") for c in cols})
                f.flush()
                n += 1
            except Exception as e:  # noqa: BLE001 - server may not be up yet
                print(f"[metrics_poll] scrape failed: {e}", file=sys.stderr)
            sleep = args.interval - (time.perf_counter() - tick)
            if sleep > 0:
                time.sleep(sleep)
    print(f"[metrics_poll] wrote {n} rows -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
