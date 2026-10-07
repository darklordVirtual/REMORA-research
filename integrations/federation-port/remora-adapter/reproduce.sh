#!/usr/bin/env bash
# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
#
# Reproduce REMORA's federation-port/v0 adapter against the UNMODIFIED federation-port core, the
# way the other outside adapters on aeoess/agent-governance-vocabulary#177 report it: the component
# is installed into federation-port's own tree and sealed with its scripts/seal.ts, and the
# upstream suite and this adapter's tests run together. REMORA's own acceptance suites (fixtures,
# Federation Bridge, report-specific selection) run separately and are reported separately.
#
#   integrations/federation-port/remora-adapter/reproduce.sh [--skip-python]
#
# Needs git, Node >= 24 and, unless --skip-python, a Python with REMORA's dev dependencies
# (pytest, cryptography, pyyaml, jsonschema); PYTHON selects it (default python3).
# Writes a machine-readable result to $REMORA_REPRODUCE_OUT (default
# ./remora-federation-port-reproduction.json) and exits non-zero on any failure.
set -euo pipefail

PIN=92d5078af3bbd3610ce4901378e913d5f370a68b
COMPONENT=remora-research-authorization
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
OUT="${REMORA_REPRODUCE_OUT:-$PWD/remora-federation-port-reproduction.json}"
PYTHON="${PYTHON:-python3}"
SKIP_PYTHON=0
[ "${1:-}" = "--skip-python" ] && SKIP_PYTHON=1

node -e 'process.exit(+process.versions.node.split(".")[0] >= 24 ? 0 : 1)' \
  || { echo "federation-port needs Node >= 24 (node:sqlite)" >&2; exit 2; }

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT        # leave nothing behind
mkdir -p "$W/tmp" && export TMPDIR="$W/tmp"
FP="$W/federation-port"

step() { echo "== $*"; }

step "federation-port at $PIN"
git -c core.autocrlf=false clone -q https://github.com/aeoess/federation-port "$FP"
git -C "$FP" -c core.autocrlf=false checkout -q "$PIN"

step "install the REMORA component (no change under src/)"
DEST="$FP/adapters/$COMPONENT"
INTEROP="$FP/test/fixtures/remora"
mkdir -p "$DEST" "$INTEROP"
cp "$HERE/adapter.ts" "$HERE/manifest.json" "$DEST/"
cp "$HERE/tests/remora-adapter.test.ts" "$FP/test/"
cp "$REPO/artifacts/interop/federation-port-v0/fixtures.json" \
   "$REPO/artifacts/interop/federation-port-v0/projection-map.yaml" "$INTEROP/"
(cd "$FP" && npm ci --silent)

step "seal with federation-port's scripts/seal.ts; the pinned digest must not move"
PINNED_DIGEST="$(node -e 'console.log(JSON.parse(require("fs").readFileSync(process.argv[1],"utf8")).artifact.digest)' "$HERE/manifest.json")"
SEALED_DIGEST="$(cd "$FP" && node --disable-warning=ExperimentalWarning scripts/seal.ts "adapters/$COMPONENT" \
  | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>console.log(JSON.parse(s).artifact_digest))')"
SEAL_OK=false
[ "$PINNED_DIGEST" = "$SEALED_DIGEST" ] && SEAL_OK=true

step "core unmodified"
CORE_CLEAN=false
if git -C "$FP" diff --quiet -- src && [ -z "$(git -C "$FP" status --porcelain -- src)" ]; then
  CORE_CLEAN=true
  echo "core unmodified (src/ clean)"
fi

export FEDERATION_PORT_DIR="$FP" REMORA_ADAPTER_DIR="$DEST" REMORA_INTEROP_DIR="$INTEROP"
tap() {  # run node:test with TAP output into $1, the remaining args are test files
  local out="$1"; shift
  (cd "$FP" && node --disable-warning=ExperimentalWarning --test --test-concurrency=1 \
     --test-reporter=tap "$@") > "$out" 2>&1 && return 0 || return 1
}
count() { sed -n "s/^# $2 \([0-9]*\)$/\1/p" "$1" | tail -1; }

STATUS=0
step "federation-port suite with the REMORA component: test/*.test.ts"
ALL_OK=true; tap "$W/all.tap" 'test/*.test.ts' || { ALL_OK=false; STATUS=1; }
tail -9 "$W/all.tap"
UPSTREAM_FILES="$(cd "$FP" && ls test/*.test.ts | grep -v '^test/remora-adapter.test.ts$')"
step "upstream tests alone"
UP_OK=true; tap "$W/upstream.tap" $UPSTREAM_FILES || { UP_OK=false; STATUS=1; }
step "REMORA adapter tests alone"
RA_OK=true; tap "$W/remora.tap" test/remora-adapter.test.ts || { RA_OK=false; STATUS=1; }

