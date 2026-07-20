# Author: Stian Skogbrott
# License: Apache-2.0
"""REM-036 acceptance: shared-engine concurrency safety.

External review finding: the engine held one instance-shared ``_stop_event``
cleared per fan-out (concurrent assessments could cancel each other), and
``CorrelationMatrix.rho()`` read the sample store without the write lock
(inconsistent snapshots under a shared matrix). Both are fixed; these tests
race them deliberately.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

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
        except BaseException as exc:  # noqa: BLE001 — collect for assertion
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


@pytest.mark.slow
def test_correlation_matrix_concurrent_observe_and_rho() -> None:
    """100 threads hammer observe() while rho()/rho_matrix() read: no
    exceptions, and every read stays a valid agreement rate in [0, 1]."""
    matrix = CorrelationMatrix()
    providers = ["a", "b", "c"]
    stop = threading.Event()
    errors: list[BaseException] = []

    from remora.canonical import phi

    v_true = phi({"unstructured": "TRUE"})
    v_false = phi({"unstructured": "FALSE"})

    def writer(seed: int) -> None:
        try:
            for i in range(500):
                matrix.observe([
                    ("a", v_true),
                    ("b", v_true if (i + seed) % 2 else v_false),
                    ("c", v_true),
                ])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            while not stop.is_set():
                for a in providers:
                    for b in providers:
                        value = matrix.rho(a, b)
                        assert 0.0 <= value <= 1.0
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=100) as pool:
        readers = [pool.submit(reader) for _ in range(50)]
        writers = [pool.submit(writer, i) for i in range(50)]
        for f in writers:
            f.result(timeout=60)
        stop.set()
        for f in readers:
            f.result(timeout=10)

    assert not errors, errors[:3]
