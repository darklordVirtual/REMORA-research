// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// REMORA's federation-port/v0 adapter, run inside an unmodified federation-port runtime.
//
//   FEDERATION_PORT_DIR=/path/to/federation-port node --test tests/remora-adapter.test.ts
//
// federation-port is checked out at the revision pinned in fixtures.json; nothing under its src/
// is changed. The fixtures are produced by REMORA (scripts/build_federation_port_v0_fixtures.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { randomBytes } from 'node:crypto'

const FP = process.env.FEDERATION_PORT_DIR
if (!FP) throw new Error('set FEDERATION_PORT_DIR to a federation-port checkout')
const ADAPTER = resolve(import.meta.dirname, '..')
const REPO = resolve(ADAPTER, '../../..')
const FIXTURES = JSON.parse(readFileSync(join(REPO, 'artifacts/interop/federation-port-v0/fixtures.json'), 'utf8'))
const MAP = readFileSync(join(REPO, 'artifacts/interop/federation-port-v0/projection-map.yaml'), 'utf8')

const runtimeMod = await import(pathToFileURL(join(FP, 'src/runtime/index.ts')).href)
const providerMod = await import(pathToFileURL(join(FP, 'sim/provider.ts')).href)
const { Runtime, artifactDigest, digestJson } = runtimeMod

const REMORA = 'remora-research/authorization-evidence'
const EXEC = 'example.sim/refund-executor'
const CLAIMS = ['remora.authorization_integrity', 'remora.port_v0.bound_action', 'remora.authorization_unexpired']

