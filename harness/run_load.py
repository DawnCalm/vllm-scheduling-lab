"""Async load client for vLLM preemption experiments.

Consumes a workload (harness/workload.py), fires each request at its arrival
time against the OpenAI-compatible /v1/completions endpoint with STREAMING on,
and records per-request client-side metrics to a CSV.

Output length is forced exactly (min_tokens == max_tokens, ignore_eos) and
sampling is greedy+seeded, so a run is byte-reproducible.

Engine-side signals (preemptions, KV usage, queue length) are collected
separately by metrics_poll.py; run.sh aligns the two by wall-clock timestamp.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from dataclasses import dataclass

import httpx

import workload as wl


@dataclass
class Result:
    rid: str
    cls: str
    input_len: int
    output_len: int
    arrival_t: float        # scheduled offset from load start (s)
    send_t: float           # actual wall-clock send, offset from load start (s)
    ttft: float             # time to first token (s); -1 on failure
    e2e: float              # end-to-end latency (s); -1 on failure
    tpot: float             # mean time per output token after the first (s)
    output_tokens: int
    ok: int                 # 1 success, 0 failure
    error: str


async def one_request(client: httpx.AsyncClient, base_url: str, model: str,
                      spec: wl.RequestSpec, seed: int, t0: float) -> Result:
    # Respect the request's arrival time (burst -> all 0.0).
    delay = spec.arrival_t - (time.perf_counter() - t0)
    if delay > 0:
        await asyncio.sleep(delay)

    payload = {
        "model": model,
        "prompt": spec.prompt_token_ids,   # exact-length token-id prompt
        "max_tokens": spec.output_len,
        "min_tokens": spec.output_len,     # force exactly output_len tokens
        "ignore_eos": True,
        "temperature": 0.0,                # greedy -> reproducible
        "seed": seed,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    send_t = time.perf_counter()
    ttft = -1.0
    out_tokens = 0
    try:
        async with client.stream("POST", f"{base_url}/v1/completions",
                                 json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: "):]
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                choices = chunk.get("choices") or []
                if choices and choices[0].get("text"):
                    if ttft < 0:
                        ttft = time.perf_counter() - send_t
                    out_tokens += 1
                usage = chunk.get("usage")
                if usage and usage.get("completion_tokens"):
                    out_tokens = usage["completion_tokens"]
        e2e = time.perf_counter() - send_t
        decode_span = max(out_tokens - 1, 1)
        tpot = (e2e - ttft) / decode_span if ttft >= 0 else -1.0
        return Result(spec.rid, spec.cls, spec.input_len, spec.output_len,
                      spec.arrival_t, send_t - t0, ttft, e2e, tpot,
                      out_tokens, 1, "")
    except Exception as e:  # noqa: BLE001 - record any failure, keep the run going
        e2e = time.perf_counter() - send_t
        return Result(spec.rid, spec.cls, spec.input_len, spec.output_len,
                      spec.arrival_t, send_t - t0, ttft, e2e, -1.0,
                      out_tokens, 0, f"{type(e).__name__}: {e}")


async def run(cfg: wl.WorkloadConfig, base_url: str, model: str,
              out_csv: str) -> None:
    specs = wl.generate(cfg)
    print(f"[run_load] {len(specs)} requests -> {base_url}  model={model}")
    # No per-host connection cap: a burst opens all streams at once on purpose.
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    timeout = httpx.Timeout(connect=30.0, read=None, write=30.0, pool=None)

    t0 = time.perf_counter()
    wall_start = time.time()
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        tasks = [one_request(client, base_url, model, s, cfg.seed, t0)
                 for s in specs]
        results = await asyncio.gather(*tasks)
    wall_end = time.time()

    fields = list(Result.__dataclass_fields__.keys())
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow(r.__dict__)

    ok = sum(r.ok for r in results)
    print(f"[run_load] done: {ok}/{len(results)} ok, "
          f"wall {wall_end - wall_start:.1f}s -> {out_csv}")
    # Emit run window so run.sh / plot.py can crop the metrics time series.
    meta = {"wall_start": wall_start, "wall_end": wall_end,
            "base_url": base_url, "model": model}
    with open(out_csv.replace(".csv", ".meta.json"), "w") as f:
        json.dump(meta, f, indent=2)


def build_cfg(args: argparse.Namespace) -> wl.WorkloadConfig:
    fields = wl.WorkloadConfig.__dataclass_fields__
    return wl.WorkloadConfig(**{k: getattr(args, k) for k in fields})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run a mixed workload against vLLM.")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--model", default="Qwen/Qwen3-8B")
    ap.add_argument("--out", default="results/requests.csv")
    for f in wl.WorkloadConfig.__dataclass_fields__.values():
        ap.add_argument(f"--{f.name.replace('_', '-')}", dest=f.name,
                        type=type(f.default), default=f.default)
    args = ap.parse_args()
    asyncio.run(run(build_cfg(args), args.base_url, args.model, args.out))
