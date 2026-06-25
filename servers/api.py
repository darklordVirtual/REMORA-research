#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""REMORA REST API gateway — OpenAPI/FastAPI prototype.

Endpoints
---------
  POST /v1/assess              — Full REMORA policy assessment for an agent action
  GET  /v1/envelope/{id}       — Retrieve a stored DecisionEnvelope by request_id
  GET  /v1/audit/{id}          — Retrieve the audit record for a request_id
  POST /v1/review              — Submit human review (approved / rejected)
  POST /v1/follow-up           — Append follow-up information to a case
  POST /v1/evidence            — Attach external evidence to a case
  POST /v1/rerun               — Replay an identical request (determinism check)
  GET  /v1/metrics             — JSON governance metrics
  GET  /metrics                — Prometheus exposition (text/plain)
  GET  /v1/policy/version      — Active policy bundle hash + runtime mode
  GET  /v1/health              — Liveness probe for orchestration / load balancers

Usage
-----
    pip install fastapi uvicorn
    uvicorn servers.api:app --host 0.0.0.0 --port 8000

    # POST assessment
    curl -X POST http://localhost:8000/v1/assess \\
      -H 'Content-Type: application/json' \\
      -d '{"question": "Should I drop the production DB?", "risk_tier": "critical"}'

Design notes
------------
- Development mode keeps bearer auth optional for local iteration.
- Production mode (`REMORA_ENV=production`) fails closed unless auth,
    persistent storage, and a non-mock oracle backend are configured.
- The endpoint is stateless: each request creates an ephemeral Remora engine
  with MockOracles.  Replace with a shared engine pool for production.
- All inputs are validated via Pydantic before processing.
"""
from __future__ import annotations

import importlib.metadata
import logging
import os
import time
import uuid
import hmac
import json
import hashlib
from pathlib import Path
from typing import Any, Literal, Optional

logger = logging.getLogger("remora.api")


# ---------------------------------------------------------------------------
# Canonical environment-mode helper
# ---------------------------------------------------------------------------

def _get_env_mode() -> str:
    """Return the normalised REMORA_ENV value.

    Default is ``"development"`` when the variable is unset or empty.
    Recognised production values: ``"prod"``, ``"production"``.
    Any other value (including empty) is treated as development.
    """
    return os.getenv("REMORA_ENV", "development").strip().lower()


# Resolved once at import time for the FastAPI app version string.
try:
    _PACKAGE_VERSION: str = importlib.metadata.version("remora")
except importlib.metadata.PackageNotFoundError:
    _PACKAGE_VERSION = "0.8.0"  # fallback for editable installs before first build

# FastAPI is an optional dependency — gate the import.
try:
    from fastapi import FastAPI, HTTPException, Request  # type: ignore[import-not-found]
    from fastapi.responses import JSONResponse, PlainTextResponse  # type: ignore[import-not-found]
    from pydantic import BaseModel, Field, field_validator  # type: ignore[import-not-found]
except ImportError as _e:  # pragma: no cover
    raise ImportError(
        "FastAPI is not installed. Run: pip install 'fastapi[all]'"
    ) from _e


# ---------------------------------------------------------------------------
# In-memory rate limiter
# ---------------------------------------------------------------------------

class _InMemoryRateLimiter:
    """Sliding-window per-key rate limiter (no external dependencies).

    The limit and window are read from env vars on each check call so that
    integration tests can override them without restarting the server.

    Env vars:
      REMORA_ASSESS_RATE_LIMIT_PER_MIN  — max requests per 60-second window
                                          (default: 120; set to 0 to disable)
    """

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit for *key*."""
        limit_raw = os.getenv("REMORA_ASSESS_RATE_LIMIT_PER_MIN", "120")
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 120
        if limit <= 0:
            return True  # disabled

        window_s = 60.0
        now = time.time()
        bucket = self._buckets.get(key, [])
        bucket = [t for t in bucket if now - t < window_s]
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        self._buckets[key] = bucket
        return True


_rate_limiter = _InMemoryRateLimiter()


def _safe_error_response(exc: Exception, status_code: int = 500) -> JSONResponse:
    """Build a safe JSON error response that never leaks internal details.

    Generates a unique correlation_id for log correlation.  The raw exception
    message is logged server-side but never included in the response body.
    """
    correlation_id = str(uuid.uuid4())[:8]
    logger.error(
        "REMORA API error [%s]: %s — %s",
        correlation_id,
        type(exc).__name__,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": (
                "An internal error occurred. "
                "Contact support with the correlation_id."
            ),
            "correlation_id": correlation_id,
        },
    )

from remora.genome import Genome
from remora.engine import Remora
from remora.oracles.mock import MockOracle
from remora.evidence import StaticJsonlEvidenceProvider
from remora.adapters.storage import (
    ControlPlaneStore,
    EvidenceRecord,
    FollowUpRecord,
    InMemoryControlPlaneStore,
    PostgresControlPlaneStore,
    ReviewRecord,
)
from remora.adapters.storage.control_plane import utc_now_iso
from remora.observability import get_remora_tracer
from remora.policy.report import DecisionReport

# ---------------------------------------------------------------------------
# App definition
# ---------------------------------------------------------------------------

