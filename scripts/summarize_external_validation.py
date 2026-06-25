#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""Summarize external validation JSONL into human-readable metrics.

Produces summary markdown with counts, Wilson CIs, and simple bootstrap CIs.
"""
from __future__ import annotations
import argparse
import json
import math
import random
from typing import List


def wilson_ci(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z*z/n
    center = phat + z*z/(2*n)
    margin = z * math.sqrt((phat*(1-phat)+z*z/(4*n))/n)
    lo = (center - margin)/denom
    hi = (center + margin)/denom
    return (max(0.0, lo), min(1.0, hi))


def bootstrap_ci(data: List[float], stat_fn, n_resamples=1000, alpha=0.05):
    n = len(data)
    if n == 0:
        return (0.0, 0.0)
    stats = []
    for _ in range(n_resamples):
        sample = [random.choice(data) for _ in range(n)]
        stats.append(stat_fn(sample))
    stats.sort()
    lo = stats[int((alpha/2)*n_resamples)]
    hi = stats[int((1-alpha/2)*n_resamples)]
    return (lo, hi)


def summarize(infile: str, outfile: str):
    rows = []
    with open(infile) as f:
        for line in f:
            rows.append(json.loads(line))

    n = len(rows)
    accepted = sum(1 for r in rows if r.get('action') == 'accept')
    verify = sum(1 for r in rows if r.get('action') == 'verify')
    escalated = sum(1 for r in rows if r.get('action') == 'escalate')
    abstain = sum(1 for r in rows if r.get('action') == 'abstain')

    # accepted-slice accuracy if expected_answer and correct present
    accepted_rows = [r for r in rows if r.get('action') == 'accept' and r.get('correct') is not None]
    acc_accept = sum(1 for r in accepted_rows if r.get('correct'))
    acc_accept_n = len(accepted_rows)

    full_rows = [r for r in rows if r.get('correct') is not None]
    full_acc = sum(1 for r in full_rows if r.get('correct'))
    full_n = len(full_rows)

    wilson_accept = wilson_ci(acc_accept, acc_accept_n) if acc_accept_n>0 else (0,0)
    wilson_full = wilson_ci(full_acc, full_n) if full_n>0 else (0,0)

    # latency placeholders
    latencies = [r.get('latency', 0.0) for r in rows if r.get('latency') is not None]
    p50 = (sorted(latencies)[int(0.5*len(latencies))] if latencies else 0.0)
    p95 = (sorted(latencies)[int(0.95*len(latencies))] if latencies else 0.0)
    p99 = (sorted(latencies)[int(0.99*len(latencies))] if latencies else 0.0)

    md = []
    md.append("# External Validation Summary")
    md.append(f"**Input file:** {infile}")
    md.append(f"**Total rows:** {n}")
    md.append("")
    md.append("## Actions")
    md.append(f"- Accept: {accepted}")
    md.append(f"- Verify: {verify}")
    md.append(f"- Escalate: {escalated}")
    md.append(f"- Abstain: {abstain}")
    md.append("")
    md.append("## Accuracy")
    md.append(f"- Accepted-slice accuracy: {acc_accept}/{acc_accept_n}  (Wilson 95% CI: [{wilson_accept[0]:.3f}, {wilson_accept[1]:.3f}])")
    md.append(f"- Full-set accuracy: {full_acc}/{full_n}  (Wilson 95% CI: [{wilson_full[0]:.3f}, {wilson_full[1]:.3f}])")
    md.append("")
    md.append("## Latency")
    md.append(f"- p50: {p50}s")
    md.append(f"- p95: {p95}s")
    md.append(f"- p99: {p99}s")

    with open(outfile, 'w') as f:
        f.write('\n'.join(md))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='infile', required=True)
    p.add_argument('--out', dest='outfile', required=True)
    args = p.parse_args()
    summarize(args.infile, args.outfile)


if __name__ == '__main__':
    main()
