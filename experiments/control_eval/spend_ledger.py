# SPDX-License-Identifier: BUSL-1.1
"""Reserve-before-spend budget ledger for the control evaluation (gate G2).

WS1 Study C overran its sealed cap by about 1 USD (NEGATIVE_RESULTS.md §96)
because its guard recorded spend after each call and the run was resumed in
a new process. This ledger closes both gaps:

* **Reserve first.** Before every API call the caller reserves a
  conservative upper bound: the request's input tokens (an upper bound, see
  :func:`input_token_upper_bound`) priced at the dearer of the uncached and
  cache-write input rates, plus ``max_tokens`` priced as output. The
  reservation is refused when it would take the phase or the total past its
  cap. Only then is the call sent.
* **Settle after.** The provider's usage fields replace the reservation with
  the actual cost (uncached input, cache writes, cache reads and output each
  at their own price). A call that raised is settled at its full reservation,
  because whether the provider billed it is unknown.
* **Durable and append-only.** Every reservation and settlement is one JSON
  line, flushed and fsynced before the call goes out, and chained to the
  previous line by SHA-256 so an edited or truncated ledger is refused. A
  reservation without a settlement (the process died mid-call) counts at its
  full amount forever. A resumed run therefore can neither forget spend nor
  spend past the cap twice.
* **One cap across phases.** ``total_cap_usd`` (default 50) binds pilot and
  test together; ``phase_caps_usd`` binds each phase. Writers take an
  exclusive ``flock`` on the ledger, so two processes cannot both reserve the
  last dollar.

Prices are per million tokens and come from the owner's run config; a model
without a price is refused rather than counted as free.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from experiments.control_eval.metrics import BudgetExceeded

DEFAULT_TOTAL_CAP_USD = 50.0
#: Tokens added to every input upper bound for the provider's own framing of
#: tools, roles and thinking configuration.
FRAMING_OVERHEAD_TOKENS = 2048
GENESIS = "0" * 64


class LedgerCorrupt(BudgetExceeded):
    """The ledger's hash chain is broken or a line is not valid JSON; nothing may spend."""


class UsageMissing(BudgetExceeded):
    """A response carried no usable usage fields; an uncounted call is not free."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ModelPrice:
        try:
            price = cls(float(raw["input"]), float(raw["output"]),
                        float(raw["cache_write"]), float(raw["cache_read"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise BudgetExceeded(f"price entry {dict(raw)!r} needs input, output, "
                                 "cache_write and cache_read in USD per MTok") from exc
        if min(price.input, price.output, price.cache_write, price.cache_read) < 0:
            raise BudgetExceeded("negative price")
        if price.input <= 0 or price.output <= 0:
            raise BudgetExceeded("input and output prices must be positive")
        return price


@dataclass(frozen=True)
class Usage:
    """Token counts from one Messages API response."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
                "cache_read_input_tokens": self.cache_read_input_tokens}