app = FastAPI(
    title="REMORA API",
    description=(
        "Multi-oracle consensus governance layer for agentic AI. "
        "Provides structured ACCEPT / VERIFY / ABSTAIN / ESCALATE decisions."
    ),
    version=_PACKAGE_VERSION,
    license_info={"name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    contact={"name": "Stian Skogbrott"},
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler: converts any unhandled exception to a safe JSON 500.

    Ensures that raw exception messages (including DSNs, file paths, or secrets)
    never reach the client.  The correlation_id allows operators to correlate the
    sanitised response with the full stack trace in server logs.
    """
    return _safe_error_response(exc, status_code=500)

_START_TIME = time.time()
_METRICS: dict[str, Any] = {
    "assess_total": 0,
    "assess_errors": 0,
    "auth_failures": 0,
    "review_total": 0,
    "follow_up_total": 0,
    "evidence_total": 0,
    "rerun_total": 0,
    "decision_counts": {
        "accept": 0,
        "verify": 0,
        "abstain": 0,
        "escalate": 0,
    },
    "decision_counts_by_risk": {},
    "total_elapsed_ms": 0.0,
    "latency_bucket_counts": {
        "100": 0,
        "250": 0,
        "500": 0,
        "1000": 0,
        "2000": 0,
        "+Inf": 0,
    },
    "oracle_cost_total_usd": 0.0,
    "oracle_calls_total": 0,
    "slo_breach_counts": {
        "latency_p95": 0,
        "escalation_rate": 0,
        "oracle_cost": 0,
    },
}

_SLO_TARGETS = {
    "latency_p95_ms": float(os.getenv("REMORA_SLO_LATENCY_P95_MS", "2000")),
    "escalation_rate_max": float(os.getenv("REMORA_SLO_ESCALATION_RATE_MAX", "0.30")),
    "oracle_cost_per_assess_usd_max": float(os.getenv("REMORA_SLO_ORACLE_COST_PER_ASSESS_USD_MAX", "0.05")),
}
_LATENCY_BUCKETS_MS = [100.0, 250.0, 500.0, 1000.0, 2000.0]

_BUILTIN_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {"*"},
    "operator": {"assess", "evidence", "rerun", "read"},
    "reviewer": {"review", "follow_up", "read"},
    "domain_expert": {"review", "read"},
    "senior_authority": {"review", "read"},
    "soc_analyst": {"review", "read"},
    "legal_counsel": {"review", "read"},
    "viewer": {"read"},
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _is_production_mode() -> bool:
    return _get_env_mode() in {"prod", "production"}


def _normalize_oracle_backend(backend: str) -> str:
    raw = (backend or "").strip().lower()
    mapping = {
        "openrouter": "recommended",
        "local_vllm": "ollama",
    }
    return mapping.get(raw, raw)


def _validate_production_prerequisites() -> None:
    if not _is_production_mode():
        return

    missing: list[str] = []
    if not os.getenv("REMORA_API_BEARER_TOKEN", "").strip():
        missing.append("REMORA_API_BEARER_TOKEN")
    if not os.getenv("REMORA_CONTROL_PLANE_DSN", "").strip():
        missing.append("REMORA_CONTROL_PLANE_DSN")
    if not os.getenv("REMORA_ORACLE_BACKEND", "").strip():
        missing.append("REMORA_ORACLE_BACKEND")
    if not os.getenv("REMORA_API_TOKENS", "").strip():
        missing.append(
            "REMORA_API_TOKENS (required in production for tenant isolation; "
            "set REMORA_ENV=development to use single-token mode)"
        )

    if missing:
        vars_txt = ", ".join(missing)
        raise RuntimeError(
            "REMORA API production mode fail-closed: missing required env vars: "
            f"{vars_txt}."
        )

    if _env_flag("REMORA_API_ALLOW_MOCK_ORACLES", default=False):
        raise RuntimeError(
            "REMORA API production mode fail-closed: mock oracles are disabled. "
            "Unset REMORA_API_ALLOW_MOCK_ORACLES and configure a real oracle backend."
        )

    backend = _normalize_oracle_backend(os.getenv("REMORA_ORACLE_BACKEND", ""))
    if backend in {"", "mock", "auto"}:
        raise RuntimeError(
            "REMORA API production mode fail-closed: REMORA_ORACLE_BACKEND must be an explicit non-mock backend."
        )


def _make_control_plane_store() -> tuple[ControlPlaneStore, str]:
    dsn = os.getenv("REMORA_CONTROL_PLANE_DSN", "").strip()
    if dsn:
        try:
            return PostgresControlPlaneStore(dsn=dsn), "postgres"
        except Exception as exc:
            if _is_production_mode():
                raise RuntimeError(
                    "REMORA API production mode fail-closed: unable to initialize "
                    "PostgresControlPlaneStore from REMORA_CONTROL_PLANE_DSN."
                ) from exc
            # Fail open to in-memory for local dev if optional deps/backing DB are absent.
            return InMemoryControlPlaneStore(), "in_memory_fallback"
    if _is_production_mode():
        raise RuntimeError(
            "REMORA API production mode fail-closed: REMORA_CONTROL_PLANE_DSN is required."
        )
    return InMemoryControlPlaneStore(), "in_memory"


_validate_production_prerequisites()
_CONTROL_PLANE_STORE, _CONTROL_PLANE_BACKEND = _make_control_plane_store()
_TRACER = get_remora_tracer(service_name="remora-api")


def _metric_int(name: str) -> int:
    v = _METRICS.get(name, 0)
    return int(v) if isinstance(v, (int, float)) else 0


def _metric_float(name: str) -> float:
    v = _METRICS.get(name, 0.0)
    return float(v) if isinstance(v, (int, float)) else 0.0


def _dict_metric(name: str) -> dict[str, Any]:
    v = _METRICS.get(name, {})
    return v if isinstance(v, dict) else {}


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dict(base_value, value)
        else:
            merged[key] = value
    return merged


def _load_risk_profile_config() -> dict[str, Any]:
    cfg_path = Path(os.getenv("REMORA_RISK_PROFILE_PATH", "enterprise/risk-profiles.yaml")).resolve()
    if not cfg_path.exists():
        if _is_production_mode():
            raise RuntimeError(
                "REMORA API production mode fail-closed: risk profile config file is missing."
            )
        return {}

    try:
        import yaml  # type: ignore[import-not-found]

        payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        if _is_production_mode():
            raise RuntimeError(
                "REMORA API production mode fail-closed: unable to parse risk profile config."
            ) from exc
        return {}

    return payload if isinstance(payload, dict) else {}


_RISK_PROFILE_CONFIG = _load_risk_profile_config()


def _make_retrieval_provider() -> StaticJsonlEvidenceProvider | None:
    runtime_path = Path(
        os.getenv(
            "REMORA_RUNTIME_EVIDENCE_JSONL",
            "datasets/remora_knowledge_v1/evidence_packs/runtime_evidence_objects.jsonl",
        )
    ).resolve()
    fallback_path = Path(
        os.getenv(
            "REMORA_BASE_EVIDENCE_JSONL",
            "datasets/remora_knowledge_v1/evidence_packs/evidence_objects.jsonl",
        )
    ).resolve()

    chosen = runtime_path if runtime_path.exists() else fallback_path
    provider = StaticJsonlEvidenceProvider(
        jsonl_path=chosen,
        top_k=max(1, int(os.getenv("REMORA_RETRIEVAL_TOP_K", "5"))),
    )

    if provider.store_size == 0:
        if _is_production_mode():
            raise RuntimeError(
                "REMORA API production mode fail-closed: retrieval evidence store is empty."
            )
        return None
    return provider


_RETRIEVAL_EVIDENCE_PROVIDER = _make_retrieval_provider()
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256_file(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _policy_component_hashes() -> dict[str, str | None]:
    policy_engine_hash = _sha256_file(_REPO_ROOT / "remora" / "policy" / "decision_engine.py")
    risk_profile_hash = _sha256_file(_REPO_ROOT / "enterprise" / "risk-profiles.yaml")
    schema_hash = _sha256_file(_REPO_ROOT / "schemas" / "decision_envelope_schema.yaml")

    opa_policy_hash = None
    opa_path_env = os.getenv("REMORA_OPA_POLICY_PATH", "").strip()
    if opa_path_env:
        opa_path = Path(opa_path_env)
        if not opa_path.is_absolute():
            opa_path = (_REPO_ROOT / opa_path).resolve()
        opa_policy_hash = _sha256_file(opa_path)

    parts = [v for v in (policy_engine_hash, risk_profile_hash, schema_hash, opa_policy_hash) if v]
    composite = None
    if parts:
        composite = "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    return {
        "policy_hash": composite,
        "risk_profile_hash": risk_profile_hash,
        "schema_hash": schema_hash,
        "opa_policy_hash": opa_policy_hash,
    }


def _latest_tenant_audit_hash(tenant_id: str) -> str | None:
    latest = _CONTROL_PLANE_STORE.get_latest_audit_record_for_tenant(tenant_id=tenant_id)
    if not isinstance(latest, dict):
        return None
    envelope_hash = latest.get("envelope_audit_hash")
    if isinstance(envelope_hash, str) and envelope_hash.strip():
        return envelope_hash
    state_hash = latest.get("state_hash")
    if isinstance(state_hash, str) and state_hash.strip():
        return state_hash
    return None


def _sign_envelope_audit_hash(audit_hash: str) -> str | None:
    key = os.getenv("REMORA_ENVELOPE_SIGNING_KEY", "").strip()
    if not key:
        return None
    return hmac.new(
        key.encode("utf-8"),
        audit_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _finalize_envelope_audit(
    *,
    envelope_payload: dict[str, Any],
    tenant_id: str,
    fallback_hash: str | None,
    actor_identity: str | None = None,
) -> dict[str, Any]:
    audit_block = envelope_payload.get("audit") if isinstance(envelope_payload, dict) else None
    if not isinstance(audit_block, dict):
        audit_block = {}
        envelope_payload["audit"] = audit_block

    existing_hash = audit_block.get("hash")
    if not isinstance(existing_hash, str) or not existing_hash.strip():
        if isinstance(fallback_hash, str) and fallback_hash.strip():
            audit_block["hash"] = fallback_hash

    audit_block["previous_hash"] = _latest_tenant_audit_hash(tenant_id)

    signature = None
    audit_hash = audit_block.get("hash")
    if isinstance(audit_hash, str) and audit_hash.strip():
        signature = _sign_envelope_audit_hash(audit_hash)
    audit_block["signature"] = signature

    # Enterprise audit fields
    audit_block["schema_version"] = "2"
    audit_block["timestamp_utc"] = utc_now_iso()
    audit_block["tenant_id"] = tenant_id
    if actor_identity is not None:
        audit_block["actor_identity"] = actor_identity
    elif "actor_identity" not in audit_block:
        audit_block["actor_identity"] = None
    hashes = _policy_component_hashes()
    audit_block["policy_bundle_hash"] = hashes.get("policy_hash")

    # Hash the assessed action for tamper-evident audit (no external infra needed)
    request_block = envelope_payload.get("request") if isinstance(envelope_payload, dict) else None
    if isinstance(request_block, dict):
        canonical_action = json.dumps({
            "proposed_action": request_block.get("proposed_action", ""),
            "action_type": request_block.get("action_type", ""),
        }, sort_keys=True, separators=(",", ":"))
        audit_block["tool_args_hash"] = hashlib.sha256(
            canonical_action.encode("utf-8")
        ).hexdigest()
    elif "tool_args_hash" not in audit_block:
        audit_block["tool_args_hash"] = None

    if "data_classification" not in audit_block:
        audit_block["data_classification"] = None
    if "retention_policy" not in audit_block:
        audit_block["retention_policy"] = None

    return audit_block


def _resolve_tenant_policy_profile(tenant_id: str, risk_tier: str | None) -> tuple[str, dict[str, Any]]:
    profiles = _RISK_PROFILE_CONFIG.get("profiles", {})
    tenant_profiles = _RISK_PROFILE_CONFIG.get("tenant_profiles", {})
    tenant_cfg = tenant_profiles.get(tenant_id, {}) if isinstance(tenant_profiles, dict) else {}

    tier = (risk_tier or "medium").strip().lower()
    tier_default_map = {
        "low": "low_risk",
        "medium": "medium_risk",
        "high": "high_risk",
        "critical": "critical",
    }
    base_name = tenant_cfg.get("base") or tier_default_map.get(tier, "medium_risk")
    base_profile = profiles.get(base_name, {}) if isinstance(profiles, dict) else {}

    tenant_override = {k: v for k, v in tenant_cfg.items() if k != "base"} if isinstance(tenant_cfg, dict) else {}
    merged = _deep_merge_dict(base_profile if isinstance(base_profile, dict) else {}, tenant_override)
    return str(base_name), merged


def _extract_review_requirements(profile: dict[str, Any]) -> dict[str, Any]:
    action = profile.get("action", {}) if isinstance(profile, dict) else {}
    return {
        "require_human_approval": bool(action.get("require_human_approval", False)),
        "approval_role": action.get("approval_role"),
        "enforce_human_in_the_loop": bool(action.get("enforce_human_in_the_loop", False)),
    }


def _role_permissions_map() -> dict[str, set[str]]:
    access_defaults = _RISK_PROFILE_CONFIG.get("access_defaults", {})
    role_permissions_cfg = access_defaults.get("role_permissions", {}) if isinstance(access_defaults, dict) else {}
    if not isinstance(role_permissions_cfg, dict) or not role_permissions_cfg:
        return _BUILTIN_ROLE_PERMISSIONS

    out: dict[str, set[str]] = {}
    for role, caps in role_permissions_cfg.items():
        if isinstance(role, str) and isinstance(caps, list):
            out[role.strip().lower()] = {str(c).strip().lower() for c in caps}
    return out or _BUILTIN_ROLE_PERMISSIONS


def _tenant_access_policy(tenant_id: str) -> dict[str, Any]:
    access_defaults = _RISK_PROFILE_CONFIG.get("access_defaults", {})
    tenant_defaults = access_defaults.get("tenant_defaults", {}) if isinstance(access_defaults, dict) else {}
    tenant_access = _RISK_PROFILE_CONFIG.get("tenant_access", {})
    tenant_override = tenant_access.get(tenant_id, {}) if isinstance(tenant_access, dict) else {}
    base = tenant_defaults if isinstance(tenant_defaults, dict) else {}
    override = tenant_override if isinstance(tenant_override, dict) else {}
    return _deep_merge_dict(base, override)


def _role_from_request(request: Request) -> str:
    role = request.headers.get("X-Remora-Role", "").strip().lower()
    if role:
        return role
    access_defaults = _RISK_PROFILE_CONFIG.get("access_defaults", {})
    default_role = ""   # explicit role required — empty = no permissions
    if isinstance(access_defaults, dict):
        raw = str(access_defaults.get("default_role", "")).strip().lower()
        if raw:
            default_role = raw
    role = default_role
    # Never silently promote an unset/empty role to something with permissions.
    # Known-bad values (empty string, whitespace) resolve to no-access.
    # Tenant-specific roles (e.g. "reviewer", "domain_expert") are accepted;
    # _require_tenant_capability validates them against the permissions map.
    return role.strip() or ""


def _require_tenant_capability(request: Request, tenant_id: str, capability: str) -> str:
    role = _role_from_request(request)
    capability_key = capability.strip().lower()
    tenant_policy = _tenant_access_policy(tenant_id)
    allowed_roles = tenant_policy.get("allowed_roles", []) if isinstance(tenant_policy, dict) else []
    allowed_role_set = {
        str(r).strip().lower() for r in allowed_roles if isinstance(r, str)
    }
    if allowed_role_set and role not in allowed_role_set:
        raise HTTPException(status_code=403, detail="role not allowed for tenant")

    role_permissions = _role_permissions_map()
    permissions = role_permissions.get(role, set())
    if "*" in permissions or capability_key in permissions:
        return role
    raise HTTPException(status_code=403, detail=f"role {role} cannot perform {capability_key}")


def _enforce_review_approval_role(
    *,
    role: str,
    tenant_id: str,
    decision: str,
    review_requirements: dict[str, Any],
) -> None:
    if decision != "approved":
        return

    tenant_policy = _tenant_access_policy(tenant_id)
    reviewer_roles = tenant_policy.get("reviewer_roles", []) if isinstance(tenant_policy, dict) else []
    reviewer_role_set = {
        str(r).strip().lower() for r in reviewer_roles if isinstance(r, str)
    }
    if reviewer_role_set and role not in reviewer_role_set:
        raise HTTPException(status_code=403, detail="role is not allowed to approve reviews for this tenant")

    required_role_raw = review_requirements.get("approval_role")
    if not required_role_raw:
        return
    required_role = str(required_role_raw).strip().lower()
    if role not in {required_role, "admin"}:
        raise HTTPException(
            status_code=403,
            detail=f"approval requires role {required_role}",
        )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AssessRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4096)
    context: Optional[str] = Field(None, max_length=16384)
    domain: Optional[str] = Field(None, max_length=128)
    risk_tier: Optional[str] = Field(None, pattern=r"^(low|medium|high|critical)$")
    action_type: Optional[str] = Field(None, max_length=128)
    target_environment: Optional[str] = Field(None, max_length=128)

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be whitespace-only")
        return v


class PolicyDecision(BaseModel):
    action: str
    reasons: list[str]
    risk_estimate: Optional[float]
    confidence: Optional[float]
    human_review_required: bool
    evidence_required: bool
    explanation: str
    source_of_decision: str
    policy_version: str
    in_sample_calibration_warning: Optional[str]
    fallback_used: bool


class AssessResponse(BaseModel):
    request_id: str
    question_hash: str
    elapsed_ms: float
    policy_decision: PolicyDecision
    thermodynamic: dict
    oracle_calls: int
    total_cost_usd: float
    require_rag: bool
    refuse_parametric_verdict: bool
    state_hash: str
    envelope: dict
    policy_profile: str
    review_requirements: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    oracle_count: int


class ReviewRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=128)
    reviewer_id: str = Field(..., min_length=1, max_length=128)
    decision: Literal["approved", "rejected", "needs_more_evidence"]
    reason: str = Field(..., min_length=3, max_length=4096)
    evidence_refs: list[str] = Field(default_factory=list, max_length=64)


class FollowUpRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=128)
    follow_up_type: Literal["evidence_request", "override_request", "manual_escalation", "incident"]
    payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: Optional[str] = Field(None, max_length=128)


class EvidenceRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=128)
    evidence_type: str = Field(..., min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    submitted_by: Optional[str] = Field(None, max_length=128)


class RerunRequest(BaseModel):
    request_id: str = Field(..., min_length=8, max_length=128)


def _summarize_evidence_for_context(evidence_rows: list[dict[str, Any]]) -> str:
    """Build compact deterministic context text from persisted evidence rows."""
    if not evidence_rows:
        return ""

    lines: list[str] = ["Persisted evidence attached to this request:"]
    for row in evidence_rows[:10]:
        e_type = str(row.get("evidence_type", "unknown"))
        submitted_by = row.get("submitted_by")
        payload = row.get("payload")
        payload_txt = json.dumps(payload, sort_keys=True)[:512] if isinstance(payload, dict) else str(payload)[:512]
        who = f" by {submitted_by}" if submitted_by else ""
        lines.append(f"- {e_type}{who}: {payload_txt}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine factory — replace with a singleton pool in production
# ---------------------------------------------------------------------------

def _make_engine() -> Remora:
    """Return a Remora instance with configured oracle backend."""
    from remora.oracles.factory import build_swarm

    prod = _is_production_mode()
    backend_raw = os.getenv("REMORA_ORACLE_BACKEND", "mock")
    backend = _normalize_oracle_backend(backend_raw)
    if prod and backend in {"", "mock", "auto"}:
        raise RuntimeError(
            "REMORA API production mode fail-closed: configure REMORA_ORACLE_BACKEND with a non-mock backend."
        )

    try:
        if backend:
            oracles = build_swarm(backend=backend)
        else:
            oracles = [MockOracle(f"mock_{i}", bias=True, noise=0.1) for i in range(3)]
    except Exception as exc:
        if prod:
            raise RuntimeError(
                "REMORA API production mode fail-closed: unable to initialize configured oracle backend."
            ) from exc
        oracles = [MockOracle(f"mock_{i}", bias=True, noise=0.1) for i in range(3)]

    genome = Genome(
        max_iterations=2,
        max_subquestions=1,
        enable_parallel_fanout=True,
        enable_thermodynamic_control=True,
        enable_routing=True,
    )
    return Remora(
        oracles=oracles,
        genome=genome,
        retrieval_evidence_provider=_RETRIEVAL_EVIDENCE_PROVIDER,
    )


def _load_token_table() -> dict[str, tuple[str, str]]:
    """Load per-token tenant+role bindings from REMORA_API_TOKENS env var.

    Format: JSON object mapping opaque token -> {"tenant": "...", "role": "..."}
    Example: export REMORA_API_TOKENS='{"tok_abc":{"tenant":"acme","role":"operator"}}'

    Falls back to single-token mode (REMORA_API_BEARER_TOKEN) for dev/single-tenant.
    In production mode (REMORA_ENV=production), REMORA_API_TOKENS MUST be set.
    """
    raw = os.getenv("REMORA_API_TOKENS", "").strip()
    if not raw:
        return {}
    _VALID_ROLES_SET = {"admin", "operator", "auditor", "viewer"}
    try:
        table = json.loads(raw)
        if not isinstance(table, dict):
            raise ValueError("REMORA_API_TOKENS must be a JSON object")
        result: dict[str, tuple[str, str]] = {}
        for token, v in table.items():
            if not token or not isinstance(token, str):
                raise ValueError(f"token key must be a non-empty string, got {token!r}")
            if not isinstance(v, dict):
                raise ValueError(f"token entry must be an object, got {v!r}")
            tenant = str(v.get("tenant", "")).strip()
            role   = str(v.get("role",   "")).strip().lower()
            if not tenant:
                raise ValueError(f"token {token!r}: 'tenant' must be non-empty")
            if role not in _VALID_ROLES_SET:
                raise ValueError(f"token {token!r}: role {role!r} not in {_VALID_ROLES_SET}")
            result[token] = (tenant, role)
        return result
    except Exception as exc:
        # Malformed REMORA_API_TOKENS means callers cannot be authenticated.
        # Fail hard at startup — do not silently fall through to no-auth mode.
        raise RuntimeError(
            f"REMORA_API_TOKENS is set but could not be parsed: {exc}. "
            "Fix the env var or unset it to use single-token mode."
        ) from exc

_TOKEN_TABLE = _load_token_table()


def _authenticate(request: Request) -> tuple[str, str]:
    """Return (tenant_id, role) derived exclusively from the bearer credential.

    Priority:
      1. Multi-tenant mode  (REMORA_API_TOKENS set): token → fixed (tenant, role).
         Callers cannot forge tenant or role via headers.
      2. Single-token mode  (REMORA_API_BEARER_TOKEN set): validates token, then
         reads tenant/role from headers (defaults: 'default' / 'operator').
         Tenant-specific roles (e.g. 'domain_expert') are accepted; downstream
         capability checks validate them against the tenant policy.
      3. No-auth dev mode   (neither set, REMORA_ENV=development): dev fallback.
         Production with no credentials configured is a startup error.
    """
    # ── Determine which auth mode is active ──────────────────────────────
    has_token_table  = bool(_TOKEN_TABLE)
    single_token     = os.getenv("REMORA_API_BEARER_TOKEN", "").strip()

    # No credentials configured at all
    if not has_token_table and not single_token:
        if _get_env_mode() not in {"development", "dev"}:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Server misconfiguration: no auth credentials set. "
                    "Set REMORA_API_TOKENS or REMORA_API_BEARER_TOKEN, "
                    "or set REMORA_ENV=development to run without auth."
                ),
            )
        # Dev fallback — no bearer required
        return "default", "operator"

    # ── Validate bearer token ─────────────────────────────────────────────
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = auth[len("Bearer "):].strip()

    # Multi-tenant mode
    if has_token_table:
        for token, (tenant, role) in _TOKEN_TABLE.items():
            if hmac.compare_digest(provided, token):
                return tenant, role
        raise HTTPException(status_code=401, detail="invalid bearer token")

    # Single-token mode
    if not hmac.compare_digest(provided, single_token):
        raise HTTPException(status_code=401, detail="invalid bearer token")
    tenant = request.headers.get("X-Remora-Tenant", "default").strip() or "default"
    role   = request.headers.get("X-Remora-Role", "operator").strip().lower() or "operator"
    return tenant, role


def _require_bearer_auth(request: Request) -> None:
    """Optional API key auth.

    If REMORA_API_BEARER_TOKEN is set, callers must send
    Authorization: Bearer <token>.
    """
    expected = os.getenv("REMORA_API_BEARER_TOKEN")
    if not expected:
        return

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        _METRICS["auth_failures"] = _metric_int("auth_failures") + 1
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = auth[len("Bearer "):].strip()
    if not hmac.compare_digest(provided, expected):
        _METRICS["auth_failures"] = _metric_int("auth_failures") + 1
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _tenant_id_from_request(request: Request) -> str:
    tenant = request.headers.get("X-Remora-Tenant", "default").strip()
    return tenant or "default"


def _record_artifacts(
    request_id: str,
    tenant_id: str,
    question_hash: str,
    req: AssessRequest,
    elapsed_ms: float,
    report: dict,
    envelope_payload: dict,
) -> None:
    """Store envelope/audit artifacts in tenant-scoped control-plane persistence."""

    pd = report["policy_decision"]
    env_audit = envelope_payload.get("audit", {}) if isinstance(envelope_payload, dict) else {}
    audit_record = {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "timestamp_utc": utc_now_iso(),
        "question_hash": question_hash,
        "state_hash": report.get("state_hash"),
        "domain": req.domain,
        "risk_tier": req.risk_tier,
        "action_type": req.action_type,
        "target_environment": req.target_environment,
        "policy_version": pd.get("policy_version"),
        "decision": pd.get("action"),
        "reasons": pd.get("reasons", []),
        "source_of_decision": pd.get("source_of_decision"),
        "human_review_required": pd.get("human_review_required", False),
        "evidence_required": pd.get("evidence_required", False),
        "fallback_used": pd.get("fallback_used", False),
        "envelope_audit_hash": env_audit.get("hash") if isinstance(env_audit, dict) else None,
        "envelope_previous_hash": env_audit.get("previous_hash") if isinstance(env_audit, dict) else None,
        "envelope_signature": env_audit.get("signature") if isinstance(env_audit, dict) else None,
        "oracle_calls": report.get("oracle_calls"),
        "elapsed_ms": elapsed_ms,
    }
    _CONTROL_PLANE_STORE.save_decision(
        request_id=request_id,
        tenant_id=tenant_id,
        envelope=envelope_payload,
        audit_record=audit_record,
    )


def _record_metrics(
    decision_action: str,
    elapsed_ms: float,
    *,
    risk_tier: str | None,
    total_cost_usd: float | None,
    oracle_calls: int | None,
) -> None:
    _METRICS["assess_total"] = _metric_int("assess_total") + 1
    _METRICS["total_elapsed_ms"] = _metric_float("total_elapsed_ms") + elapsed_ms
    _METRICS["oracle_cost_total_usd"] = _metric_float("oracle_cost_total_usd") + float(total_cost_usd or 0.0)
    _METRICS["oracle_calls_total"] = _metric_int("oracle_calls_total") + int(oracle_calls or 0)

    for bound in _LATENCY_BUCKETS_MS:
        if elapsed_ms <= bound:
            key = str(int(bound))
            buckets = _dict_metric("latency_bucket_counts")
            buckets[key] = int(buckets.get(key, 0)) + 1
    buckets = _dict_metric("latency_bucket_counts")
    buckets["+Inf"] = int(buckets.get("+Inf", 0)) + 1

    counts = _METRICS["decision_counts"]
    if isinstance(counts, dict) and decision_action in counts:
        counts[decision_action] = int(counts[decision_action]) + 1

    risk = (risk_tier or "unknown").strip().lower() or "unknown"
    by_risk = _dict_metric("decision_counts_by_risk")
    risk_counts = by_risk.setdefault(risk, {
        "accept": 0,
        "verify": 0,
        "abstain": 0,
        "escalate": 0,
    })
    if decision_action in risk_counts:
        risk_counts[decision_action] = int(risk_counts[decision_action]) + 1

    breaches = _dict_metric("slo_breach_counts")
    if elapsed_ms > _SLO_TARGETS["latency_p95_ms"]:
        breaches["latency_p95"] = int(breaches.get("latency_p95", 0)) + 1

    total = _metric_int("assess_total")
    escalates = int(_dict_metric("decision_counts").get("escalate", 0))
    escalation_rate = (escalates / total) if total > 0 else 0.0
    if escalation_rate > _SLO_TARGETS["escalation_rate_max"]:
        breaches["escalation_rate"] = int(breaches.get("escalation_rate", 0)) + 1

    req_cost = float(total_cost_usd or 0.0)
    if req_cost > _SLO_TARGETS["oracle_cost_per_assess_usd_max"]:
        breaches["oracle_cost"] = int(breaches.get("oracle_cost", 0)) + 1


def _prometheus_metrics_text() -> str:
    uptime = round(time.time() - _START_TIME, 1)
    counts = _METRICS["decision_counts"]
    decision_counts = counts if isinstance(counts, dict) else {}
    assess_total = _metric_int("assess_total")
    total_elapsed = _metric_float("total_elapsed_ms")
    mean_elapsed = (total_elapsed / assess_total) if assess_total > 0 else 0.0
    escalates = int(decision_counts.get("escalate", 0))
    escalation_rate = (escalates / assess_total) if assess_total > 0 else 0.0
    cost_total = _metric_float("oracle_cost_total_usd")
    avg_cost = (cost_total / assess_total) if assess_total > 0 else 0.0
    slo_breaches = _dict_metric("slo_breach_counts")
    latency_buckets = _dict_metric("latency_bucket_counts")
    decision_by_risk = _dict_metric("decision_counts_by_risk")

    lines = [
        "# HELP remora_uptime_seconds Process uptime in seconds.",
        "# TYPE remora_uptime_seconds gauge",
        f"remora_uptime_seconds {uptime}",
        "# HELP remora_assess_total Number of assessment requests.",
        "# TYPE remora_assess_total counter",
        f"remora_assess_total {_metric_int('assess_total')}",
        "# HELP remora_assess_errors_total Number of failed assessment requests.",
        "# TYPE remora_assess_errors_total counter",
        f"remora_assess_errors_total {_metric_int('assess_errors')}",
        "# HELP remora_auth_failures_total Number of auth failures.",
        "# TYPE remora_auth_failures_total counter",
        f"remora_auth_failures_total {_metric_int('auth_failures')}",
        "# HELP remora_reviews_total Number of review decisions submitted.",
        "# TYPE remora_reviews_total counter",
        f"remora_reviews_total {_metric_int('review_total')}",
        "# HELP remora_followups_total Number of follow-up requests submitted.",
        "# TYPE remora_followups_total counter",
        f"remora_followups_total {_metric_int('follow_up_total')}",
        "# HELP remora_assess_latency_mean_ms Mean assessment latency in milliseconds.",
        "# TYPE remora_assess_latency_mean_ms gauge",
        f"remora_assess_latency_mean_ms {round(mean_elapsed, 3)}",
        "# HELP remora_escalation_rate Current escalation rate.",
        "# TYPE remora_escalation_rate gauge",
        f"remora_escalation_rate {round(escalation_rate, 6)}",
        "# HELP remora_oracle_cost_per_assess_usd Mean oracle cost per assessment.",
        "# TYPE remora_oracle_cost_per_assess_usd gauge",
        f"remora_oracle_cost_per_assess_usd {round(avg_cost, 6)}",
        "# HELP remora_slo_target_latency_p95_ms Configured SLO target for p95 latency.",
        "# TYPE remora_slo_target_latency_p95_ms gauge",
        f"remora_slo_target_latency_p95_ms {_SLO_TARGETS['latency_p95_ms']}",
        "# HELP remora_slo_target_escalation_rate_max Configured SLO target for max escalation rate.",
        "# TYPE remora_slo_target_escalation_rate_max gauge",
        f"remora_slo_target_escalation_rate_max {_SLO_TARGETS['escalation_rate_max']}",
        "# HELP remora_slo_target_oracle_cost_per_assess_usd_max Configured SLO target for max per-assess oracle cost.",
        "# TYPE remora_slo_target_oracle_cost_per_assess_usd_max gauge",
        f"remora_slo_target_oracle_cost_per_assess_usd_max {_SLO_TARGETS['oracle_cost_per_assess_usd_max']}",
        "# HELP remora_slo_breach_total Number of SLO breaches by type.",
        "# TYPE remora_slo_breach_total counter",
    ]
    for key in ("accept", "verify", "abstain", "escalate"):
        lines.append(f'remora_decision_total{{action="{key}"}} {int(decision_counts.get(key, 0))}')
    for breach_key in ("latency_p95", "escalation_rate", "oracle_cost"):
        lines.append(
            f'remora_slo_breach_total{{type="{breach_key}"}} {int(slo_breaches.get(breach_key, 0))}'
        )

    lines.extend([
        "# HELP remora_assess_latency_ms_bucket Assessment latency histogram bucket counts.",
        "# TYPE remora_assess_latency_ms_bucket counter",
    ])
    for key in ("100", "250", "500", "1000", "2000", "+Inf"):
        lines.append(f'remora_assess_latency_ms_bucket{{le="{key}"}} {int(latency_buckets.get(key, 0))}')
    lines.extend([
        "# HELP remora_assess_latency_ms_count Total latency observations.",
        "# TYPE remora_assess_latency_ms_count counter",
        f"remora_assess_latency_ms_count {assess_total}",
    ])

    lines.extend([
        "# HELP remora_decision_by_risk_total Decision counts partitioned by risk tier.",
        "# TYPE remora_decision_by_risk_total counter",
    ])
    for risk, risk_counts in decision_by_risk.items():
        if not isinstance(risk_counts, dict):
            continue
        for action in ("accept", "verify", "abstain", "escalate"):
            lines.append(
                f'remora_decision_by_risk_total{{risk_tier="{risk}",action="{action}"}} '
                f'{int(risk_counts.get(action, 0))}'
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/v1/health", response_model=HealthResponse, tags=["infrastructure"])
def health() -> HealthResponse:
    """Liveness probe — returns 200 when the gateway is ready."""
    return HealthResponse(
        status="ok",
        version=_PACKAGE_VERSION,
        uptime_seconds=round(time.time() - _START_TIME, 1),
        oracle_count=3,
    )


@app.post("/v1/assess", response_model=AssessResponse, tags=["governance"])
def assess(req: AssessRequest, request: Request) -> AssessResponse:
    """Assess an agent action proposal through the full REMORA pipeline.

    Returns a structured governance decision with thermodynamic observables,
    policy action (ACCEPT/VERIFY/ABSTAIN/ESCALATE), and audit metadata.
    """
    t0 = time.monotonic()

    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "assess")

    # Rate limiting — per-tenant sliding window
    if not _rate_limiter.is_allowed(f"assess:{tenant_id}"):
        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit exceeded for /v1/assess. "
                "Reduce request frequency or contact support to increase your quota."
            ),
            headers={"Retry-After": "60"},
        )

    _actor_identity = request.headers.get("X-Remora-Actor", "").strip() or None
    profile_name, profile_cfg = _resolve_tenant_policy_profile(tenant_id, req.risk_tier)
    review_requirements = _extract_review_requirements(profile_cfg)

    engine = _make_engine()
    try:
        with _TRACER.query_span(req.question, remora_endpoint="/v1/assess", tenant_id=tenant_id) as span:
            span.set_attribute("remora.domain", req.domain)
            span.set_attribute("remora.risk_tier", req.risk_tier)
            with _TRACER.stage_span("api_gateway", tenant_id=tenant_id):
                state = engine.run(
                    question=req.question,
                    context=req.context,
                    domain=req.domain,
                    risk_tier=req.risk_tier,
                    action_type=req.action_type,
                    target_environment=req.target_environment,
                )
                report = engine.report(state)
            policy = report.get("policy_decision", {})
            span.set_outcome(
                action=str(policy.get("action", "unknown")),
                confidence=policy.get("confidence"),
                risk_estimate=policy.get("risk_estimate"),
            )
    except Exception as exc:
        _METRICS["assess_errors"] = _metric_int("assess_errors") + 1
        return _safe_error_response(exc, status_code=500)

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    pd = report["policy_decision"]
    traj = report.get("trajectory", [])
    last = traj[-1] if traj else {}

    q_hash = hashlib.sha256(req.question.encode()).hexdigest()[:16]
    request_id = f"{q_hash}-{int(t0 * 1000) % 1_000_000:06d}"
    env = report.get("envelope")
    if env is not None and hasattr(env, "to_dict"):
        envelope_payload = env.to_dict()
    elif isinstance(env, dict):
        envelope_payload = env
    else:
        envelope_payload = {}

    req_block = envelope_payload.get("request") if isinstance(envelope_payload, dict) else None
    if isinstance(req_block, dict):
        req_block["request_id"] = request_id

    _finalize_envelope_audit(
        envelope_payload=envelope_payload,
        tenant_id=tenant_id,
        fallback_hash=report.get("state_hash"),
        actor_identity=_actor_identity,
    )

    _record_artifacts(
        request_id=request_id,
        tenant_id=tenant_id,
        question_hash=q_hash,
        req=req,
        elapsed_ms=elapsed_ms,
        report=report,
        envelope_payload=envelope_payload,
    )
    _record_metrics(
        decision_action=pd["action"],
        elapsed_ms=elapsed_ms,
        risk_tier=req.risk_tier,
        total_cost_usd=report.get("total_cost_usd"),
        oracle_calls=report.get("oracle_calls"),
    )

    try:
        with _TRACER.stage_span("api_observability", tenant_id=tenant_id) as obs_span:
            obs_span.set_attribute("remora.elapsed_ms", elapsed_ms)
            obs_span.set_attribute("remora.oracle_calls", report.get("oracle_calls"))
            obs_span.set_attribute("remora.oracle_cost_usd", report.get("total_cost_usd"))
            obs_span.set_attribute(
                "remora.slo.latency_breach",
                elapsed_ms > _SLO_TARGETS["latency_p95_ms"],
            )
            obs_span.set_attribute(
                "remora.slo.oracle_cost_breach",
                float(report.get("total_cost_usd") or 0.0) > _SLO_TARGETS["oracle_cost_per_assess_usd_max"],
            )
    except Exception:
        pass

    return AssessResponse(
        request_id=request_id,
        question_hash=q_hash,
        elapsed_ms=elapsed_ms,
        policy_decision=PolicyDecision(
            action=pd["action"],
            reasons=pd["reasons"],
            risk_estimate=pd.get("risk_estimate"),
            confidence=pd.get("confidence"),
            human_review_required=pd["human_review_required"],
            evidence_required=pd["evidence_required"],
            explanation=pd["explanation"],
            source_of_decision=pd["source_of_decision"],
            policy_version=pd["policy_version"],
            in_sample_calibration_warning=pd.get("in_sample_calibration_warning"),
            fallback_used=pd.get("fallback_used", False),
        ),
        thermodynamic={
            "V": last.get("V"),
            "H": last.get("H"),
            "D": last.get("D"),
            "final_entropy": report.get("final_entropy"),
            "is_converging": report.get("is_converging"),
        },
        oracle_calls=report["oracle_calls"],
        total_cost_usd=report["total_cost_usd"],
        require_rag=report["require_rag"],
        refuse_parametric_verdict=report["refuse_parametric_verdict"],
        state_hash=report["state_hash"],
        envelope=envelope_payload,
        policy_profile=profile_name,
        review_requirements=review_requirements,
    )


@app.get("/v1/envelope/{request_id}", response_model=dict, tags=["governance"])
def get_envelope(request_id: str, request: Request) -> dict:
    """Fetch a previously generated DecisionEnvelope by request id."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "read")
    env = _CONTROL_PLANE_STORE.get_envelope(request_id=request_id, tenant_id=tenant_id)
    if env is None:
        raise HTTPException(status_code=404, detail="envelope not found")
    return {
        "request_id": request_id,
        "tenant_id": tenant_id,
        "envelope": env,
    }


@app.get("/v1/audit/{request_id}", response_model=dict, tags=["governance"])
def get_audit_record(request_id: str, request: Request) -> dict:
    """Fetch structured audit metadata for a request id."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "read")
    record = _CONTROL_PLANE_STORE.get_audit_record(request_id=request_id, tenant_id=tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail="audit record not found")
    return record


@app.post("/v1/review", response_model=dict, tags=["governance"])
def review(req: ReviewRequest, request: Request) -> dict:
    """Submit a human review decision for a previously assessed request."""
    tenant_id, role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "review")
    envelope = _CONTROL_PLANE_STORE.get_envelope(request_id=req.request_id, tenant_id=tenant_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="request not found")
    env_req = envelope.get("request", {}) if isinstance(envelope, dict) else {}
    risk_tier = env_req.get("risk_tier") if isinstance(env_req, dict) else None
    _, profile_cfg = _resolve_tenant_policy_profile(tenant_id, str(risk_tier) if risk_tier is not None else None)
    review_requirements = _extract_review_requirements(profile_cfg)
    _enforce_review_approval_role(
        role=role,
        tenant_id=tenant_id,
        decision=req.decision,
        review_requirements=review_requirements,
    )

    _CONTROL_PLANE_STORE.create_review(
        ReviewRecord(
            request_id=req.request_id,
            tenant_id=tenant_id,
            reviewer_id=req.reviewer_id,
            decision=req.decision,
            reason=req.reason,
            evidence_refs=req.evidence_refs,
            created_at=utc_now_iso(),
        )
    )
    _METRICS["review_total"] = _metric_int("review_total") + 1
    return {
        "status": "recorded",
        "request_id": req.request_id,
        "tenant_id": tenant_id,
        "decision": req.decision,
    }


@app.post("/v1/follow-up", response_model=dict, tags=["governance"])
def follow_up(req: FollowUpRequest, request: Request) -> dict:
    """Submit follow-up actions tied to an assessed request."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "follow_up")
    if _CONTROL_PLANE_STORE.get_envelope(request_id=req.request_id, tenant_id=tenant_id) is None:
        raise HTTPException(status_code=404, detail="request not found")

    _CONTROL_PLANE_STORE.create_follow_up(
        FollowUpRecord(
            request_id=req.request_id,
            tenant_id=tenant_id,
            follow_up_type=req.follow_up_type,
            requested_by=req.requested_by,
            payload=req.payload,
            created_at=utc_now_iso(),
        )
    )
    _METRICS["follow_up_total"] = _metric_int("follow_up_total") + 1
    return {
        "status": "recorded",
        "request_id": req.request_id,
        "tenant_id": tenant_id,
        "follow_up_type": req.follow_up_type,
    }


@app.get("/v1/metrics", response_model=dict, tags=["infrastructure"])
def metrics(request: Request) -> dict:
    """Basic governance gateway metrics for prototype observability."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "read")
    total = _metric_int("assess_total")
    total_elapsed = _metric_float("total_elapsed_ms")
    mean_elapsed = round(total_elapsed / total, 3) if total else 0.0
    decision_counts = _dict_metric("decision_counts")
    escalates = int(decision_counts.get("escalate", 0))
    escalation_rate = round((escalates / total), 6) if total else 0.0
    avg_oracle_cost = round((_metric_float("oracle_cost_total_usd") / total), 6) if total else 0.0
    return {
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "assess_total": total,
        "assess_errors": _metric_int("assess_errors"),
        "auth_failures": _metric_int("auth_failures"),
        "review_total": _metric_int("review_total"),
        "follow_up_total": _metric_int("follow_up_total"),
        "evidence_total": _metric_int("evidence_total"),
        "rerun_total": _metric_int("rerun_total"),
        "control_plane_backend": _CONTROL_PLANE_BACKEND,
        "decision_counts": decision_counts,
        "decision_counts_by_risk": _dict_metric("decision_counts_by_risk"),
        "latency_buckets_ms": _dict_metric("latency_bucket_counts"),
        "mean_assess_latency_ms": mean_elapsed,
        "escalation_rate": escalation_rate,
        "avg_oracle_cost_per_assess_usd": avg_oracle_cost,
        "slo": {
            "targets": {
                "latency_p95_ms": _SLO_TARGETS["latency_p95_ms"],
                "escalation_rate_max": _SLO_TARGETS["escalation_rate_max"],
                "oracle_cost_per_assess_usd_max": _SLO_TARGETS["oracle_cost_per_assess_usd_max"],
            },
            "current": {
                "mean_latency_ms": mean_elapsed,
                "escalation_rate": escalation_rate,
                "avg_oracle_cost_per_assess_usd": avg_oracle_cost,
            },
            "breaches": _dict_metric("slo_breach_counts"),
        },
    }


@app.get("/metrics", response_class=PlainTextResponse, tags=["infrastructure"])
def metrics_prometheus(request: Request) -> PlainTextResponse:
    """Prometheus exposition endpoint for gateway metrics."""
    if os.getenv("REMORA_PROMETHEUS_PUBLIC", "").lower() not in {"1", "true", "yes"}:
        _authenticate(request)
    return PlainTextResponse(_prometheus_metrics_text(), media_type="text/plain; version=0.0.4")


@app.get("/v1/policy/version", response_model=dict, tags=["governance"])
def policy_version(request: Request) -> dict:
    """Expose active policy-engine version metadata for audit/replay clients."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "read")
    version = DecisionReport.__dataclass_fields__["policy_version"].default
    hashes = _policy_component_hashes()
    return {
        "policy_version": str(version),
        "policy_hash": hashes["policy_hash"],
        "risk_profile_hash": hashes["risk_profile_hash"],
        "schema_hash": hashes["schema_hash"],
        "opa_policy_hash": hashes["opa_policy_hash"],
        "source": "python_decision_engine",
        "runtime_mode": "production" if _is_production_mode() else "development",
    }


@app.post("/v1/evidence", response_model=dict, tags=["governance"])
def evidence(req: EvidenceRequest, request: Request) -> dict:
    """Attach external evidence payloads to a tenant-scoped request record."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "evidence")
    if _CONTROL_PLANE_STORE.get_envelope(request_id=req.request_id, tenant_id=tenant_id) is None:
        raise HTTPException(status_code=404, detail="request not found")

    _CONTROL_PLANE_STORE.create_evidence(
        EvidenceRecord(
            request_id=req.request_id,
            tenant_id=tenant_id,
            evidence_type=req.evidence_type,
            payload=req.payload,
            submitted_by=req.submitted_by,
            created_at=utc_now_iso(),
        )
    )
    _METRICS["evidence_total"] = _metric_int("evidence_total") + 1
    return {
        "status": "recorded",
        "request_id": req.request_id,
        "tenant_id": tenant_id,
        "evidence_type": req.evidence_type,
    }


@app.post("/v1/rerun", response_model=dict, tags=["governance"])
def rerun(req: RerunRequest, request: Request) -> dict:
    """Re-run governance assessment with the same persisted request context."""
    tenant_id, _caller_role = _authenticate(request)
    _require_tenant_capability(request, tenant_id, "rerun")
    prior = _CONTROL_PLANE_STORE.get_envelope(request_id=req.request_id, tenant_id=tenant_id)
    if prior is None:
        raise HTTPException(status_code=404, detail="request not found")

    req_block = prior.get("request", {}) if isinstance(prior, dict) else {}
    if not isinstance(req_block, dict) or not str(req_block.get("proposed_action", "")).strip():
        raise HTTPException(status_code=422, detail="stored envelope lacks replayable request block")

    evidence_rows = _CONTROL_PLANE_STORE.get_evidence(request_id=req.request_id, tenant_id=tenant_id)
    evidence_context = _summarize_evidence_for_context(evidence_rows)
    replay_mode = "same_input_plus_evidence" if evidence_rows else "same_input"

    replay_request = AssessRequest(
        question=str(req_block.get("proposed_action", "")),
        context=evidence_context or None,
        domain=(str(req_block.get("domain", "")) or None),
        risk_tier=(str(req_block.get("risk_tier", "")) or None),
        action_type=(str(req_block.get("action_type", "")) or None),
        target_environment=(str(req_block.get("target_environment", "")) or None),
    )

    t0 = time.monotonic()
    engine = _make_engine()
    try:
        state = engine.run(
            question=replay_request.question,
            context=replay_request.context,
            domain=replay_request.domain,
            risk_tier=replay_request.risk_tier,
            action_type=replay_request.action_type,
            target_environment=replay_request.target_environment,
            external_evidence=evidence_rows,
        )
        report = engine.report(state)
    except Exception as exc:
        _METRICS["assess_errors"] = _metric_int("assess_errors") + 1
        return _safe_error_response(exc, status_code=500)

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    q_hash = hashlib.sha256(replay_request.question.encode()).hexdigest()[:16]
    rerun_request_id = f"{q_hash}-rerun-{int(t0 * 1000) % 1_000_000:06d}"

    env = report.get("envelope")
    if env is not None and hasattr(env, "to_dict"):
        envelope_payload = env.to_dict()
    elif isinstance(env, dict):
        envelope_payload = env
    else:
        envelope_payload = {}

    req_payload = envelope_payload.get("request") if isinstance(envelope_payload, dict) else None
    if isinstance(req_payload, dict):
        req_payload["request_id"] = rerun_request_id

    _finalize_envelope_audit(
        envelope_payload=envelope_payload,
        tenant_id=tenant_id,
        fallback_hash=report.get("state_hash"),
    )

    _record_artifacts(
        request_id=rerun_request_id,
        tenant_id=tenant_id,
        question_hash=q_hash,
        req=replay_request,
        elapsed_ms=elapsed_ms,
        report=report,
        envelope_payload=envelope_payload,
    )
    pd = report["policy_decision"]
    _record_metrics(
        decision_action=pd["action"],
        elapsed_ms=elapsed_ms,
        risk_tier=replay_request.risk_tier,
        total_cost_usd=report.get("total_cost_usd"),
        oracle_calls=report.get("oracle_calls"),
    )
    _METRICS["rerun_total"] = _metric_int("rerun_total") + 1

    _, profile_cfg = _resolve_tenant_policy_profile(tenant_id, replay_request.risk_tier)
    prior_gate = prior.get("gate") if isinstance(prior, dict) else None
    prior_assessment = prior.get("assessment") if isinstance(prior, dict) else None
    current_gate = envelope_payload.get("gate") if isinstance(envelope_payload, dict) else None
    current_assessment = envelope_payload.get("assessment") if isinstance(envelope_payload, dict) else None
    prior_action = prior_gate.get("outcome") if isinstance(prior_gate, dict) else None
    current_action = current_gate.get("outcome") if isinstance(current_gate, dict) else None
    prior_signal_source = None
    if isinstance(prior_assessment, dict):
        prior_eq = prior_assessment.get("evidence_quality")
        if isinstance(prior_eq, dict):
            prior_signal_source = prior_eq.get("signal_source")
    current_signal_source = None
    if isinstance(current_assessment, dict):
        current_eq = current_assessment.get("evidence_quality")
        if isinstance(current_eq, dict):
            current_signal_source = current_eq.get("signal_source")
    hashes = _policy_component_hashes()
    return {
        "status": "recorded",
        "original_request_id": req.request_id,
        "rerun_request_id": rerun_request_id,
        "tenant_id": tenant_id,
        "elapsed_ms": elapsed_ms,
        "policy_decision": pd,
        "state_hash": report.get("state_hash"),
        "replay_mode": replay_mode,
        "evidence_records_used": len(evidence_rows),
        "envelope": envelope_payload,
        "policy_hash": hashes["policy_hash"],
        "determinism_checks": {
            "same_action_as_original": (
                bool(prior_action == current_action)
                if isinstance(prior_action, str) and isinstance(current_action, str)
                else None
            ),
            "same_evidence_signal_source": (
                bool(prior_signal_source == current_signal_source)
                if isinstance(prior_signal_source, str) and isinstance(current_signal_source, str)
                else None
            ),
            "stable_policy_hash": bool(hashes["policy_hash"]),
        },
        "review_requirements": _extract_review_requirements(profile_cfg),
    }