step "tsc against the published contract types (adapter and its tests included)"
TSC_OK=true; (cd "$FP" && npx tsc -p tsconfig.json) || { TSC_OK=false; STATUS=1; }

PY_STATE=not_evaluated; FIXTURES_STATE=not_evaluated; PY_TESTS=0; PY_FAIL=0; PY_SKIP=0
if [ "$SKIP_PYTHON" = 0 ]; then
  step "REMORA fixtures match the code"
  if (cd "$REPO" && "$PYTHON" scripts/build_federation_port_v0_fixtures.py --check); then
    FIXTURES_STATE=pass; else FIXTURES_STATE=fail; STATUS=1; fi
  step "REMORA acceptance: Federation Bridge and report-specific selection (separate suite)"
  if (cd "$REPO" && "$PYTHON" -m pytest -q -p no:cacheprovider \
        tests/test_federation_report_selection.py tests/test_federation_bridge.py \
        --junitxml "$W/py.xml"); then PY_STATE=pass; else PY_STATE=fail; STATUS=1; fi
  if [ -f "$W/py.xml" ]; then
    read -r PY_TESTS PY_FAIL PY_SKIP < <(node -e '
      const x=require("fs").readFileSync(process.argv[1],"utf8");
      const a=n=>[...x.matchAll(new RegExp(`<testsuite[^>]* ${n}="(\\d+)"`,"g"))].reduce((s,m)=>s+ +m[1],0);
      console.log(a("tests"), a("failures")+a("errors"), a("skipped"))' "$W/py.xml")
  fi
fi
[ "$SEAL_OK" = true ] && [ "$CORE_CLEAN" = true ] || STATUS=1

node -e '
  const [out, ...v] = process.argv.slice(1)
  const f = require("fs"), n = x => Number(x || 0)
  const tapCounts = p => { const t = f.readFileSync(p, "utf8"), g = k => n((t.match(new RegExp(`^# ${k} (\\d+)$`, "m")) || [])[1])
    return { tests: g("tests"), pass: g("pass"), fail: g("fail"), skipped: g("skipped"), todo: g("todo"), cancelled: g("cancelled") } }
  const [w, pin, remora, dirty, seal, sealed, pinned, core, allOk, upOk, raOk, tsc, fx, py, pyT, pyF, pyS, status] = v
  const all = tapCounts(w + "/all.tap"), up = tapCounts(w + "/upstream.tap"), ra = tapCounts(w + "/remora.tap")
  const result = {
    schema_version: "remora-federation-port-reproduction-v1",
    federation_port: { repository: "aeoess/federation-port", revision: pin, src_unmodified: core === "true" },
    remora: { revision: remora, working_tree_clean: dirty === "clean", component: "remora-research/authorization-evidence",
              artifact_digest_pinned: pinned, artifact_digest_sealed_by_federation_port: sealed, seal_matches: seal === "true" },
    node: process.version,
    federation_port_suite: { command: "node --test --test-concurrency=1 test/*.test.ts", ...all, passed: allOk === "true",
                             upstream: up, remora_adapter: ra },
    typecheck: { command: "npx tsc -p tsconfig.json", passed: tsc === "true" },
    remora_acceptance: { fixtures_check: fx,
      suites: ["tests/test_federation_report_selection.py", "tests/test_federation_bridge.py"],
      state: py, tests: n(pyT), failed: n(pyF), skipped: n(pyS),
      note: "REMORA-side suites; not part of the federation-port count" },
    passed: status === "0",
  }
  f.writeFileSync(out, JSON.stringify(result, null, 2) + "\n")
  console.log(`federation-port suite: ${all.pass}/${all.tests} (${up.pass}/${up.tests} upstream + ${ra.pass}/${ra.tests} REMORA adapter), src unmodified: ${core}, seal matches: ${seal}, tsc: ${tsc}`)
  console.log(`REMORA acceptance (separate): ${py}, ${n(pyT) - n(pyF) - n(pyS)}/${n(pyT)} passed, fixtures: ${fx}`)
' "$OUT" "$W" "$PIN" "$(git -C "$REPO" rev-parse HEAD)" \
  "$([ -z "$(git -C "$REPO" status --porcelain -- integrations artifacts remora tests scripts)" ] && echo clean || echo dirty)" \
  "$SEAL_OK" "$SEALED_DIGEST" "$PINNED_DIGEST" "$CORE_CLEAN" "$ALL_OK" "$UP_OK" "$RA_OK" "$TSC_OK" \
  "$FIXTURES_STATE" "$PY_STATE" "$PY_TESTS" "$PY_FAIL" "$PY_SKIP" "$STATUS"
echo "result: $OUT"
exit "$STATUS"
