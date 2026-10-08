// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// REMORA's federation-port/v0 adapter, run inside an unmodified federation-port runtime.
//
//   FEDERATION_PORT_DIR=/path/to/federation-port node --test tests/remora-adapter.test.ts
//
// or, as reproduce.sh does, copied into federation-port's own test/ and run with its suite, with
// REMORA_ADAPTER_DIR (the installed component) and REMORA_INTEROP_DIR (fixtures and map) set.
// federation-port is checked out at the revision pinned in fixtures.json; nothing under its src/
// is changed. The fixtures are produced by REMORA (scripts/build_federation_port_v0_fixtures.py).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash, createPrivateKey, generateKeyPairSync, randomBytes, sign as signBytes } from 'node:crypto'

const FP: string = process.env.FEDERATION_PORT_DIR ?? ''
if (!FP) throw new Error('set FEDERATION_PORT_DIR to a federation-port checkout')
const ADAPTER = resolve(process.env.REMORA_ADAPTER_DIR ?? resolve(import.meta.dirname, '..'))
const INTEROP = resolve(process.env.REMORA_INTEROP_DIR
  ?? resolve(import.meta.dirname, '../../../../artifacts/interop/federation-port-v0'))
const FIXTURES = JSON.parse(readFileSync(join(INTEROP, 'fixtures.json'), 'utf8'))
const MAP = readFileSync(join(INTEROP, 'projection-map.yaml'), 'utf8')

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

// ---------------------------------------------------------------------------------------------
// Held-out cases, written after the component shipped. The mutation check
// (integrations/federation-port/mutation_check.py) found 34 of 107 single-edit faults surviving
// the tests above; these cases sign their own envelopes with the published test seed and reach
// the paths the fixtures do not: every refusal before the signature, a correctly sized wrong
// signature, every envelope-level refusal, evidence addressed elsewhere, the empty tenant,
// malformed instants on both sides, the inclusive deadline, null and nested arguments. Most run
// the component alone, so they discriminate on behaviour and not on the fixture digests.
// ---------------------------------------------------------------------------------------------
const adapterMod = await import(pathToFileURL(join(ADAPTER, 'adapter.ts')).href)
const SEED = Buffer.from(FIXTURES.test_keys.signing_seed_hex, 'hex')
const PUB = Buffer.from(FIXTURES.test_keys.public_key_hex, 'hex')
const KID = 'ed25519-' + createHash('sha256').update(PUB).digest('hex')
const DOMAIN = 'REMORA/FEDERATION-ACTION/v1'
const signingKey = createPrivateKey({ format: 'jwk',
  key: { kty: 'OKP', crv: 'Ed25519', d: SEED.toString('base64url'), x: PUB.toString('base64url') } })
const validCase = fixture('valid')
const validOuter = JSON.parse(Buffer.from(validCase.evidence_b64, 'base64').toString('utf8'))
const validEnvelope = JSON.parse(Buffer.from(validOuter.envelope_b64, 'base64').toString('utf8'))

/** Sign an envelope the way REMORA does, with optional edits to the outer document and signature. */
function sealEnvelope(envelope: unknown, outer: Record<string, unknown> = {}, sig: Record<string, unknown> = {},
                      key = signingKey): Uint8Array {
  const payload = Buffer.from(JSON.stringify(envelope))
  const preimage = Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload])
  const signature = signBytes(null, preimage, key).toString('base64')
  const doc = { format: 'remora-federation-evidence-v1', envelope_b64: payload.toString('base64'),
    signature: { algorithm: 'Ed25519', domain: DOMAIN, kid: KID, signature, ...sig }, ...outer }
  return new Uint8Array(Buffer.from(JSON.stringify(doc)))
}
function envelopeWith(edit: (e: any) => void = () => {}) {
  const e = structuredClone(validEnvelope); edit(e); return e
}
const bytes = (s: string) => new Uint8Array(Buffer.from(s))

function direct(trusted: string[] = [PUB.toString('hex')]) {
  return adapterMod.createAdapter({ config: { trusted_keys: trusted }, secrets: {}, fetch: globalThis.fetch })
}
async function checkDirect(a: any, evidence: Uint8Array | undefined, o: Record<string, unknown> = {}) {
  const req = validCase.request
  const out = await a.check({ operation_id: req.operation_id, workflow: req.workflow, tenant: req.tenant,
    approval_id: req.approval_id, action: structuredClone(req.action), now: validCase.now, evidence, ...o })
  const claims = Object.fromEntries(out.claims.map((c: any) => [c.claim, c.reason ? `${c.status}:${c.reason}` : c.status]))
  return { out, claims }
}
const [INTEGRITY, BOUND, UNEXPIRED] = CLAIMS
const allThree = (s: string) => ({ [INTEGRITY]: s, [BOUND]: s, [UNEXPIRED]: s })
const integrityFailed = (reason: string) => ({ [INTEGRITY]: `not_established:${reason}`,
  [BOUND]: 'not_established:integrity_not_established', [UNEXPIRED]: 'not_established:integrity_not_established' })
