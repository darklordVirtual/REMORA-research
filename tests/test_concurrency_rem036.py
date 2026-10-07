# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""REM-036 acceptance: shared-engine concurrency safety.

External review finding: the engine held one instance-shared ``_stop_event``
cleared per fan-out (concurrent assessments could cancel each other), and
``CorrelationMatrix.rho()`` read the sample store without the write lock
(inconsistent snapshots under a shared matrix). Both are fixed; these tests
race them deliberately.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import pytest

from remora.correlation import CorrelationMatrix
from remora.engine import Remora
from remora.genome import Genome


class _SlowOracle:
    """Stub oracle whose ask() blocks until released."""

    def __init__(self, name: str, gate: threading.Event) -> None:
        self.name = name
        self._gate = gate

    def ask(self, prompt: str):
        self._gate.wait(timeout=5.0)
        from remora.engine import OracleResponse
        return OracleResponse(provider=self.name, verdict="TRUE",
                              confidence=0.9, raw_text="ok")


def _engine(gate: threading.Event) -> Remora:
    return Remora(
        oracles=[_SlowOracle("a", gate), _SlowOracle("b", gate)],
        genome=Genome(),
        oracle_timeout_s=5.0,
    )


def test_concurrent_fanouts_use_request_local_stop_events() -> None:
    """60 concurrent fan-outs on ONE engine: no assessment may cancel
    another's deadline state, and every fan-out completes with responses."""
    gate = threading.Event()
    engine = _engine(gate)
    barrier = threading.Barrier(60)
    results: list[int] = []
    errors: list[BaseException] = []

    def one_assessment(i: int) -> None:
        try:
            barrier.wait(timeout=10)
            responses = engine._ask_parallel(f"prompt-{i}")
            results.append(len(responses))
        except Exception as exc:  # noqa: BLE001 — collect for assertion
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=60) as pool:
        futures = [pool.submit(one_assessment, i) for i in range(60)]
        # Release the oracles once every fan-out is in flight.
        gate.set()
        for f in futures:
            f.result(timeout=30)

    assert not errors, errors[:3]
    assert len(results) == 60
    assert all(n == 2 for n in results)


def test_stop_event_is_created_per_fanout() -> None:
    """Structural pin: each fan-out constructs a fresh Event (the shared
    clear() pattern is the regression this guards against)."""
    gate = threading.Event()
    gate.set()
    engine = _engine(gate)
    before = engine._stop_event
    engine._ask_parallel("p1")
    first = engine._stop_event
    engine._ask_parallel("p2")
    second = engine._stop_event
    assert first is not before
    assert second is not first


def _race_observe_and_rho(
    writer: Callable[[CorrelationMatrix, int], None],
    *,
    writers: int = 50,
    readers: int = 50,
    writer_budget_s: float = 60.0,
    reader_budget_s: float = 120.0,
) -> list[BaseException]:
    """Run ``writers`` against ``readers`` on one matrix, with bounded liveness.

    RMR-CR-012: the old shape waited on each writer inside the pool's ``with``
    block and set the stop flag only afterwards. A writer timeout skipped the
    flag, readers spun forever and ``shutdown(wait=True)`` never returned. Here
    the writers share one deadline, the flag is set in ``finally``, and every
    reader has its own time budget, so a starved run fails instead of hanging.
    """
    matrix = CorrelationMatrix()
    providers = ["a", "b", "c"]
    stop = threading.Event()
    errors: list[BaseException] = []

    def reader() -> None:
        deadline = time.monotonic() + reader_budget_s
        try:
            while not stop.is_set():
                if time.monotonic() > deadline:
                    raise TimeoutError("reader ran past its budget without a stop signal")
                for a in providers:
                    for b in providers:
                        value = matrix.rho(a, b)
                        assert 0.0 <= value <= 1.0
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    def guarded_writer(seed: int) -> None:
        try:
            writer(matrix, seed)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    pool = ThreadPoolExecutor(max_workers=writers + readers)
    reader_futures = []
    try:
        reader_futures = [pool.submit(reader) for _ in range(readers)]
        writer_futures = [pool.submit(guarded_writer, i) for i in range(writers)]
        deadline = time.monotonic() + writer_budget_s
        for f in writer_futures:
            f.result(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        stop.set()
        # Readers leave on the flag; writers are bounded by construction.
        pool.shutdown(wait=True, cancel_futures=True)
    for f in reader_futures:
        f.result(timeout=10)
    return errors


def _observe_500(matrix: CorrelationMatrix, seed: int) -> None:
    from remora.canonical import phi

    v_true = phi({"unstructured": "TRUE"})
    v_false = phi({"unstructured": "FALSE"})
    for i in range(500):
        matrix.observe([
            ("a", v_true),
            ("b", v_true if (i + seed) % 2 else v_false),
            ("c", v_true),
        ])


@pytest.mark.slow
def test_correlation_matrix_concurrent_observe_and_rho() -> None:
    """100 threads hammer observe() while rho()/rho_matrix() read: no
    exceptions, and every read stays a valid agreement rate in [0, 1]."""
    errors = _race_observe_and_rho(_observe_500)
    assert not errors, errors[:3]


def test_starved_writers_fail_within_a_bound_instead_of_hanging() -> None:
    """RMR-CR-012 regression: writers slower than their budget must end the
    race with a TimeoutError in bounded time, with every reader stopped."""

    def starved(matrix: CorrelationMatrix, seed: int) -> None:
        time.sleep(2.0)

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        _race_observe_and_rho(starved, writers=4, readers=4, writer_budget_s=0.2)
    assert time.monotonic() - started < 15.0
