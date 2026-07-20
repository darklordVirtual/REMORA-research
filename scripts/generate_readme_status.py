# Author: Stian Skogbrott
# License: Apache-2.0
"""Render the README status block from the assurance registers.

The block between the markers

    <!-- BEGIN GENERATED: status ... -->
    <!-- END GENERATED: status -->

in README.md is machine-generated from release_profiles_v1.yaml,
capability_register_v1.yaml, and remediation_register.yaml, so the README's
deployment-profile / open-gate / capability summary can never drift from the
registers by hand-editing prose.

Usage:
    python scripts/generate_readme_status.py           # rewrite the block
    python scripts/generate_readme_status.py --check    # verify it is current
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PROFILES = ROOT / "docs" / "assurance" / "release_profiles_v1.yaml"
CAP_REGISTER = ROOT / "docs" / "assurance" / "capability_register_v1.yaml"
REM_REGISTER = ROOT / "docs" / "assurance" / "remediation_register.yaml"

BEGIN = "<!-- BEGIN GENERATED: status"
END = "<!-- END GENERATED: status -->"
API_PATH_LEVEL = "WIRED_API_PATH"


def _load(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _rem_statuses() -> dict[str, str]:
    out: dict[str, str] = {}
    stack = [_load(REM_REGISTER)]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            rid, status = node.get("id"), node.get("status")
            if isinstance(rid, str) and rid.startswith("REM-") and status is not None:
                out[rid] = str(status).strip()
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out


def build_block() -> str:
    prof = _load(PROFILES)
    caps = {c["id"]: c["status"] for c in _load(CAP_REGISTER)["capabilities"]}
    ladder = prof["capability_ladder"]
    prefixes = prof["rem_satisfied_prefixes"]
    rems = _rem_statuses()

    def rem_ok(rid: str) -> bool:
        return any(rems.get(rid, "").upper().startswith(p) for p in prefixes)

    current = prof["current_profile"]
    dse = prof["deployment_status_equivalent"]
    ordered = sorted(prof["profiles"], key=lambda p: p["order"])
    names = [p["name"] for p in ordered]
    idx = names.index(current)
    nxt = ordered[idx + 1] if idx + 1 < len(ordered) else None

    api_idx = ladder.index(API_PATH_LEVEL)
    wired = sum(1 for lvl in caps.values() if ladder.index(lvl) >= api_idx)
    total = len(caps)

    lines = [
        f"{BEGIN} — source: assurance registers, via "
        f"scripts/generate_readme_status.py --check. DO NOT EDIT. -->",
        f"**Deployment profile:** `{current}` (= `{dse}`) — recomputed from the "
        f"capability and remediation registers by CI; a profile cannot be raised "
        f"by editing prose.",
    ]
    if nxt is not None:
        unmet_rem = [
            rid for rid in (nxt.get("requires", {}).get("rem_done") or [])
            if not rem_ok(rid)
        ]
        unmet_cap = []
        for cid, lvl in (nxt.get("requires", {}).get("capabilities") or {}).items():
            if cid in caps and ladder.index(caps[cid]) < ladder.index(lvl):
                unmet_cap.append(f"{cid}≥{lvl}")
        unmet = unmet_rem + unmet_cap
        blockers = ", ".join(unmet) if unmet else "no register blockers"
        lines.append("")
        lines.append(
            f"**To reach `{nxt['name']}`, still open:** {blockers}."
        )
    lines.append("")
    lines.append(
        f"**Capabilities:** {wired} of {total} wired to the API path or deeper "
        f"([wiring register](docs/assurance/capability_register_v1.yaml)); full "
        f"gate status in [release_gates.md](docs/assurance/release_gates.md), "
        f"maturity ladder in "
        f"[release_profiles_v1.yaml](docs/assurance/release_profiles_v1.yaml)."
    )
    lines.append(END)
    return "\n".join(lines)


def _splice(text: str, block: str) -> str:
    begin = text.index(BEGIN)
    end = text.index(END) + len(END)
    return text[:begin] + block + text[end:]


def main(argv: list[str]) -> int:
    block = build_block()
    text = README.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print(
            "ERROR: README.md has no status markers; add:\n"
            f"    {BEGIN} ... -->\n    {END}",
            file=sys.stderr,
        )
        return 1
    updated = _splice(text, block)
    if "--check" in argv:
        if updated != text:
            print(
                "ERROR: README status block is stale — run: "
                "python scripts/generate_readme_status.py",
                file=sys.stderr,
            )
            return 1
        print("README status block: up to date")
        return 0
    README.write_text(updated, encoding="utf-8", newline="\n")
    print("README status block updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