const notAddressed = { [INTEGRITY]: 'established', [BOUND]: 'not_established:evidence_not_addressed_to_this_component',
  [UNEXPIRED]: 'not_established:evidence_not_addressed_to_this_component' }

test('held-out: the fixtures are signed with the published test seed, and Ed25519 reproduces them exactly', () => {
  assert.equal(validOuter.signature.kid, KID)
  const resigned = JSON.parse(Buffer.from(sealEnvelope(validEnvelope)).toString('utf8'))
  assert.equal(resigned.envelope_b64, validOuter.envelope_b64)
  assert.equal(resigned.signature.signature, validOuter.signature.signature)
})

test('held-out: the unmutated evidence establishes all three claims on the component alone', async () => {
  const { out, claims } = await checkDirect(direct(), sealEnvelope(validEnvelope))
  assert.deepEqual(claims, allThree('established'))
  assert.equal(out.valid_until, validEnvelope.transport_projection.valid_until)
})

const BEFORE_SIGNATURE: [string, () => Uint8Array | undefined, Record<string, string>][] = [
  ['no evidence at all', () => undefined, allThree('not_established:evidence_missing')],
  ['an empty evidence buffer', () => new Uint8Array(), allThree('not_established:evidence_missing')],
  ['one byte of evidence', () => new Uint8Array([0x7b]), allThree('failed:evidence_malformed')],
  ['evidence that is not JSON', () => bytes('{"format":'), allThree('failed:evidence_malformed')],
  ['another evidence format', () => sealEnvelope(validEnvelope, { format: 'remora-federation-evidence-v2' }), allThree('unsupported:evidence_format_unknown')],
  ['another signature algorithm', () => sealEnvelope(validEnvelope, {}, { algorithm: 'RSA-PSS' }), integrityFailed('algorithm_unsupported')],
  ['another signing domain', () => sealEnvelope(validEnvelope, {}, { domain: 'REMORA/FEDERATION-ACTION/v2' }), integrityFailed('domain_mismatch')],
  ['a kid the customer did not pin', () => sealEnvelope(validEnvelope, {}, { kid: 'ed25519-' + 'f'.repeat(64) }), integrityFailed('unknown_kid')],
  ['no signature object', () => sealEnvelope(validEnvelope, { signature: undefined }), integrityFailed('algorithm_unsupported')],
  ['a 63-byte signature', () => sealEnvelope(validEnvelope, {}, { signature: Buffer.alloc(63).toString('base64') }), integrityFailed('signature_invalid')],
  ['a 65-byte signature', () => sealEnvelope(validEnvelope, {}, { signature: Buffer.alloc(65).toString('base64') }), integrityFailed('signature_invalid')],
  ['a correctly sized signature by another key under the pinned kid', () => {
    const other = generateKeyPairSync('ed25519').privateKey
    return sealEnvelope(validEnvelope, {}, {}, other)  // kid stays KID, signature is by `other`
  }, integrityFailed('signature_invalid')],
  ['a correctly sized signature over another domain', () => {
    const payload = Buffer.from(JSON.stringify(validEnvelope))
    const bad = signBytes(null, Buffer.concat([Buffer.from('OTHER/v1', 'ascii'), Buffer.from([0]), payload]), signingKey)
    return sealEnvelope(validEnvelope, {}, { signature: bad.toString('base64') })
  }, integrityFailed('signature_invalid')],
]
for (const [what, evidence, expected] of BEFORE_SIGNATURE) {
  test(`held-out before the envelope: ${what}`, async () => {
    const { out, claims } = await checkDirect(direct(), evidence())
    assert.deepEqual(claims, expected)
    assert.equal(out.valid_until, undefined)
  })
}

test('held-out sweep: flipping any bit of the signed envelope or any byte of the signature invalidates it', async () => {
  const a = direct()
  const good = JSON.parse(Buffer.from(sealEnvelope(validEnvelope)).toString('utf8'))
  const payload = Buffer.from(good.envelope_b64, 'base64')
  const signature = Buffer.from(good.signature.signature, 'base64')
  const mutants: [string, Uint8Array][] = []
  for (let i = 0; i < payload.length; i++) {
    for (const bit of [1, 128]) {
      const p = Buffer.from(payload); p[i] ^= bit
      mutants.push([`envelope[${i}]^${bit}`, bytes(JSON.stringify({ ...good, envelope_b64: p.toString('base64') }))])
    }
  }
  for (let i = 0; i < 64; i++) {
    const s = Buffer.from(signature); s[i] ^= 1
    mutants.push([`signature[${i}]^1`, bytes(JSON.stringify({ ...good, signature: { ...good.signature, signature: s.toString('base64') } }))])
  }
  assert.ok(mutants.length > 1000, `${mutants.length} mutants`)
  const survivors: string[] = []
  for (const [name, evidence] of mutants) {
    const { claims } = await checkDirect(a, evidence)
    if (claims[INTEGRITY] !== 'not_established:signature_invalid' || claims[BOUND] === 'established') survivors.push(`${name}:${claims[INTEGRITY]}`)
  }
  assert.deepEqual(survivors, [])
})

