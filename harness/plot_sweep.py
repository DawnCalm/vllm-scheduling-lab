"""Aggregate several single-run result dirs into a preemption-vs-load curve.

Each run dir must contain requests.csv (per-request input/output lens + TTFT)
and metrics.csv (engine time series incl. preemptions_total). For each run we
compute:
  load%      = peak KV demand (sum of input_len+output_len over all requests)
               / KV budget in tokens
  preemptions= delta of vllm:num_preemptions_total over the run
  P99 TTFT   = per class (short/long)
and plot preemptions (left axis) + P99 TTFT (right axis) vs load%.

Budget defaults to the v0.24.0 / Qwen3-8B @ gpu_mem_util 0.9 figure (Day 0).
Usage: plot_sweep.py --budget 514464 --out plots/preempt_vs_load.png DIR [DIR...]
"""
from __future__ import annotations

import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def point(d: str, budget: int) -> dict:
    rq = read(os.path.join(d, "requests.csv"))
    mt = read(os.path.join(d, "metrics.csv"))
    demand = sum(int(r["input_len"]) + int(r["output_len"]) for r in rq)
    pre = np.array([float(r["preemptions_total"]) for r in mt
                    if r.get("preemptions_total") not in ("", None)])
    def p99(cls):
        v = [float(r["ttft"]) for r in rq
             if r["cls"] == cls and int(r["ok"]) == 1 and float(r["ttft"]) >= 0]
        return np.percentile(v, 99) if v else np.nan
    return {
        "name": os.path.basename(d.rstrip("/")),
        "load": 100.0 * demand / budget,
        "n": len(rq),
        "preempt": float(pre.max() - pre.min()) if len(pre) else np.nan,
        "p99_short": p99("short"),
        "p99_long": p99("long"),
    }


def aggregate(dirs, budget):
    """Group runs by offered load (repeats share an identical load%) and reduce
    each metric to median + min/max across repeats."""
    groups: dict[float, list[dict]] = {}
    for d in dirs:
        p = point(d, budget)
        groups.setdefault(round(p["load"], 1), []).append(p)
    rows = []
    for load, ps in sorted(groups.items()):
        def med(k): return float(np.nanmedian([p[k] for p in ps]))
        def lo(k):  return float(np.nanmin([p[k] for p in ps]))
        def hi(k):  return float(np.nanmax([p[k] for p in ps]))
        rows.append({
            "load": load, "n_rep": len(ps),
            "pre_med": med("preempt"), "pre_lo": lo("preempt"), "pre_hi": hi("preempt"),
            "ps_med": med("p99_short"), "pl_med": med("p99_long"),
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--budget", type=int, default=514464)
    ap.add_argument("--out", default="preempt_vs_load.png")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    rows = aggregate(args.dirs, args.budget)
    print(f"{'load%':>7s} {'reps':>5s} {'preempt(med[min-max])':>22s} "
          f"{'p99_short':>10s} {'p99_long':>9s}")
    for r in rows:
        print(f"{r['load']:6.1f}% {r['n_rep']:5d} "
              f"{r['pre_med']:6.0f} [{r['pre_lo']:.0f}-{r['pre_hi']:.0f}]".ljust(38)
              + f"{r['ps_med']:8.1f}s {r['pl_med']:8.1f}s")

    load = [r["load"] for r in rows]
    fig, ax1 = plt.subplots(figsize=(10, 6))
    ax1.plot(load, [r["pre_med"] for r in rows], "o-", color="black", lw=2,
             label="preemptions (median of reps)")
    ax1.fill_between(load, [r["pre_lo"] for r in rows], [r["pre_hi"] for r in rows],
                     color="black", alpha=0.15, label="preempt min–max")
    ax1.set_xlabel("offered load  (peak KV demand / KV budget, %)")
    ax1.set_ylabel("preemptions over run")
    ax1.axvline(100, color="gray", ls=":", alpha=0.7)
    ax1.text(100, ax1.get_ylim()[1] * 0.02, " 100% = KV budget", color="gray",
             rotation=90, va="bottom", ha="right", fontsize=8)
    ax1.set_ylim(bottom=0)

    ax2 = ax1.twinx()
    ax2.plot(load, [r["ps_med"] for r in rows], "s--", color="tab:green",
             lw=1.5, alpha=0.8, label="P99 TTFT short (median)")
    ax2.plot(load, [r["pl_med"] for r in rows], "^--", color="tab:purple",
             lw=1.5, alpha=0.8, label="P99 TTFT long (median)")
    ax2.set_ylabel("P99 TTFT (s)")
    ax2.set_ylim(bottom=0)

    # real series only (drop axvline & other helper artists); keep the min–max
    # band handle explicitly since fill_between is not a Line2D.
    band = ax1.collections[0] if ax1.collections else None
    lines = [l for l in ax1.get_lines() + ax2.get_lines()
             if not l.get_label().startswith("_")]
    handles = lines[:1] + ([band] if band is not None else []) + lines[1:]
    ax1.legend(handles, [h.get_label() for h in handles], loc="upper left", fontsize=9)
    ax1.set_title("Preemption vs offered load" + (f"  [{args.tag}]" if args.tag else ""))
    fig.tight_layout()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fig.savefig(args.out, dpi=120)
    print(f"[plot_sweep] wrote {args.out}")


if __name__ == "__main__":
    main()
