"""Turn requests.csv + metrics.csv into PNGs.

fig1  engine timeline: KV usage, running/waiting queues, cumulative preemptions.
fig2  per-request TTFT stratified by class (long vs short), with P99 markers.

Deliberately dependency-light: csv + numpy + matplotlib, no pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_csv(path: str) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def to_float(rows: list[dict], key: str) -> np.ndarray:
    vals = []
    for r in rows:
        v = r.get(key, "")
        vals.append(float(v) if v not in ("", None) else np.nan)
    return np.array(vals, dtype=float)


def plot_timeline(metrics: list[dict], out: str, title: str) -> None:
    t = to_float(metrics, "t")
    kv = to_float(metrics, "kv_usage") * 100.0
    running = to_float(metrics, "running")
    waiting = to_float(metrics, "waiting")
    waiting_cap = to_float(metrics, "waiting_capacity")
    preempt = to_float(metrics, "preemptions_total")
    preempt = preempt - np.nanmin(preempt)  # cumulative since run start

    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.plot(t, kv, color="tab:red", lw=2, label="KV cache usage %")
    ax1.set_xlabel("time since load start (s)")
    ax1.set_ylabel("KV usage %  /  queue length")
    ax1.plot(t, running, color="tab:blue", lw=1, alpha=0.7, label="running")
    ax1.plot(t, waiting, color="tab:orange", lw=1, alpha=0.7, label="waiting")
    if not np.all(np.isnan(waiting_cap)):
        ax1.plot(t, waiting_cap, color="tab:brown", lw=1.5, alpha=0.8,
                 label="waiting (capacity)")
    ax1.set_ylim(bottom=0)

    ax2 = ax1.twinx()
    ax2.plot(t, preempt, color="black", lw=2, ls="--",
             label="preemptions (cumulative)")
    ax2.set_ylabel("cumulative preemptions")
    ax2.set_ylim(bottom=0)

    # mark first preemption
    fired = np.where(preempt > 0)[0]
    if len(fired):
        t_first = t[fired[0]]
        ax1.axvline(t_first, color="gray", ls=":", alpha=0.8)
        ax1.text(t_first, ax1.get_ylim()[1] * 0.95,
                 f" first preempt @ {t_first:.1f}s", color="gray", va="top")

    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [l.get_label() for l in lines], loc="upper left", fontsize=9)
    ax1.set_title(title)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"[plot] wrote {out}")


def plot_ttft(reqs: list[dict], out: str, title: str) -> None:
    ok = [r for r in reqs if r.get("ok") == "1" and float(r["ttft"]) >= 0]
    fig, (axc, axs) = plt.subplots(1, 2, figsize=(13, 5))
    colors = {"long": "tab:purple", "short": "tab:green"}

    for cls in ("short", "long"):
        ttft = np.array([float(r["ttft"]) for r in ok if r["cls"] == cls])
        if not len(ttft):
            continue
        xs = np.sort(ttft)
        ys = np.arange(1, len(xs) + 1) / len(xs)
        p99 = np.percentile(ttft, 99)
        axc.plot(xs, ys, color=colors[cls], lw=2,
                 label=f"{cls}  n={len(ttft)}  P99={p99:.2f}s")
        axc.axvline(p99, color=colors[cls], ls=":", alpha=0.6)

    axc.set_xlabel("TTFT (s)")
    axc.set_ylabel("cumulative fraction")
    axc.set_title("TTFT ECDF by class (dotted = P99)")
    axc.legend(fontsize=9)
    axc.grid(alpha=0.3)

    # right: TTFT vs send time, to see degradation build up under pressure
    for cls in ("short", "long"):
        sub = [r for r in ok if r["cls"] == cls]
        if not sub:
            continue
        axs.scatter([float(r["send_t"]) for r in sub],
                    [float(r["ttft"]) for r in sub],
                    s=14, alpha=0.6, color=colors[cls], label=cls)
    axs.set_xlabel("send time since load start (s)")
    axs.set_ylabel("TTFT (s)")
    axs.set_title("TTFT vs arrival")
    axs.legend(fontsize=9)
    axs.grid(alpha=0.3)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"[plot] wrote {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Plot harness results.")
    ap.add_argument("--requests", default="results/requests.csv")
    ap.add_argument("--metrics", default="results/metrics.csv")
    ap.add_argument("--outdir", default="plots")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    tag = f" [{args.tag}]" if args.tag else ""

    if os.path.exists(args.metrics):
        plot_timeline(read_csv(args.metrics),
                      os.path.join(args.outdir, "timeline.png"),
                      "Engine timeline: KV pressure & preemption" + tag)
    if os.path.exists(args.requests):
        plot_ttft(read_csv(args.requests),
                  os.path.join(args.outdir, "ttft_by_class.png"),
                  "Per-request TTFT" + tag)