const ENVELOPE_LEVEL: [string, () => Uint8Array, Record<string, string>][] = [
  ['a signed payload that is not JSON', () => {
    const payload = Buffer.from('{"schema_version":')
    const sig = signBytes(null, Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload]), signingKey)
    return bytes(JSON.stringify({ format: 'remora-federation-evidence-v1', envelope_b64: payload.toString('base64'),
      signature: { algorithm: 'Ed25519', domain: DOMAIN, kid: KID, signature: sig.toString('base64') } }))
  }, allThree('failed:envelope_malformed')],
  ['another envelope schema', () => sealEnvelope(envelopeWith(e => { e.schema_version = 'remora-federation-action-v2' })), allThree('unsupported:envelope_version_unknown')],
  ['another canonicalization', () => sealEnvelope(envelopeWith(e => { e.action.canonicalization = 'json-v0' })), allThree('failed:canonicalization_mismatch')],
  ['no action section at all', () => sealEnvelope(envelopeWith(e => { delete e.action })), allThree('failed:canonicalization_mismatch')],
  ['no transport projection', () => sealEnvelope(envelopeWith(e => { delete e.transport_projection })), notAddressed],
  ['a projection for another transport', () => sealEnvelope(envelopeWith(e => { e.transport_projection.transport = 'federation-port/v1' })), notAddressed],
  ['a projection for another component', () => sealEnvelope(envelopeWith(e => { e.transport_projection.component = 'remora-research/report-result' })), notAddressed],
]
for (const [what, evidence, expected] of ENVELOPE_LEVEL) {
  test(`held-out envelope: ${what}`, async () => {
    const { out, claims } = await checkDirect(direct(), evidence())
    assert.deepEqual(claims, expected)
    assert.equal(out.valid_until, undefined)
  })
}

test('held-out: an empty tenant label is a label, not an absent tenant, on either side', async () => {
  const a = direct()
  const ev = sealEnvelope(envelopeWith(e => { e.transport_projection.tenant = '' }))
  assert.equal((await checkDirect(a, ev, { tenant: undefined })).claims[BOUND], 'not_established:tenant_differs')
  assert.equal((await checkDirect(a, ev, { tenant: '' })).claims[BOUND], 'established')
  const absent = sealEnvelope(envelopeWith(e => { e.transport_projection.tenant = null }))
  assert.equal((await checkDirect(a, absent, { tenant: '' })).claims[BOUND], 'not_established:tenant_differs')
  assert.equal((await checkDirect(a, absent, { tenant: undefined })).claims[BOUND], 'established')
})

const BAD_INSTANTS = ['2026-10-07T12:05:00Z', '2026-10-07T12:05:00.000+00:00', '2026-10-07 12:05:00.000Z',
  '2026-13-45T00:00:00.000Z', '2026-02-30T00:00:00.000Z', 1760000000000, null, '']
test('held-out: a malformed valid_until fails the unexpired claim only, and carries no valid_until', async () => {
  const a = direct()
  for (const bad of BAD_INSTANTS) {
    const { out, claims } = await checkDirect(a, sealEnvelope(envelopeWith(e => { e.transport_projection.valid_until = bad })))
    assert.deepEqual(claims, { [INTEGRITY]: 'established', [BOUND]: 'established', [UNEXPIRED]: 'failed:instant_malformed' }, String(bad))
    assert.equal(out.valid_until, undefined, String(bad))
  }
})
test('held-out: a malformed now fails the unexpired claim only, and the valid_until is still carried', async () => {
  const a = direct()
  for (const bad of BAD_INSTANTS) {
    const { out, claims } = await checkDirect(a, sealEnvelope(validEnvelope), { now: bad })
    assert.deepEqual(claims, { [INTEGRITY]: 'established', [BOUND]: 'established', [UNEXPIRED]: 'failed:instant_malformed' }, String(bad))
    assert.equal(out.valid_until, validEnvelope.transport_projection.valid_until)
  }
})
test('held-out: the deadline is inclusive to the millisecond', async () => {
  const a = direct()
  const until = validEnvelope.transport_projection.valid_until
  const at = (ms: number) => new Date(Date.parse(until) + ms).toISOString()
  assert.equal((await checkDirect(a, sealEnvelope(validEnvelope), { now: at(0) })).claims[UNEXPIRED], 'established')
  assert.equal((await checkDirect(a, sealEnvelope(validEnvelope), { now: at(-1) })).claims[UNEXPIRED], 'established')
  assert.equal((await checkDirect(a, sealEnvelope(validEnvelope), { now: at(1) })).claims[UNEXPIRED], 'not_established:authorization_expired')
})