test('the pinned federation-port revision is the one checked out, and its src/ is unmodified', () => {
  const head = execFileSync('git', ['-C', FP, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  assert.equal(`aeoess/federation-port@${head}`, FIXTURES.transport_revision)
  const changed = execFileSync('git', ['-C', FP, 'status', '--porcelain', '--', 'src'], { encoding: 'utf8' })
  assert.equal(changed, '')
})

function pin(path: string, config: Record<string, unknown>) {
  const m = JSON.parse(readFileSync(join(path, 'manifest.json'), 'utf8'))
  return { path, version: m.artifact.version, manifest_digest: digestJson(m),
    artifact_digest: artifactDigest(path, m.artifact.files), privileges_granted: [...m.privileges_requested],
    destinations_allowed: [...m.data_destinations], config }
}

async function env(now: string, trusted = [FIXTURES.test_keys.public_key_hex]) {
  const apiKey = randomBytes(24).toString('hex')
  const provider = await providerMod.startProvider({ apiKey })
  const policy = {
    policy_id: 'remora-adapter-test',
    components: {
      [REMORA]: pin(ADAPTER, { trusted_keys: trusted }),
      [EXEC]: pin(join(FP, 'sim/executor'), { base_url: provider.url }),
    },
    workflows: { refund: { executor: EXEC, tool: 'refund', approval: 'required',
      required_claims: CLAIMS.map(claim => ({ component: REMORA, claim })), optional_claims: [],
      check_timeout_ms: 500, execute_timeout_ms: 1000 } },
  }
  let rt
  try {
    rt = await Runtime.create({ policy, dbPath: join(mkdtempSync(join(tmpdir(), 'remora-fp-')), 'port.db'),
      secrets: { provider_api_key: apiKey }, clock: () => new Date(now) })
  } catch (err) {
    await provider.close()
    throw err
  }
  return { rt, provider, async close() { rt.close(); await provider.close() } }
}

const fixture = (name: string) => FIXTURES.cases.find((c: any) => c.name === name)
function submission(c: any, change: (r: any) => void = () => {}) {
  const req = structuredClone(c.request)
  req.evidence = { [REMORA]: new Uint8Array(Buffer.from(c.evidence_b64, 'base64')) }
  change(req)
  return req
}
const claimsOf = (rt: any, op: string) => Object.fromEntries((rt.provenance(op) as any).admissions.at(-1).claims
  .filter((c: any) => c.component === REMORA).map((c: any) => [c.claim, c.status]))

for (const c of FIXTURES.cases) {
  test(`fixture ${c.name}: claims as REMORA expects (${c.note})`, async () => {
    const e = await env(c.now)
    try {
      const r = await e.rt.submit(submission(c))
      assert.deepEqual(claimsOf(e.rt, c.request.operation_id), c.expected_claims)
      const admitted = Object.values(c.expected_claims).every(s => s === 'established')
      assert.equal(r.status, admitted ? 'provider_confirmed' : 'refused', JSON.stringify(r))
      assert.equal(e.provider.requests, admitted ? 1 : 0)
    } finally { await e.close() }
  })
}

const MUTATIONS: [string, (r: any) => void, string][] = [
  ['argument value', r => { r.action.args.amount_minor = 4100 }, 'action_differs'],
  ['payment target inside the arguments', r => { r.action.args.payment_id = 'pay_B' }, 'action_differs'],
  ['tenant label', r => { r.tenant = 'tenant-b' }, 'tenant_differs'],
  ['tenant removed', r => { delete r.tenant }, 'tenant_differs'],
  ['approval id', r => { r.approval_id = 'apr-other' }, 'approval_id_differs'],
  ['operation id (evidence replayed for another operation)', r => { r.operation_id = 'op-other' }, 'operation_id_differs'],
  ['evidence byte', r => { const b = r.evidence[REMORA]; b[b.length - 10] ^= 1 }, ''],
]
for (const [what, change, reason] of MUTATIONS) {
  test(`AC-03 mutated ${what}: refused before dispatch`, async () => {
    const c = fixture('valid')
    const e = await env(c.now)
    try {
      const req = submission(c, change)
      const r = await e.rt.submit(req)
      assert.equal(r.status, 'refused', JSON.stringify(r))
      assert.equal(e.provider.requests, 0)
      if (reason) assert.ok(r.reasons.some((x: string) => x.endsWith(`#remora.port_v0.bound_action:${reason}`)), JSON.stringify(r.reasons))
    } finally { await e.close() }
  })
}

test('AC-03 a different tool is refused by the runtime before any claim', async () => {
  const c = fixture('valid')
  const e = await env(c.now)
  try {
    const r = await e.rt.submit(submission(c, r => { r.action.tool = 'transfer' }))
    assert.equal(r.status, 'refused')
    assert.equal(e.provider.requests, 0)
  } finally { await e.close() }
})

test('AC-04/AC-06/AC-08 the adapter exports only the narrowed claims REMORA\'s map permits', () => {
  const manifest = JSON.parse(readFileSync(join(ADAPTER, 'manifest.json'), 'utf8'))
  assert.deepEqual(manifest.claims.map((c: any) => c.id).sort(), [...CLAIMS].sort())
  for (const forbidden of ['exact_call_binding', 'principal_binding', 'custody_isolation', 'effect_verified', 'fresh_authority_at_dispatch']) {
    assert.ok(!manifest.claims.some((c: any) => c.id.includes(forbidden)), forbidden)
  }
  for (const claim of CLAIMS) assert.ok(MAP.includes(claim), `${claim} is exported in the projection map`)
})

test('AC-05 1 and 1.0: V0 admits both, the native digests differ and the projection says what was lost', () => {
  const valid = fixture('valid'), lossy = fixture('lossy_float')
  assert.deepEqual(valid.request.action, lossy.request.action)
  assert.notEqual(valid.native_arguments_digest, lossy.native_arguments_digest)
  const exact = lossy.projection_records.find((p: any) => p.native_claim.startsWith('exact_call_binding'))
  assert.equal(exact.projection, 'NARROWED')
  assert.deepEqual(exact.action_losses, { lexical_numeric_type: ['/amount_minor'] })
})

test('AC-09 every case carries projection records with artifact and revision digests', () => {
  const manifest = JSON.parse(readFileSync(join(ADAPTER, 'manifest.json'), 'utf8'))
  for (const c of FIXTURES.cases) {
    for (const p of c.projection_records) {
      assert.equal(p.schema_version, 'remora-federation-projection-v2')
      // At issuance the record is about the operation itself, selected as the single one.
      assert.deepEqual(p.subject, { kind: 'operation', operation_id: c.request.operation_id })
      assert.equal(p.evidence_selection.selection_rule, 'single_available')
      assert.equal(p.native_result, null)
      assert.equal(p.adapter_digest, manifest.artifact.digest)
      assert.equal(p.transport_revision, FIXTURES.transport_revision)
      for (const k of ['native_evidence_digest', 'transport_evidence_digest', 'projection_map_digest', 'capabilities_digest']) {
        assert.match(p[k], /^sha256:[0-9a-f]{64}$/)
      }
    }
    const effect = c.projection_records.find((p: any) => p.native_claim.startsWith('effect_verification'))
    assert.equal(effect.projection, 'UNSUPPORTED')
  }
})
