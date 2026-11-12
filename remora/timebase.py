# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""The governed path's one reading of the current time.

Token lifetimes, approval expiry, lease expiry, limit windows and audit
timestamps were each read from the system clock where they were needed. That
is right for a deployment and wrong for a host that embeds REMORA and owns
time itself: a simulator running faster than real time, or a replay. There a
token issued "now" on the host's clock is expired or not yet valid on the
system clock, and no run is reproducible.

Every reader on the governed path asks :func:`utc_now` (or :func:`unix_now`).
Unset, that is the system clock, exactly as before. ``REMORA_TIME_SOURCE_MODULE``
names a module exposing ``utc_now()``; when set, its answer is the time.

The setting does not weaken a deployment:

* It is refused in production. Whoever supplies the time decides when an
  authorization ends, so a host clock belongs to development, simulation and
  replay only.
* It fails closed. A module that cannot be imported, has no ``utc_now``, raises,
  or answers with anything but a timezone-aware datetime raises
  :class:`TimeSourceError`; the system clock is never substituted for a source
  that was asked for and could not answer.
* It moves no authority. The same checks run on the same values; only where
  "now" comes from changes.

What it does not cover: the liveness timers that bound a running dispatch (the
flow fence renewal in ``servers/execution_api.py``) wait in real time on a
thread and stay on the system clock, and so do uptime and latency figures.
A host clock may also stand still or move backwards (a simulator restoring a
snapshot does); REMORA does not require it to be monotonic and records what it
is given.
"""
from __future__ import annotations

import importlib
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from remora.profiles import deployment_environment

#: Names a module exposing ``utc_now() -> datetime`` (timezone-aware).
TIME_SOURCE_ENV = "REMORA_TIME_SOURCE_MODULE"


class TimeSourceError(RuntimeError):
    """A host time source was asked for and could not be used."""


_LOCK = threading.Lock()
_RESOLVED = False
_SOURCE: Callable[[], object] | None = None
_SOURCE_NAME: str | None = None


def _resolve() -> Callable[[], object] | None:
    """The host's ``utc_now``, or None for the system clock. Bound once.

    A refusal is not cached: the next call refuses again, so a source that
    cannot be bound is never mistaken for no source at all.
    """
    global _RESOLVED, _SOURCE, _SOURCE_NAME
    if _RESOLVED:
        return _SOURCE
    with _LOCK:
        if _RESOLVED:
            return _SOURCE
        name = os.environ.get(TIME_SOURCE_ENV, "").strip()
        if not name:
            _SOURCE, _SOURCE_NAME, _RESOLVED = None, None, True
            return None
        if deployment_environment() == "production":
            raise TimeSourceError(
                f"{TIME_SOURCE_ENV} is refused in production: a host-supplied "
                "clock decides when an authorization ends")
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            raise TimeSourceError(
                f"{TIME_SOURCE_ENV}={name!r} cannot be imported: {exc}") from exc
        source = getattr(module, "utc_now", None)
        if not callable(source):
            raise TimeSourceError(
                f"{TIME_SOURCE_ENV}={name!r} does not expose a callable utc_now()")
        _SOURCE, _SOURCE_NAME, _RESOLVED = source, name, True
        return _SOURCE


def utc_now() -> datetime:
    """The current time on the governed path, timezone-aware, in UTC."""
    source = _resolve()
    if source is None:
        return datetime.now(UTC)
    try:
        answer = source()
    except Exception as exc:
        raise TimeSourceError(f"host time source {_SOURCE_NAME!r} failed: {exc}") from exc
    if not isinstance(answer, datetime) or answer.tzinfo is None:
        raise TimeSourceError(
            f"host time source {_SOURCE_NAME!r} must return a timezone-aware datetime, "
            f"got {answer!r}")
    return answer.astimezone(UTC)


def unix_now() -> float:
    """:func:`utc_now` as seconds since the epoch."""
    return utc_now().timestamp()


def host_time_source() -> str | None:
    """The module supplying the time, or None when it is the system clock.

    For evidence and diagnostics: a record made under a host clock should be
    able to say so.
    """
    _resolve()
    return _SOURCE_NAME


def reset_time_source() -> None:
    """Forget the bound source so the setting is read again. For tests."""
    global _RESOLVED, _SOURCE, _SOURCE_NAME
    with _LOCK:
        _RESOLVED, _SOURCE, _SOURCE_NAME = False, None, None
