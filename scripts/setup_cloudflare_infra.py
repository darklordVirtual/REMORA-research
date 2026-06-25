#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Provision REMORA Cloudflare infrastructure for a new environment.

Creates:
  - D1 database      remora-audit       (audit ledger)
  - KV namespace     remora-sessions    (agent sessions)
  - R2 bucket        remora-artifacts   (stored artifacts)

Then patches workers/agent-control/wrangler.toml with the new resource IDs.

Requirements:
  - Node.js + wrangler installed  (npm i -g wrangler)
  - Logged in to Cloudflare       (npx wrangler login)

Usage:
  python scripts/setup_cloudflare_infra.py [--dry-run]
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRANGLER_TOML = ROOT / "workers" / "agent-control" / "wrangler.toml"

DRY_RUN = "--dry-run" in sys.argv


def run(cmd: list[str], capture: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    if DRY_RUN:
        print("  [dry-run - skipped]")
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result


def wrangler(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    return run(["npx", "--yes", "wrangler", *args], capture=capture)


def extract_id(output: str, pattern: str) -> str | None:
    m = re.search(pattern, output)
    return m.group(1) if m else None


def patch_toml(path: Path, replacements: dict[str, str]) -> None:
    if not path.exists():
        print(f"  WARNING: {path} not found - skipping wrangler.toml patch")
        return
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old in text:
            text = text.replace(old, new)
            print(f"  Patched wrangler.toml: {old!r} → {new!r}")
        else:
            print(f"  WARNING: pattern {old!r} not found in wrangler.toml")
    if not DRY_RUN:
        path.write_text(text, encoding="utf-8")


def check_wrangler() -> None:
    result = subprocess.run(
        ["npx", "wrangler", "--version"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("ERROR: wrangler not found. Run: npm install -g wrangler", file=sys.stderr)
        sys.exit(1)
    print(f"  wrangler {result.stdout.strip()}")


def create_d1(name: str) -> str:
    print(f"\n[1/3] Creating D1 database '{name}' ...")
    result = wrangler("d1", "create", name, "--json")
    if DRY_RUN:
        return "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    data = json.loads(result.stdout)
    db_id: str = data.get("uuid") or data.get("id") or ""
    if not db_id:
        db_id = extract_id(result.stdout, r'"uuid"\s*:\s*"([^"]+)"') or ""
    if not db_id:
        print(f"  Could not parse D1 ID from output:\n{result.stdout}", file=sys.stderr)
        sys.exit(1)
    print(f"  D1 database ID: {db_id}")
    return db_id


def create_kv(name: str) -> str:
    print(f"\n[2/3] Creating KV namespace '{name}' ...")
    result = wrangler("kv", "namespace", "create", name, "--json")
    if DRY_RUN:
        return "yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
    data = json.loads(result.stdout)
    kv_id: str = data.get("id") or ""
    if not kv_id:
        kv_id = extract_id(result.stdout, r'"id"\s*:\s*"([^"]+)"') or ""
    if not kv_id:
        print(f"  Could not parse KV ID from output:\n{result.stdout}", file=sys.stderr)
        sys.exit(1)
    print(f"  KV namespace ID: {kv_id}")
    return kv_id


def create_r2(name: str) -> None:
    print(f"\n[3/3] Creating R2 bucket '{name}' ...")
    wrangler("r2", "bucket", "create", name)
    print(f"  R2 bucket '{name}' created.")


def prompt_secret(label: str, worker: str) -> None:
    print(f"\n  Set {label} on worker '{worker}'?")
    value = input("  Enter value (leave blank to skip): ").strip()
    if value:
        if DRY_RUN:
            print(f"  [dry-run] would set {label} on {worker}")
            return
        proc = subprocess.run(
            ["npx", "wrangler", "secret", "put", label, "--name", worker],
            input=value,
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            print(f"  {label} set on {worker}.")
        else:
            print(f"  WARNING: failed to set {label}: {proc.stderr.strip()}")
    else:
        print("  Skipped - set manually with:")
        print(f"  printf '%s' '<value>' | npx wrangler secret put {label} --name {worker}")


def main() -> None:
    print("=" * 60)
    print("REMORA - Cloudflare Infrastructure Setup")
    if DRY_RUN:
        print("(DRY RUN - no changes will be made)")
    print("=" * 60)

    print("\nChecking wrangler ...")
    check_wrangler()

    print("\nThis script will create:")
    print("  - D1 database:    remora-audit")
    print("  - KV namespace:   remora-sessions")
    print("  - R2 bucket:      remora-artifacts")
    print(f"\nwrangler.toml to patch: {WRANGLER_TOML}")
    print()

    if not DRY_RUN:
        confirm = input("Continue? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            sys.exit(0)

    d1_id = create_d1("remora-audit")
    kv_id = create_kv("remora-sessions")
    create_r2("remora-artifacts")

    print("\n[Patching wrangler.toml] ...")
    patch_toml(
        WRANGLER_TOML,
        {
            "642489ab-6c3d-4709-9ad0-d58896e1ce5f": d1_id,
            "c085347bc8be49f3afc38a0e263e5d87": kv_id,
        },
    )

    print("\n[Secrets] - set CONTROL_SECRET on agent-control worker")
    prompt_secret("CONTROL_SECRET", "remora-agent-control")

    print("\n" + "=" * 60)
    print("Infrastructure provisioned.")
    print()
    print("Next steps:")
    print("  1. Deploy the worker:")
    print("     cd workers/agent-control && npx wrangler deploy")
    print()
    print("  2. Note your worker URL (shown after deploy), then update")
    print("     AGENT_CONTROL_URL in claude_desktop_config.json:")
    print("     https://remora-agent-control.<your-subdomain>.workers.dev")
    print()
    print("  3. Add AGENT_CONTROL_SECRET to claude_desktop_config.json")
    print("     under mcpServers.remora.env - must match CONTROL_SECRET above.")
    print()
    print("  4. Run schema migration for D1:")
    print("     npx wrangler d1 execute remora-audit \\")
    print("       --file workers/agent-control/schema.sql")
    print()
    print("  5. Update .claude/settings.json hook path to your local clone:")
    print("     python /absolute/path/to/REMORA/scripts/remora_hook.py")
    print()
    print("See .claude/skills/remora/skill.md - Configuration Checklist for")
    print("all remaining author-specific values to replace.")
    print("=" * 60)


if __name__ == "__main__":
    main()