test('held-out: arguments compare as structured values, with null, nesting and array order kept', async () => {
  const a = direct()
  const args = { payment_id: 'pay_A', amount_minor: 4000, currency: 'EUR', memo: null, lines: [{ sku: 'x', qty: 1 }, { sku: 'y', qty: 2 }] }
  const ev = sealEnvelope(envelopeWith(e => { e.transport_projection.action = { tool: 'refund', args } }))
  const action = (edit: (x: any) => void = () => {}) => { const x = structuredClone({ tool: 'refund', args }); edit(x); return x }
  assert.equal((await checkDirect(a, ev, { action: action() })).claims[BOUND], 'established')
  // key order is not a difference
  assert.equal((await checkDirect(a, ev, { action: { args: { lines: args.lines, memo: null, currency: 'EUR', amount_minor: 4000, payment_id: 'pay_A' }, tool: 'refund' } })).claims[BOUND], 'established')
  for (const [what, edit] of [
    ['null against the string "null"', (x: any) => { x.args.memo = 'null' }],
    ['null against absent', (x: any) => { delete x.args.memo }],
    ['array order', (x: any) => { x.args.lines.reverse() }],
    ['a nested value', (x: any) => { x.args.lines[1].qty = 3 }],
    ['a nested key', (x: any) => { x.args.lines[0].note = 'x' }],
    ['the tool', (x: any) => { x.tool = 'transfer' }],
    ['an array against an object with index keys', (x: any) => { x.args.lines = { '0': args.lines[0], '1': args.lines[1] } }],
    ['an array against an object with index keys, nested', (x: any) => { x.args.lines = [args.lines[0], { '0': 'y', '1': 2 }] }],
  ] as const) {
    assert.equal((await checkDirect(a, ev, { action: action(edit) })).claims[BOUND], 'not_established:action_differs', what)
  }
  // JSON semantics: a member whose value is undefined is not a member.
  assert.equal((await checkDirect(a, ev, { action: action(x => { x.args.extra = undefined }) })).claims[BOUND], 'established')
  assert.equal((await checkDirect(a, ev, { action: action(x => { x.args.lines[0].extra = undefined }) })).claims[BOUND], 'established')
})

test('held-out: each bound dimension is reported by its own reason, in the declared order', async () => {
  const a = direct()
  const ev = sealEnvelope(validEnvelope)
  assert.equal((await checkDirect(a, ev, { workflow: 'payout' })).claims[BOUND], 'not_established:workflow_differs')
  assert.equal((await checkDirect(a, ev, { operation_id: 'op-other' })).claims[BOUND], 'not_established:operation_id_differs')
  assert.equal((await checkDirect(a, ev, { approval_id: 'apr-other' })).claims[BOUND], 'not_established:approval_id_differs')
  // several differ: the first in the ladder names the reason
  assert.equal((await checkDirect(a, ev, { workflow: 'payout', approval_id: 'apr-other' })).claims[BOUND], 'not_established:workflow_differs')
  assert.equal((await checkDirect(a, ev, { tenant: 'tenant-b', approval_id: 'apr-other' })).claims[BOUND], 'not_established:tenant_differs')
})

test('held-out: trusted_keys must be 32-byte Ed25519 keys, and the pinned set is the only set', async () => {
  assert.throws(() => direct(['ab'.repeat(31)]), /32 bytes/)
  assert.throws(() => direct(['ab'.repeat(33)]), /32 bytes/)
  const none = direct([])
  assert.deepEqual((await checkDirect(none, sealEnvelope(validEnvelope))).claims, integrityFailed('unknown_kid'))
})

test('held-out: the runtime refuses each envelope-level and signature-level case before dispatch', async () => {
  const c = validCase
  for (const [what, evidence] of [
    ['wrong signature', () => sealEnvelope(validEnvelope, {}, {}, generateKeyPairSync('ed25519').privateKey)],
    ['not addressed', () => sealEnvelope(envelopeWith(e => { delete e.transport_projection }))],
    ['canonicalization', () => sealEnvelope(envelopeWith(e => { e.action.canonicalization = 'json-v0' }))],
    ['no evidence', () => new Uint8Array()],
  ] as const) {
    const e = await env(c.now)
    try {
      const r = await e.rt.submit(submission(c, r => { r.evidence[REMORA] = evidence() }))
      assert.equal(r.status, 'refused', what)
      assert.equal(e.provider.requests, 0, what)
    } finally { await e.close() }
  }
})