def _get(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def _count(value: Any, name: str, optional: bool = False) -> int:
    if value is None and optional:
        return 0
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise UsageMissing(f"usage field {name!r} is {value!r}; refusing to count the call as free")
    return value


def usage_from_response(response: Any) -> Usage:
    usage = _get(response, "usage")
    if usage is None:
        raise UsageMissing("response has no usage object")
    return Usage(
        _count(_get(usage, "input_tokens"), "input_tokens"),
        _count(_get(usage, "output_tokens"), "output_tokens"),
        _count(_get(usage, "cache_creation_input_tokens"), "cache_creation_input_tokens", True),
        _count(_get(usage, "cache_read_input_tokens"), "cache_read_input_tokens", True),
    )


def input_token_upper_bound(request: Mapping[str, Any]) -> int:
    """UTF-8 byte length of the request body plus framing overhead.

    Every Claude tokenizer maps at least one byte to each token, so the byte
    length bounds the token count of the text; the overhead covers framing.
    """
    body = json.dumps(request, sort_keys=True, ensure_ascii=False, default=str)
    return len(body.encode("utf-8")) + FRAMING_OVERHEAD_TOKENS


class PriceTable:
    def __init__(self, prices: Mapping[str, Mapping[str, Any] | ModelPrice]) -> None:
        self._prices = {m: p if isinstance(p, ModelPrice) else ModelPrice.from_mapping(p)
                        for m, p in prices.items()}

    def price(self, model: str) -> ModelPrice:
        if model not in self._prices:
            raise BudgetExceeded(f"no price for model {model!r}; refusing to count it as free")
        return self._prices[model]

    def upper_bound(self, model: str, input_tokens: int, max_output_tokens: int) -> float:
        p = self.price(model)
        return (input_tokens * max(p.input, p.cache_write) + max_output_tokens * p.output) / 1e6

    def actual(self, model: str, usage: Usage) -> float:
        p = self.price(model)
        return (usage.input_tokens * p.input + usage.cache_creation_input_tokens * p.cache_write
                + usage.cache_read_input_tokens * p.cache_read + usage.output_tokens * p.output) / 1e6


@dataclass
class LedgerTotals:
    total_usd: float = 0.0
    by_phase: dict[str, float] = field(default_factory=dict)
    open_reservations: int = 0
    calls_settled: int = 0
    last_hash: str = GENESIS


def _line_hash(prev: str, body: Mapping[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev}\n{canonical}".encode()).hexdigest()


class SpendLedger:
    """Append-only, hash-chained JSONL ledger with caps.

    ``phase_caps_usd`` maps a phase name (``pilot``, ``test``) to its
    sub-cap; a phase not listed may not spend. The chain is verified once
    and then incrementally: each read under the lock parses only the bytes
    appended since the last read, by this or another process.
    """

    def __init__(self, path: Path, prices: PriceTable, total_cap_usd: float = DEFAULT_TOTAL_CAP_USD,
                 phase_caps_usd: Mapping[str, float] | None = None) -> None:
        if total_cap_usd <= 0:
            raise BudgetExceeded("the total cap must be positive")
        self.path = Path(path)
        self.prices = prices
        self.total_cap_usd = float(total_cap_usd)
        self.phase_caps_usd = {k: float(v) for k, v in (phase_caps_usd or {}).items()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._offset = 0
        self._line = 0
        self._last = GENESIS
        self._reserved: dict[str, dict[str, Any]] = {}
        self._settled: dict[str, float] = {}
        self._refresh()  # refuse a corrupt ledger at construction

    # ── reading ───────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        with self.path.open("rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            if size < self._offset:
                raise LedgerCorrupt(f"{self.path} shrank; the ledger was truncated")
            fh.seek(self._offset)
            chunk = fh.read()
        if chunk and not chunk.endswith(b"\n"):
            chunk = chunk[:chunk.rfind(b"\n") + 1]  # a line still being written
        for raw in chunk.splitlines():
            self._line += 1
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError as exc:
                raise LedgerCorrupt(f"{self.path}:{self._line} is not JSON") from exc
            recorded = entry.pop("hash", None)
            if entry.get("prev") != self._last or recorded != _line_hash(self._last, entry):
                raise LedgerCorrupt(f"{self.path}:{self._line} breaks the hash chain; "
                                    "the ledger was edited or truncated")
            self._last = recorded
            if entry["kind"] == "reserve":
                self._reserved[entry["id"]] = entry
            elif entry["kind"] == "settle":
                if entry["id"] not in self._reserved or entry["id"] in self._settled:
                    raise LedgerCorrupt(f"settlement {entry['id']} has no open reservation")
                self._settled[entry["id"]] = float(entry["usd"])
        self._offset += len(chunk)

    def entries(self) -> list[dict[str, Any]]:
        """Every reservation, with its settled cost or ``None`` while open."""
        self._refresh()
        return [{**r, "settled_usd": self._settled.get(rid)} for rid, r in self._reserved.items()]

    def totals(self) -> LedgerTotals:
        self._refresh()
        t = LedgerTotals(last_hash=self._last)
        for rid, r in self._reserved.items():
            usd = self._settled.get(rid, float(r["usd"]))
            t.total_usd += usd
            t.by_phase[r["phase"]] = t.by_phase.get(r["phase"], 0.0) + usd
            if rid in self._settled:
                t.calls_settled += 1
            else:
                t.open_reservations += 1
        return t

    def remaining(self, phase: str) -> float:
        t = self.totals()
        cap = self.phase_caps_usd.get(phase, 0.0)
        return max(0.0, min(self.total_cap_usd - t.total_usd, cap - t.by_phase.get(phase, 0.0)))

    # ── writing ───────────────────────────────────────────────────────────

    @contextmanager
    def _locked(self) -> Iterator[Any]:
        with self.path.open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                self._refresh()
                yield fh
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _append(self, fh: Any, body: dict[str, Any]) -> None:
        body = {**body, "prev": self._last}
        body["hash"] = _line_hash(self._last, body)
        fh.write(json.dumps(body, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
        self._refresh()

    def reserve(self, phase: str, model: str, input_tokens: int, max_output_tokens: int,
                meta: Mapping[str, Any] | None = None) -> str:
        """Reserve the worst case of one call, or raise :class:`BudgetExceeded`."""
        if phase not in self.phase_caps_usd:
            raise BudgetExceeded(f"phase {phase!r} has no sub-cap; refusing to spend")
        usd = self.prices.upper_bound(model, input_tokens, max_output_tokens)
        with self._locked() as fh:
            t = self.totals()
            phase_spent = t.by_phase.get(phase, 0.0)
            if t.total_usd + usd > self.total_cap_usd:
                raise BudgetExceeded(
                    f"reserving {usd:.4f} USD would pass the total cap {self.total_cap_usd} "
                    f"(committed {t.total_usd:.4f})")
            if phase_spent + usd > self.phase_caps_usd[phase]:
                raise BudgetExceeded(
                    f"reserving {usd:.4f} USD would pass the {phase} cap "
                    f"{self.phase_caps_usd[phase]} (committed {phase_spent:.4f})")
            rid = uuid.uuid4().hex
            self._append(fh, {"kind": "reserve", "id": rid, "phase": phase, "model": model,
                              "usd": usd, "input_bound": input_tokens,
                              "max_output": max_output_tokens, "meta": dict(meta or {})})
        return rid

    def settle(self, rid: str, model: str, usage: Usage | None) -> float:
        """Replace reservation *rid* by the actual cost; ``usage=None`` keeps the full reservation."""
        with self._locked() as fh:
            res = self._reserved.get(rid)
            if res is None or rid in self._settled:
                raise LedgerCorrupt(f"no open reservation {rid}")
            if usage is None:
                usd, note = float(res["usd"]), "error_charged_at_reservation"
            else:
                usd, note = self.prices.actual(model, usage), "usage"
                if usd > float(res["usd"]) + 1e-12:
                    # The bound failed; record the truth and stop the run.
                    note = "actual_exceeded_reservation"
            self._append(fh, {"kind": "settle", "id": rid, "usd": usd, "note": note,
                              "usage": usage.as_dict() if usage else None})
        if note == "actual_exceeded_reservation":
            raise BudgetExceeded(f"call {rid} cost {usd:.6f} USD, above its reservation")
        return usd
