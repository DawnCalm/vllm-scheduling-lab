"""Generate a mixed long/short request workload for vLLM preemption experiments.

Single responsibility: turn a WorkloadConfig into a deterministic list of
RequestSpec. It does NOT send anything — run_load.py consumes this list.

Three design decisions (see docs/notes and question-bank):
  1. Prompts are raw token-id lists of an EXACT length, so each request's KV
     footprint is known to the token. Random ids (not shared text) also stop
     vLLM's automatic prefix caching from silently deflating KV usage and
     breaking our budget math.
  2. Output length is forced exactly (client sets ignore_eos + min/max tokens),
     so peak KV per request = input_len + output_len is reproducible.
  3. Everything is seeded -> byte-identical workload across runs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field

import numpy as np


@dataclass
class WorkloadConfig:
    n_long: int = 20            # long requests (long input, e.g. doc-summary / code)
    n_short: int = 100          # short requests (simple chat Q&A)
    long_input: int = 25000
    long_output: int = 512
    short_input: int = 512
    short_output: int = 256
    arrival: str = "burst"      # "burst" = all at t=0; "poisson" = rate-based
    rate: float = 0.0           # requests/sec for poisson (ignored when burst)
    seed: int = 0
    # token-id sampling range: skip low ids (specials) and stay well inside vocab
    vocab_lo: int = 5
    vocab_hi: int = 10000


@dataclass
class RequestSpec:
    rid: str
    cls: str                    # "long" | "short"
    input_len: int
    output_len: int
    arrival_t: float            # seconds after load start
    prompt_token_ids: list[int] = field(repr=False)  # exact length == input_len


def generate(cfg: WorkloadConfig) -> list[RequestSpec]:
    rng = np.random.default_rng(cfg.seed)
    specs: list[RequestSpec] = []

    def add(cls: str, n: int, ilen: int, olen: int) -> None:
        for i in range(n):
            ids = rng.integers(cfg.vocab_lo, cfg.vocab_hi, size=ilen).tolist()
            specs.append(RequestSpec(f"{cls}-{i:04d}", cls, ilen, olen, 0.0, ids))

    add("long", cfg.n_long, cfg.long_input, cfg.long_output)
    add("short", cfg.n_short, cfg.short_input, cfg.short_output)

    if cfg.arrival == "burst":
        pass  # arrival_t stays 0.0 for all
    elif cfg.arrival == "poisson":
        if cfg.rate <= 0:
            raise ValueError("poisson arrival needs rate > 0")
        order = rng.permutation(len(specs))  # interleave long/short arrivals
        t = 0.0
        for idx in order:
            specs[int(idx)].arrival_t = t
            t += rng.exponential(1.0 / cfg.rate)
    else:
        raise ValueError(f"unknown arrival mode: {cfg.arrival}")

    return specs


def kv_budget_report(cfg: WorkloadConfig, kv_budget_tokens: int) -> str:
    long_peak = cfg.n_long * (cfg.long_input + cfg.long_output)
    short_peak = cfg.n_short * (cfg.short_input + cfg.short_output)
    total = long_peak + short_peak
    pct = 100.0 * total / kv_budget_tokens
    return (
        f"peak KV demand: long {long_peak:,} + short {short_peak:,} = {total:,} tokens\n"
        f"KV budget: {kv_budget_tokens:,} tokens  ->  {pct:.0f}% "
        f"({'OVER -> preemption expected' if pct > 100 else 'UNDER -> may not preempt'})"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Preview the mixed workload.")
    ap.add_argument("--kv-budget", type=int, default=514464,
                    help="KV budget in tokens (Qwen3-8B @ default gpu_mem_util, v0.24.0)")
    for f in WorkloadConfig.__dataclass_fields__.values():
        ap.add_argument(f"--{f.name.replace('_', '-')}", type=type(f.default),
                        default=f.default)
    args = ap.parse_args()
    cfg = WorkloadConfig(**{k: v for k, v in vars(args).items() if k != "kv_budget"})
    specs = generate(cfg)
    print(json.dumps(asdict(cfg), indent=2))
    print(kv_budget_report(cfg, args.kv_budget))
    n_long = sum(s.cls == "long" for s in specs)
    print(f"generated {len(specs)} requests ({n_long} long, {len(specs) - n_long} short)")
    print("sample:", specs[0].rid, "input_len", specs[0].input_len,
          "first5 ids", specs[0].prompt_token_ids[:5])
