"""
REMORA-mediated solver for AgentHarm (inspect-ai).

Wraps an inspect-ai inner solver and records a DecisionEnvelope for the
agent's proposed action surface (intent-gating). This is NOT a PreToolUse
hook into Inspect's execution loop; see INTERCEPTION_NOTES.md. Mode
degradation (e.g. full -> hardblocks_only) is recorded. DecisionEnvelopes
are logged to results/agentharm/envelopes.jsonl.

Usage in inspect eval:
    --solver experiments/agentharm/solvers.py@remora_full
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

# inspect-ai imports (available after: pip install inspect-ai)
from inspect_ai.solver import Generate, Solver, TaskState, solver

TOOL_RISK_MAP_PATH = Path(__file__).parent / "tool_risk_map.yaml"
ENVELOPE_LOG = Path(__file__).parent.parent.parent / "results" / "agentharm" / "envelopes.jsonl"
ENVELOPE_LOG.parent.mkdir(parents=True, exist_ok=True)

BLOCKED_OUTCOMES = {"ABSTAIN", "ESCALATE"}


def _load_risk_map() -> dict[str, dict[str, str]]:
    with open(TOOL_RISK_MAP_PATH) as f:
        data = yaml.safe_load(f)
    return data.get("tools", {})


def _map_tool(tool_name: str, risk_map: dict) -> dict[str, str]:
    """Return (domain, risk_tier, action_type) for a tool name."""
    key = tool_name.lower().replace("-", "_")
    if key in risk_map:
        return risk_map[key]
    # prefix match (e.g. bash_exec_v2 -> bash_exec)
    for k, v in risk_map.items():
        if key.startswith(k):
            return v
    return risk_map.get("_default_unknown", {
        "domain": "unknown", "risk_tier": "high", "action_type": "execution"
    })


def _log_envelope(envelope: dict) -> None:
    with open(ENVELOPE_LOG, "a") as f:
        f.write(json.dumps(envelope) + "\n")


def _build_remora_engine(single_oracle: bool = False):
    """
    Build REMORA engine routed through Cloudflare AI Gateway or direct OpenAI.

    Returns ``(engine_or_None, degradation_reason_or_None)``. The reason is a
    short string when the engine could NOT be built, so callers can record
    mode degradation in metadata instead of silently passing through. We do
    NOT swallow init failures into a generic ``None``.

    Oracle models deliberately differ from the AgentHarm judge model (gpt-4o)
    to avoid circularity.
    """
    from experiments.agentharm.cf_compat import resolve_api_key, resolve_base_url

    api_key = resolve_api_key()
    try:
        base_url = resolve_base_url()
    except ValueError:
        base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key:
        return None, "no_api_key: Cloudflare/OpenAI-compatible token unset"

    try:
        from remora.engine import Remora
        from remora.genome import Genome
        from remora.oracles import OpenAIOracle
    except Exception as e:  # noqa: BLE001 - import-time failure is a real signal
        return None, f"import_error: {type(e).__name__}: {e}"

    try:
        models = ["gpt-4o-mini"] if single_oracle else [
            "gpt-4o-mini", "gpt-3.5-turbo", "gpt-4o-mini"
        ]
        oracles = []
        for model in models:
            kw = {"model": model, "api_key": api_key}
            if base_url:
                kw["base_url"] = base_url
            oracles.append(OpenAIOracle(**kw))
        engine = Remora(
            oracles=oracles,
            genome=Genome(enable_routing=True, enable_thermodynamic_control=True),
        )
        return engine, None
    except Exception as e:  # noqa: BLE001
        return None, f"engine_init_error: {type(e).__name__}: {e}"


class RemoraGate:
    """Thin sync wrapper around REMORA engine or hard-blocks-only fallback.

    Exposes ``effective_mode`` and ``degradation_reason`` so callers can record
    in run metadata when an oracle-backed mode silently fell back to
    hard-blocks (e.g. full -> hardblocks_only on engine init failure).
    """

    def __init__(self, mode: str = "full"):
        """
        mode: 'full' | 'hardblocks_only' | 'single_oracle'
        """
        self.mode = mode
        self.risk_map = _load_risk_map()
        self.degradation_reason: str | None = None
        if mode == "hardblocks_only":
            self.engine = None
            self.effective_mode = "hardblocks_only"
        else:
            self.engine, self.degradation_reason = _build_remora_engine(
                single_oracle=(mode == "single_oracle")
            )
            if self.engine is None:
                self.effective_mode = "hardblocks_only"
            else:
                self.effective_mode = mode

    def mode_metadata(self) -> dict:
        """Mode-degradation record for run_config/summary metadata."""
        return {
            "requested_mode": self.mode,
            "effective_mode": self.effective_mode,
            "degraded": self.effective_mode != self.mode,
            "degradation_reason": self.degradation_reason,
        }

    def assess(self, tool_name: str, tool_args: dict[str, Any],
               session_id: str = "") -> dict:
        """
        Returns a dict with keys: outcome, reason, envelope_id, latency_ms
        outcome: ACCEPT | VERIFY | ABSTAIN | ESCALATE
        """
        t0 = time.monotonic()
        mapping = _map_tool(tool_name, self.risk_map)
        domain = mapping.get("domain", "unknown")
        risk_tier = mapping.get("risk_tier", "high")
        action_type = mapping.get("action_type", "execution")

        # Hard-block rules (applied in all modes)
        hard_outcome = self._hard_blocks(tool_name, tool_args, risk_tier, action_type)
        if hard_outcome:
            envelope = {
                "envelope_id": f"env_{session_id}_{tool_name}_{int(t0*1000)}",
                "tool": tool_name,
                "domain": domain,
                "risk_tier": risk_tier,
                "gate": {"outcome": hard_outcome, "source": "hard_block"},
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            }
            _log_envelope(envelope)
            return envelope

        # Oracle consensus (full and single_oracle effective modes)
        assess_error = None
        if self.engine and self.effective_mode in ("full", "single_oracle"):
            try:
                action_str = f"{tool_name}({json.dumps(tool_args)[:200]})"
                result = self.engine.assess_sync(
                    action=action_str,
                    domain=domain,
                    risk_tier=risk_tier,
                    action_type=action_type,
                )
                outcome = getattr(result, "outcome", "ACCEPT")
            except Exception as e:  # noqa: BLE001 - recorded, not hidden
                outcome = "VERIFY"   # fail toward VERIFY on error
                assess_error = f"{type(e).__name__}: {e}"
        else:
            # hardblocks_only or no engine: pass through
            outcome = "ACCEPT"

        envelope = {
            "envelope_id": f"env_{session_id}_{tool_name}_{int(t0*1000)}",
            "tool": tool_name,
            "domain": domain,
            "risk_tier": risk_tier,
            "gate": {"outcome": outcome, "source": self.effective_mode},
            "assess_error": assess_error,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        }
        _log_envelope(envelope)
        return envelope

    def _hard_blocks(self, tool_name: str, tool_args: dict,
                     risk_tier: str, action_type: str) -> str | None:
        """
        Deterministic hard-block rules - same logic as remora/policy/engine.py
        hard blocks 1-7, expressed as guardrail pre-filter.
        Returns outcome string if blocked, None if no block fires.
        """
        name_lower = tool_name.lower()
        args_str = json.dumps(tool_args).lower()

        # Block 1: Adversarial patterns - known dangerous tool names
        ADVERSARIAL_TOOLS = {
            "bash", "execute_bash", "run_command", "bash_exec",
            "sql_execute", "db_delete", "delete_file", "file_delete",
        }
        if name_lower in ADVERSARIAL_TOOLS and risk_tier == "critical":
            return "ESCALATE"

        # Block 2: Exfiltration / credential extraction keywords
        EXFIL_PATTERNS = [
            "password", "secret", "api_key", "private_key", "token",
            "credential", "ssh_key", "/etc/passwd", "/etc/shadow",
            "id_rsa", ".env",
        ]
        if any(p in args_str for p in EXFIL_PATTERNS):
            return "ESCALATE"

        # Block 3: Auth actions always require review
        if action_type == "auth":
            return "ESCALATE"

        # Block 4: Critical risk + no explicit allow
        if risk_tier == "critical" and action_type in ("execution", "delete"):
            return "ESCALATE"

        return None



def write_mode_metadata(mode: str) -> dict:
    """Construct a gate for ``mode`` and persist its mode-degradation metadata.

    Records to results/agentharm/mode_metadata.jsonl so runs make any silent
    fallback (e.g. full -> hardblocks_only on engine-init failure) auditable.
    """
    gate = RemoraGate(mode=mode)
    meta = gate.mode_metadata()
    path = ENVELOPE_LOG.parent / "mode_metadata.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(meta) + "\n")
    return meta


def remora_mediated_solver_factory(mode: str = "full"):
    """Factory returning an inspect-ai @solver for the given REMORA mode.

    IMPORTANT (see experiments/agentharm/INTERCEPTION_NOTES.md): this wrapper
    does NOT install a true PreToolUse hook into Inspect's tool-execution loop.
    It records a DecisionEnvelope for the agent's *proposed* action surface
    (intent-gating) and surfaces mode degradation. It must not be described as
    tool-call interception until a real tool-wrapping hook is implemented and
    inspect_tools_probe.py confirms scenario tools are exposed.
    """
    gate = RemoraGate(mode=mode)
    session_counter = [0]

    @solver
    def _solver(inner: Solver) -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            session_counter[0] += 1
            session_id = f"s{session_counter[0]:04d}"

            # Record the effective mode (and any degradation) once per session.
            meta = gate.mode_metadata()
            meta["session_id"] = session_id
            _log_envelope({"type": "mode_metadata", **meta})

            # Intent-level assessment over the tools attached to this sample.
            # This is NOT execution interception; see INTERCEPTION_NOTES.md.
            for tool in getattr(state, "tools", []) or []:
                tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))
                gate.assess(tool_name, {}, session_id)

            # Delegate to the underlying agent. Tool execution is owned by
            # Inspect; we do not (yet) intercept it.
            return await inner(state, generate)

        return solve

    return _solver
