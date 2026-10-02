# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
"""Semantic shadow for the enforcing assess path: Jev beside every decision.

When enabled, each ``/v1/execution/assess`` hands its proposal, observation
and decision to :class:`SemanticShadow` after the audit record is durable.
The shadow puts the configured question set to Jev on a background worker,
computes what the same engine would have decided with Jev's answers
admitted, and appends a :class:`~remora.decision_providers.shadow.ShadowRecord`
to a local JSON Lines file. The real decision, record and response are
already final by then and nothing here reaches them.

Everything is opt-in and explicit. There are no defaults for the parts that
are decisions:

``REMORA_SEMANTIC_SHADOW``
    ``1``/``true`` turns it on. Unset or anything else: off.
``REMORA_SEMANTIC_SHADOW_TENANTS``
    Comma-separated tenants whose calls may be sent to the provider. The
    arguments and untrusted context leave the process, so this is a data
    egress decision taken per tenant, never by default.
``REMORA_SEMANTIC_SHADOW_QUESTIONS``
    ``v1``, ``v2`` or ``v2.1``.
``REMORA_SEMANTIC_SHADOW_THRESHOLDS``
    ``intent=…,target=…,injection=…,drift=…``. Thresholds have no defaults
    anywhere in the integration; see ``SemanticThresholds``.
``REMORA_SEMANTIC_SHADOW_LOG``
    Path of the JSON Lines file records are appended to.
``REMORA_SEMANTIC_SHADOW_MODEL``
    Optional; defaults to the pinned ``jev-1.13.0``, never to an alias.
``REMORA_SEMANTIC_SHADOW_PROFILES``
    Optional path to a YAML (or JSON) file of per-vertical profiles, which
    replaces ``_TENANTS``, ``_QUESTIONS`` and ``_THRESHOLDS``; setting both
    is refused as ambiguous. See :func:`load_profiles` for the format.

A profile is how a vertical is configured: a question set, its thresholds,
the language its requests are written in, and a calibration record. A
Norwegian ISP and an English bank differ in all four, and a single global
setting would make one of them wrong. A profile that claims ``calibrated``
must name its study and the corpus hash, so the claim can be checked.

Turning it on with any of the required settings missing or malformed raises
at startup. A half-configured shadow that silently records nothing would be
read later as "Jev never disagreed".

Only proposals whose operator request was resolved server-side
(``intent_authority_present is True``) are evaluated. Without that the
observation's question is a placeholder built from the tool call, and asking
whether a call matches itself measures nothing; those are counted as
``skipped_unresolved``. The tool description comes from the signed ToolSpec
when a bundle is configured, never from the agent.

The worker pool is small and its queue is bounded. When it is full the
proposal is dropped and counted rather than queued without limit, so a slow
provider costs shadow coverage and never request latency or memory.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from remora.decision_providers.enrich import (
    SemanticThresholds,
    semantic_state,
    semantic_state_v2,
)
from remora.decision_providers.questions import (
    QUESTION_SET_VERSION,
    QUESTION_SET_VERSION_V2,
    QUESTION_SET_VERSION_V2_1,
    REMORA_QUESTIONS_V1,
    REMORA_QUESTIONS_V2,
    REMORA_QUESTIONS_V2_1,
)
from remora.decision_providers.shadow import JsonlShadowSink, shadow_evaluate

__all__ = ["SemanticShadow", "ShadowProfile", "build_semantic_shadow_from_env", "load_profiles"]

PINNED_MODEL = "jev-1.13.0"

QUESTION_SETS = {
    "v1": (QUESTION_SET_VERSION, REMORA_QUESTIONS_V1),
    "v2": (QUESTION_SET_VERSION_V2, REMORA_QUESTIONS_V2),
    "v2.1": (QUESTION_SET_VERSION_V2_1, REMORA_QUESTIONS_V2_1),
}

_THRESHOLD_KEYS = {
    "intent": "intent_match",
    "target": "target_matches_request",
    "injection": "possible_injection",
    "drift": "scope_drift",
}


def _thresholds_from(values: Mapping[str, Any], where: str) -> SemanticThresholds:
    unknown = sorted(set(values) - set(_THRESHOLD_KEYS))
    if unknown:
        raise ValueError(f"{where}: unknown threshold {unknown}; expected {sorted(_THRESHOLD_KEYS)}")
    missing = sorted(set(_THRESHOLD_KEYS) - set(values))
    if missing:
        raise ValueError(f"{where}: missing {missing}; no threshold has a default")
    return SemanticThresholds(**{_THRESHOLD_KEYS[k]: float(v) for k, v in values.items()})


@dataclass(frozen=True)
class ShadowProfile:
    """How one vertical, language or customer is evaluated."""

    name: str
    set_name: str
    thresholds: SemanticThresholds
    language: str | None = None
    calibration: Mapping[str, Any] = field(default_factory=lambda: {"status": "uncalibrated"})

    def __post_init__(self) -> None:
        if self.set_name not in QUESTION_SETS:
            raise ValueError(
                f"profile {self.name!r}: unknown question set {self.set_name!r}; "
                f"expected one of {sorted(QUESTION_SETS)}"
            )
        status = self.calibration.get("status")
        if status not in ("uncalibrated", "calibrated"):
            raise ValueError(f"profile {self.name!r}: calibration status must be uncalibrated or calibrated")
        if status == "calibrated" and not (self.calibration.get("study") and self.calibration.get("corpus_sha256")):
            raise ValueError(
                f"profile {self.name!r}: a calibrated profile must name its study and corpus_sha256"
            )

    @property
    def version(self) -> str:
        return QUESTION_SETS[self.set_name][0]

    @property
    def questions(self) -> tuple:
        return QUESTION_SETS[self.set_name][1]


_PROFILE_KEYS = {"questions", "thresholds", "language", "calibration"}


def load_profiles(path: str | Path) -> tuple[dict[str, ShadowProfile], dict[str, str]]:
    """Profiles and the tenant-to-profile map from a YAML or JSON file.

    ::

        profiles:
          isp-no:
            questions: v2.1
            thresholds: {intent: 0.85, target: 0.85, injection: 0.5, drift: 0.5}
            language: no
            calibration: {status: uncalibrated}
        tenants:
          luftfiber: isp-no

    Every key is checked. An unknown key, a missing threshold, a tenant
    mapped to a profile that does not exist, or a ``calibrated`` profile
    without ``study`` and ``corpus_sha256`` refuses the whole file.
    """
    import yaml

    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(document, Mapping) or set(document) - {"profiles", "tenants"}:
        raise ValueError(f"{path}: expected exactly the keys 'profiles' and 'tenants'")
    profiles: dict[str, ShadowProfile] = {}
    for name, body in (document.get("profiles") or {}).items():
        if not isinstance(body, Mapping):
            raise ValueError(f"{path}: profile {name!r} is not a mapping")
        unknown = sorted(set(body) - _PROFILE_KEYS)
        if unknown:
            raise ValueError(f"{path}: profile {name!r} has unknown keys {unknown}")
        language = body.get("language")
        profiles[str(name)] = ShadowProfile(
            name=str(name),
            set_name=str(body.get("questions", "")),
            thresholds=_thresholds_from(body.get("thresholds") or {}, f"{path}: profile {name!r}"),
            # YAML reads a bare ``no`` as False; a language code is a string.
            language=("no" if language is False else (str(language) if language is not None else None)),
            calibration=dict(body.get("calibration") or {"status": "uncalibrated"}),
        )
    tenants = {str(t): str(p) for t, p in (document.get("tenants") or {}).items()}
    if not profiles or not tenants:
        raise ValueError(f"{path}: needs at least one profile and one tenant")
    unknown_profiles = sorted({p for p in tenants.values() if p not in profiles})
    if unknown_profiles:
        raise ValueError(f"{path}: tenants map to undefined profiles {unknown_profiles}")
    return profiles, tenants


def _parse_thresholds(raw: str) -> SemanticThresholds:
    values: dict[str, float] = {}
    for part in raw.split(","):
        if not part.strip():
            continue
        key, sep, value = part.partition("=")
        key = key.strip()
        if not sep or key not in _THRESHOLD_KEYS:
            raise ValueError(f"REMORA_SEMANTIC_SHADOW_THRESHOLDS: unknown entry {part.strip()!r}")
        values[_THRESHOLD_KEYS[key]] = float(value)
    missing = sorted(set(_THRESHOLD_KEYS) - {k for k, v in _THRESHOLD_KEYS.items() if v in values})
    if missing:
        raise ValueError(f"REMORA_SEMANTIC_SHADOW_THRESHOLDS: missing {missing}; no threshold has a default")
    return SemanticThresholds(**values)


class SemanticShadow:
    """Callable handed to ``assess_proposal`` as ``semantic_shadow``."""

    def __init__(
        self,
        *,
        engine: Any,
        sink: JsonlShadowSink,
        provider: Any = None,
        set_name: str | None = None,
        thresholds: SemanticThresholds | None = None,
        tenants: frozenset[str] | None = None,
        profiles: Mapping[str, ShadowProfile] | None = None,
        tenant_profiles: Mapping[str, str] | None = None,
        provider_for: Callable[[str], Any] | None = None,
        tool_description: Callable[[str], str | None] = lambda _name: None,
        max_workers: int = 2,
        max_pending: int = 64,
        executor: Any = None,
    ) -> None:
        if profiles is None:
            # One profile for every listed tenant: the env-only configuration.
            if set_name is None or thresholds is None or tenants is None or provider is None:
                raise ValueError("give either profiles and tenant_profiles, or provider, "
                                 "set_name, thresholds and tenants")
            profiles = {"default": ShadowProfile(name="default", set_name=set_name, thresholds=thresholds)}
            tenant_profiles = {tenant: "default" for tenant in tenants}
        if not tenant_profiles or any(p not in profiles for p in tenant_profiles.values()):
            raise ValueError("every tenant must map to a defined profile")
        self.profiles = dict(profiles)
        self.tenant_profiles = dict(tenant_profiles)
        self.tenants = frozenset(self.tenant_profiles)
        self.provider = provider
        #: One provider per question-set version; a provider records the
        #: version it was asked under, so profiles on different sets need
        #: different instances.
        self._provider_for = provider_for
        self._providers: dict[str, Any] = {}
        self.engine = engine
        self.sink = sink
        self.tool_description = tool_description
        self.max_pending = max_pending
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="semantic-shadow"
        )
        self._lock = threading.Lock()
        self._pending = 0
        self.submitted = 0
        self.dropped = 0
        self.skipped_tenant = 0
        self.skipped_unresolved = 0
        #: Why a recent proposal has no record yet, bounded. Lets a reviewer
        #: be told "not evaluated: tenant not opted in" instead of nothing.
        self._status: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._status_limit = 4096

    def profile_of(self, tenant: str) -> ShadowProfile:
        return self.profiles[self.tenant_profiles[tenant]]

    # Single-profile conveniences, kept for the env-only configuration.
    @property
    def questions(self) -> tuple:
        return next(iter(self.profiles.values())).questions

    @property
    def thresholds(self) -> SemanticThresholds:
        return next(iter(self.profiles.values())).thresholds

    def _provider(self, version: str) -> Any:
        if self._provider_for is None:
            return self.provider
        with self._lock:
            if version not in self._providers:
                self._providers[version] = self._provider_for(version)
            return self._providers[version]

    def _note(self, context: Mapping[str, Any], status: str) -> None:
        with self._lock:
            self._status[context["proposal_id"]] = (context["tenant"], status)
            self._status.move_to_end(context["proposal_id"])
            while len(self._status) > self._status_limit:
                self._status.popitem(last=False)

    def lookup(self, proposal_id: str, tenant: str) -> tuple[str, dict[str, Any] | None]:
        """``(status, record)`` for a proposal, scoped to ``tenant``.

        ``recorded`` comes with the record. Otherwise the status says why
        there is none: ``pending``, ``tenant_not_opted_in``,
        ``request_not_resolved``, ``dropped`` or ``unknown`` (older than the
        in-process memory, or assessed by another process).
        """
        record = self.sink.find(proposal_id, tenant)
        if record is not None:
            return "recorded", record
        with self._lock:
            noted = self._status.get(proposal_id)
        if noted is None or noted[0] != tenant:
            return "unknown", None
        return noted[1], None

    def __call__(self, context: Mapping[str, Any]) -> None:
        if context["tenant"] not in self.tenants:
            self.skipped_tenant += 1
            self._note(context, "tenant_not_opted_in")
            return
        if getattr(context["observation"], "intent_authority_present", None) is not True:
            self.skipped_unresolved += 1
            self._note(context, "request_not_resolved")
            return
        with self._lock:
            full = self._pending >= self.max_pending
            if full:
                self.dropped += 1
            else:
                self._pending += 1
                self.submitted += 1
        if full:
            self._note(context, "dropped")
            return
        self._note(context, "pending")
        try:
            self._executor.submit(self._run, dict(context))
        except RuntimeError:
            with self._lock:
                self._pending -= 1
                self.dropped += 1
            self._note(context, "dropped")

    def _state(self, context: Mapping[str, Any], profile: ShadowProfile) -> dict[str, Any]:
        proposal = context["proposal"]
        observation = context["observation"]
        untrusted = getattr(proposal, "untrusted_context", None)
        if profile.set_name == "v1":
            return semantic_state(
                intent=observation.question,
                tool_name=proposal.tool_name,
                arguments=dict(proposal.arguments),
                context={"untrusted_text": untrusted} if untrusted else None,
            )
        return semantic_state_v2(
            operator_request=observation.question,
            tool_name=proposal.tool_name,
            tool_description=self.tool_description(proposal.tool_name),
            arguments=dict(proposal.arguments),
            untrusted_content={"text": untrusted} if untrusted else None,
        )

    def _run(self, context: Mapping[str, Any]) -> None:
        try:
            profile = self.profile_of(context["tenant"])
            record = shadow_evaluate(
                context["observation"],
                context["final_action"],
                self._provider(profile.version),
                engine=self.engine,
                state=lambda: self._state(context, profile),
                thresholds=profile.thresholds,
                questions=profile.questions,
                proposal_id=context["proposal_id"],
                tenant=context["tenant"],
                tool_name=context["proposal"].tool_name,
                engine_action=context["engine_action"],
                profile=profile.name,
                language=profile.language,
                calibration=profile.calibration,
            )
            self.sink.write(record)
        finally:
            with self._lock:
                self._pending -= 1


def _on(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_semantic_shadow_from_env(
    *,
    engine: Any,
    tool_description: Callable[[str], str | None] = lambda _name: None,
    provider_factory: Callable[[str, str], Any] | None = None,
) -> SemanticShadow | None:
    """The configured shadow, ``None`` when off. Raises on a partial setup.

    Each variable is read from ``os.environ`` by its literal name, so the
    credential topology scanner sees every read.
    """
    environ = os.environ
    if not _on(environ.get("REMORA_SEMANTIC_SHADOW", "")):
        return None
    profiles_path = environ.get("REMORA_SEMANTIC_SHADOW_PROFILES", "").strip()
    raw_tenants = environ.get("REMORA_SEMANTIC_SHADOW_TENANTS", "")
    set_name = environ.get("REMORA_SEMANTIC_SHADOW_QUESTIONS", "").strip()
    raw_thresholds = environ.get("REMORA_SEMANTIC_SHADOW_THRESHOLDS", "")
    log_path = environ.get("REMORA_SEMANTIC_SHADOW_LOG", "").strip()
    model = environ.get("REMORA_SEMANTIC_SHADOW_MODEL", "").strip() or PINNED_MODEL
    if not log_path:
        raise ValueError("semantic shadow is on but not configured: REMORA_SEMANTIC_SHADOW_LOG is not set")
    if provider_factory is None:
        from remora.decision_providers.typesafe import TypeSafeJevProvider

        def provider_factory(question_set_version: str, model_id: str) -> Any:
            return TypeSafeJevProvider(question_set_version=question_set_version, model=model_id)

    common = {"engine": engine, "sink": JsonlShadowSink(log_path), "tool_description": tool_description}
    if profiles_path:
        if raw_tenants.strip() or set_name or raw_thresholds.strip():
            raise ValueError(
                "REMORA_SEMANTIC_SHADOW_PROFILES is set together with _TENANTS, _QUESTIONS or "
                "_THRESHOLDS; use one or the other"
            )
        profiles, tenant_profiles = load_profiles(profiles_path)
        return SemanticShadow(
            profiles=profiles, tenant_profiles=tenant_profiles,
            provider_for=lambda version: provider_factory(version, model), **common,
        )

    tenants = frozenset(t.strip() for t in raw_tenants.split(",") if t.strip())
    problems = []
    if not tenants:
        problems.append("REMORA_SEMANTIC_SHADOW_TENANTS names no tenant")
    if set_name not in QUESTION_SETS:
        problems.append(f"REMORA_SEMANTIC_SHADOW_QUESTIONS must be one of {sorted(QUESTION_SETS)}")
    if problems:
        raise ValueError("semantic shadow is on but not configured: " + "; ".join(problems))
    thresholds = _parse_thresholds(raw_thresholds)
    return SemanticShadow(
        provider=provider_factory(QUESTION_SETS[set_name][0], model),
        set_name=set_name, thresholds=thresholds, tenants=tenants, **common,
    )
