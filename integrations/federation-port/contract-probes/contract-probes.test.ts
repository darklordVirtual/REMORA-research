// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// Contract probes for federation-port/v0: one test per normative clause of spec/CONTRACT.md that
// the upstream suite at the pinned revision does not already exercise, run against the UNMODIFIED
// runtime. They test the runtime, not a REMORA component, so any project on #177 can run them.
//
//   FEDERATION_PORT_DIR=/path/to/federation-port node --test contract-probes.test.ts
//
// or copied into federation-port's test/ by ../remora-adapter/reproduce.sh, with REMORA_INTEROP_DIR
// set. Every test title starts with its probe id; contract-coverage.json maps each clause to the
// upstream, REMORA and probe tests that cover it, and the last test here checks that map against
// the test files actually present.
//
// Two kinds of test:
//   CP-<section><letter>  a clause holds. A failure is a contract violation at the pinned revision.
//   CP-F<n>               a finding these probes made at 92d5078 and that aeoess/federation-port#1
//                         fixed (merged as 3a2f6ce). Each now asserts the fixed behaviour, so a
//                         regression upstream fails it. What each found at 92d5078 stays recorded
//                         in contract-coverage.json.
//
// Probe components are generated into temporary directories at run time, sealed with the
// runtime's own artifactDigest, so nothing under federation-port's tree is changed.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash } from 'node:crypto'

const FP: string = process.env.FEDERATION_PORT_DIR ?? ''
if (!FP) throw new Error('set FEDERATION_PORT_DIR to a federation-port checkout')
const INTEROP = resolve(process.env.REMORA_INTEROP_DIR
  ?? resolve(import.meta.dirname, '../../../artifacts/interop/federation-port-v0'))
const COVERAGE = JSON.parse(readFileSync(join(INTEROP, 'contract-coverage.json'), 'utf8'))

const imp = (rel: string) => import(pathToFileURL(join(FP, rel)).href)
const { Runtime, loadComponent, artifactDigest, digestJson, sha256 } = await imp('src/runtime/index.ts')
const { APS, EXEC, opId, setup, restart, pinFromDisk, request, tmp, child, delayCheck } = await imp('test/helpers.ts')
const { APPROVED_REFUND } = await imp('sim/profile.ts')

const PROBE = 'remora-research/contract-probe'
const reasonsOf = (r: any): string[] => r.reasons ?? []

test('the pinned federation-port revision is checked out, and its src/ is unmodified', () => {
  const head = execFileSync('git', ['-C', FP, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  assert.equal(`aeoess/federation-port@${head}`, COVERAGE.transport_revision)
  assert.equal(execFileSync('git', ['-C', FP, 'status', '--porcelain', '--', 'src'], { encoding: 'utf8' }), '')
})

// ---- probe components ----------------------------------------------------------------------

/** A check component whose behaviour ctx.config selects. Plain JavaScript, so it runs from a temp dir. */
const PROBE_SOURCE = `
import { readFileSync } from 'node:fs'
const manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))
export function createAdapter(ctx) {
  const c = ctx.config
  return {
    describe: () => manifest,
    async check(input) {
      const ok = { claim: 'probe.ok', status: 'established' }
      const deadline = c.valid_until === undefined ? {} : { valid_until: c.valid_until }
      switch (c.mode) {
        case 'duplicate': return { evidence: new Uint8Array([1]), claims: [ok, ok], ...deadline }
        case 'secrets': return { evidence: new TextEncoder().encode(JSON.stringify(Object.keys(ctx.secrets).sort())), claims: [ok], ...deadline }
        case 'mutate_later': {
          const bytes = new TextEncoder().encode('probe-evidence-as-returned')
          setTimeout(() => bytes.fill(0x58), 0)
          return { evidence: bytes, claims: [ok], ...deadline }
        }
        case 'mutate_input': {
          const tried = []
          for (const [what, f] of [['args', () => { input.action.args.amount_minor = 1 }],
                                   ['tool', () => { input.action.tool = 'other' }],
                                   ['new_arg', () => { input.action.args.injected = true }]]) {
            try { f(); tried.push(what + ':mutated') } catch { tried.push(what + ':refused') }
          }
          return { evidence: new TextEncoder().encode(tried.join(',')), claims: [ok], ...deadline }
        }
        default: return { evidence: new Uint8Array([1]), claims: [ok], ...deadline }
      }
    },
  }
}
`

function baseManifest(id: string) {
  return {
    contract: 'federation-port/v0', id,
    publisher: { name: 'REMORA-research contract probe' }, maintainer: { name: 'REMORA-research' },
    artifact: { version: '0.1.0', entry: 'adapter.ts', files: ['adapter.ts'], digest: '' },
    role: 'action_evaluation',
    schemas: { output_evidence: { media_type: 'application/octet-stream', description: 'probe bytes' } },
    claims: [{ id: 'probe.ok', establishes: 'The probe returned established.', limits: ['Contract probe only'] }],
    profiles: [], privileges_requested: [] as string[], data_destinations: [] as string[], keys: [],
    license: { spdx: 'BUSL-1.1', attribution: 'REMORA-research contract probe' },
  }
}

/**
 * Write a component into a fresh directory and seal it: artifact.digest is the runtime's own
 * artifactDigest over the declared files. `edit` runs after sealing, to produce load-time defects.
 */
function makeComponent(o: { id?: string; source?: string; edit?: (m: any) => void; keyOrder?: 'reversed' } = {}): string {
  const dir = mkdtempSync(join(tmpdir(), 'cp-comp-'))
  writeFileSync(join(dir, 'adapter.ts'), o.source ?? PROBE_SOURCE)
  const m: any = baseManifest(o.id ?? PROBE)
  m.artifact.digest = artifactDigest(dir, m.artifact.files)
  o.edit?.(m)
  const reorder = (v: any): any => Array.isArray(v) ? v.map(reorder)
    : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).reverse().map(k => [k, reorder(v[k])])) : v
  writeFileSync(join(dir, 'manifest.json'), o.keyOrder === 'reversed' ? JSON.stringify(reorder(m)) : JSON.stringify(m, null, 2))
  return dir
}

const probePin = (dir: string, config: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) =>
  pinFromDisk(dir, { config, ...extra })

/** A pin for a manifest that is refused before its artifact is read: the artifact digest is never compared. */
function manifestPin(dir: string) {
  const m = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'))
  return { path: dir, version: m.artifact.version, manifest_digest: digestJson(m), artifact_digest: 'sha256:' + '0'.repeat(64),
    privileges_granted: [...m.privileges_requested], destinations_allowed: [...m.data_destinations] }
}

async function loadCode(id: string, pin: unknown, secrets: Record<string, string> = {}): Promise<string> {
  try { await loadComponent(id, pin, secrets); return 'loaded' } catch (e: any) { return e.code ?? String(e) }
}

// ---- section 2 and 3: manifest and digests ----------------------------------------------------

test('CP-02a the contract field must be federation-port/v0: another value is refused at load', async () => {
  const dir = makeComponent({ edit: m => { m.contract = 'federation-port/v1' } })
  assert.equal(await loadCode(PROBE, manifestPin(dir)), 'contract_version_unsupported')
})

test('CP-02b artifact.files must include the entry: an entry outside the digest is refused at load', async () => {
  const dir = makeComponent({ edit: m => { m.artifact.entry = 'other.ts' } })
  writeFileSync(join(dir, 'other.ts'), PROBE_SOURCE)
  assert.equal(await loadCode(PROBE, manifestPin(dir)), 'entry_not_covered_by_digest')
})

test('CP-02c artifact.files may not hold absolute or .. paths: each is refused at load', async () => {
  for (const bad of ['../outside.ts', '/etc/hostname', 'sub/../../outside.ts']) {
    const dir = makeComponent({ edit: m => { m.artifact.files = ['adapter.ts', bad] } })
    assert.equal(await loadCode(PROBE, manifestPin(dir)), 'artifact_path_outside_component', bad)
  }
})

test('CP-03a the manifest digest is over sorted-key JSON: key order and whitespace in the file do not change it', async () => {
  const pretty = makeComponent()
  const reversed = makeComponent({ keyOrder: 'reversed' })
  const a = probePin(pretty), b = probePin(reversed)
  assert.notEqual(readFileSync(join(pretty, 'manifest.json'), 'utf8'), readFileSync(join(reversed, 'manifest.json'), 'utf8'))
  assert.equal(a.manifest_digest, b.manifest_digest)
  // The reversed file loads under the pin computed from the pretty one.
  assert.equal(await loadCode(PROBE, { ...a, path: reversed }), 'loaded')
})

test('CP-03b the manifest is not part of the artifact digest: a manifest-only change moves the manifest digest alone', async () => {
  const dir = makeComponent()
  const before = probePin(dir)
  const m = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'))
  m.publisher.name = 'someone else'
  writeFileSync(join(dir, 'manifest.json'), JSON.stringify(m))
  const after = probePin(dir)
  assert.equal(after.artifact_digest, before.artifact_digest)
  assert.notEqual(after.manifest_digest, before.manifest_digest)
  assert.equal(await loadCode(PROBE, before), 'manifest_changed')
})

// ---- section 8: load refusals the upstream suite does not exercise -----------------------------

test('CP-08a a version other than the pinned one is refused at load', async () => {
  const dir = makeComponent()
  assert.equal(await loadCode(PROBE, probePin(dir, {}, { version: '0.2.0' })), 'version_not_pinned')
})

test('CP-08b an artifact digest other than the pinned one is refused at load, even with a consistent manifest', async () => {
  const dir = makeComponent()
  assert.equal(await loadCode(PROBE, probePin(dir, {}, { artifact_digest: 'sha256:' + '0'.repeat(64) })), 'artifact_not_pinned')
})

test('CP-08c a granted secret the operator did not provision is refused at load', async () => {
  const dir = makeComponent({ edit: m => { m.privileges_requested = ['secret:probe_key'] } })
  assert.equal(await loadCode(PROBE, probePin(dir), {}), 'secret_not_provisioned')
  assert.equal(await loadCode(PROBE, probePin(dir), { probe_key: 'x' }), 'loaded')
})

test('CP-08d an entry without createAdapter is refused at load', async () => {
  const dir = makeComponent({ source: 'export const nothing = 1\n' })
  assert.equal(await loadCode(PROBE, probePin(dir)), 'entry_missing_createAdapter')
})

test('CP-08e an adapter without the method its role needs is refused at load', async () => {
  const dir = makeComponent({ source: PROBE_SOURCE.replace('async check(input)', 'async notCheck(input)') })
  assert.equal(await loadCode(PROBE, probePin(dir)), 'adapter_missing_role_method')
})

test('CP-08f describe() that differs from the manifest file is refused at load', async () => {
  const dir = makeComponent({ source: PROBE_SOURCE.replace('describe: () => manifest', "describe: () => ({ ...manifest, role: 'authority_evidence' })") })
  assert.equal(await loadCode(PROBE, probePin(dir)), 'describe_differs_from_manifest')
})

// ---- section 4: adapter interface ---------------------------------------------------------------

test('CP-04a ctx.secrets carries only the names granted as secret:<name>, nothing else the operator provisioned', async () => {
  const asks = makeComponent({ edit: m => { m.privileges_requested = ['secret:probe_key'] } })
  const P2 = 'remora-research/contract-probe-2'
  const silent = makeComponent({ id: P2 })
  const env = await setup()
  try {
    // setup() provisions only the provider key, and the probe that asks for probe_key would not
    // load without it, so the probes join the policy here, with probe_key provisioned beside it.
    env.policy = { ...env.policy,
      components: { ...env.policy.components, [PROBE]: probePin(asks, { mode: 'secrets' }), [P2]: probePin(silent, { mode: 'secrets' }) },
      workflows: { refund: { ...env.policy.workflows.refund,
        optional_claims: [{ component: PROBE, claim: 'probe.ok' }, { component: P2, claim: 'probe.ok' }] } } }
    env.rt.close()
    env.rt = await Runtime.create({ policy: env.policy, dbPath: env.dbPath, secrets: { provider_api_key: env.apiKey, probe_key: 'k' } })
    const { req } = request(env)
    const r = await env.rt.submit(req)
    assert.equal(r.status, 'provider_confirmed', JSON.stringify(r))
    const seen = (id: string) => JSON.parse(Buffer.from(env.rt.store.evidence(req.operation_id, id, 'check:0')).toString('utf8'))
    assert.deepEqual(seen(PROBE), ['probe_key'])
    assert.deepEqual(seen(P2), [])
  } finally { await env.close() }
})

test('CP-04b CheckInput is a frozen copy: an adapter cannot change the action another component checks or the executor receives', async () => {
  const dir = makeComponent()
  const env = await setup({ extraComponents: { [PROBE]: probePin(dir, { mode: 'mutate_input' }) },
    optional: [{ component: PROBE, claim: 'probe.ok' }] })
  try {
    const seen: unknown[] = []
    const c = env.rt.component(EXEC)
    const original = c.adapter.execute.bind(c.adapter)
    c.adapter.execute = async (op: any) => { seen.push(structuredClone(op.action)); return original(op) }
    const { req } = request(env)
    const r = await env.rt.submit(req)
    assert.equal(r.status, 'provider_confirmed', JSON.stringify(r))
    const tried = Buffer.from(env.rt.store.evidence(req.operation_id, PROBE, 'check:0')).toString('utf8')
    assert.equal(tried, 'args:refused,tool:refused,new_arg:refused')
    assert.deepEqual(seen, [{ tool: 'refund', args: { ...APPROVED_REFUND } }])
  } finally { await env.close() }
})

// ---- section 5: evidence rule -------------------------------------------------------------------

test('CP-05a evidence is stored as returned: an adapter that mutates its buffer afterwards does not change the stored bytes', async () => {
  const dir = makeComponent()
  const env = await setup({ extraComponents: { [PROBE]: probePin(dir, { mode: 'mutate_later' }) },
    optional: [{ component: PROBE, claim: 'probe.ok' }] })
  try {
    // The other component answers later, so the probe's mutation lands before anything is stored.
    delayCheck(env.rt, APS, 30)
    const { req } = request(env)
    await env.rt.submit(req)
    await new Promise(ok => setTimeout(ok, 20))
    const stored = env.rt.store.evidence(req.operation_id, PROBE, 'check:0')
    assert.equal(Buffer.from(stored).toString('utf8'), 'probe-evidence-as-returned')
    const recorded = (env.rt.provenance(req.operation_id) as any).admissions[0].evidence.find((e: any) => e.component === PROBE)
    assert.equal(recorded.digest, sha256(new TextEncoder().encode('probe-evidence-as-returned')))
  } finally { await env.close() }
})

test('CP-05b a claim reported twice makes that claim unavailable, never established', async () => {
  const dir = makeComponent()
  const env = await setup({ extraComponents: { [PROBE]: probePin(dir, { mode: 'duplicate' }) },
    required: [{ component: APS, claim: 'approval.signature_valid' }, { component: PROBE, claim: 'probe.ok' }] })
  try {
    const r = await env.rt.submit(request(env).req)
    assert.deepEqual(reasonsOf(r), [`required_claim_unavailable:${PROBE}#probe.ok:adapter_protocol_violation:duplicate`])
    assert.equal(env.provider.requests, 0)
  } finally { await env.close() }
})

test('CP-05c every valid_until form outside exact UTC milliseconds makes all the component\'s claims unavailable', async () => {
  // The contract names: no milliseconds, an offset, an impossible calendar date, a non-string.
  const forms: unknown[] = ['2099-01-01T00:00:00Z', '2099-01-01T00:00:00.000+00:00', '2026-02-30T00:00:00.000Z',
    4102444800000, '2099-01-01T00:00:00.0000Z', '2099-01-01 00:00:00.000Z', '']
  for (const form of forms) {
    const dir = makeComponent()
    const env = await setup({ extraComponents: { [PROBE]: probePin(dir, { valid_until: form }) },
      required: [{ component: APS, claim: 'approval.signature_valid' }, { component: PROBE, claim: 'probe.ok' }] })
    try {
      const r = await env.rt.submit(request(env).req)
      assert.deepEqual(reasonsOf(r), [`required_claim_unavailable:${PROBE}#probe.ok:adapter_protocol_violation:valid_until`], JSON.stringify(form))
      assert.equal(env.provider.requests, 0)
    } finally { await env.close() }
  }
})

// ---- section 6: admission deadline --------------------------------------------------------------

function withDeadlineProbe(requirement: 'required' | 'optional', probeDeadline: string) {
  const ref = [{ component: PROBE, claim: 'probe.ok' }]
  return setup({ extraComponents: { [PROBE]: probePin(makeComponent(), { valid_until: probeDeadline }) },
    ...(requirement === 'required'
      ? { required: [{ component: APS, claim: 'approval.signature_valid' }, { component: APS, claim: 'approval.unexpired' }, ...ref] }
      : { optional: ref }) })
}

test('CP-06a an optional component\'s earlier valid_until does not shorten the admission deadline', async () => {
  const T0 = new Date('2026-10-08T12:00:00.000Z')
  const env = await withDeadlineProbe('optional', '2026-10-08T12:00:01.000Z')
  try {
    const now = new Date(T0.getTime() + 5_000)  // past the optional deadline, inside the approval's
    await restart(env, env.policy, () => now)
    const a = env.operator.issue(APPROVED_REFUND, { issuedAt: T0, ttlMs: 60_000 })
    const req = { workflow: 'refund', operation_id: opId(), approval_id: a.approval_id, action: { tool: 'refund', args: { ...APPROVED_REFUND } }, evidence: { [APS]: a.evidence } }
    const r = await env.rt.submit(req)
    assert.equal(r.status, 'provider_confirmed', JSON.stringify(r))
    assert.equal(env.rt.store.getOperation(req.operation_id).valid_until_ms, Date.parse(a.valid_until))
  } finally { await env.close() }
})

test('CP-06b with two required components, the earliest valid_until binds admission', async () => {
  const T0 = new Date('2026-10-08T12:00:00.000Z')
  const env = await withDeadlineProbe('required', '2026-10-08T12:00:01.000Z')
  try {
    let now = new Date(T0.getTime() + 500)
    await restart(env, env.policy, () => now)
    const a = env.operator.issue(APPROVED_REFUND, { issuedAt: T0, ttlMs: 60_000 })
    const req = { workflow: 'refund', operation_id: opId(), approval_id: a.approval_id, action: { tool: 'refund', args: { ...APPROVED_REFUND } }, evidence: { [APS]: a.evidence } }
    // Checks pass at T0+0.5s; the admission write then reads T0+1.001s: past the probe's deadline only.
    const c = env.rt.component(APS)
    const original = c.adapter.check.bind(c.adapter)
    c.adapter.check = async (input: any) => { const out = await original(input); now = new Date(T0.getTime() + 1_001); return out }
    const r = await env.rt.submit(req)
    assert.deepEqual(reasonsOf(r), ['approval_expired_at_admission'])
    assert.equal(env.rt.store.approvalConsumedBy(a.approval_id), undefined)
    assert.equal(env.provider.requests, 0)
  } finally { await env.close() }
})

// ---- section 7: operation states and retries ----------------------------------------------------

test('CP-07a concurrent retries of an unknown operation in one process: exactly one new dispatch', async () => {
  const env = await setup()
  try {
    const { req } = request(env)
    env.provider.setFault({ mode: 'drop_after_commit', count: 1 })
    assert.equal((await env.rt.submit(req)).status, 'unknown')
    const rs = await Promise.all(Array.from({ length: 8 }, () => env.rt.submit(req)))
    assert.equal(rs.filter((r: any) => r.status === 'provider_confirmed' && !r.replayed).length, 1, JSON.stringify(rs))
    assert.ok(rs.every((r: any) => ['provider_confirmed', 'in_flight'].includes(r.status)), JSON.stringify(rs))
    assert.equal(env.provider.requests, 2)
    assert.equal(env.provider.refunds.length, 1)
    assert.equal(env.rt.store.attempts(req.operation_id).length, 2)
  } finally { await env.close() }
})

test('CP-07b concurrent retries of an unknown operation from 4 OS processes sharing the store: exactly one new dispatch', async () => {
  const env = await setup()
  try {
    const { req } = request(env)
    env.provider.setFault({ mode: 'drop_after_commit', count: 1 })
    assert.equal((await env.rt.submit(req)).status, 'unknown')
    const job = join(tmp(), 'job.json')
    const evidence = Object.fromEntries(Object.entries(req.evidence).map(([k, v]) => [k, Buffer.from(v as Uint8Array).toString('base64')]))
    writeFileSync(job, JSON.stringify({ policy: env.policy, dbPath: env.dbPath, request: { ...req, evidence } }))
    const worker = join(FP, 'test/fixtures/port-worker.ts')
    const outs = await Promise.all(Array.from({ length: 4 }, () => child(worker, [job], { FP_PROVIDER_KEY: env.apiKey }).done))
    const rs = outs.map((o: any) => { assert.equal(o.code, 0); return JSON.parse(o.lines.at(-1)) })
    assert.ok(rs.every((r: any) => ['provider_confirmed', 'in_flight'].includes(r.status)), JSON.stringify(rs))
    assert.equal(env.provider.requests, 2)
    assert.equal(env.provider.refunds.length, 1)
    assert.equal(env.rt.store.attempts(req.operation_id).length, 2)
  } finally { await env.close() }
})

test('CP-07c a dispatch lease blocks retries while it runs, and a lease left by a dead worker expires into one re-dispatch under the same key', async () => {
  const env = await setup()
  try {
    const T0 = Date.now()
    await restart(env, env.policy, () => new Date(T0))
    const { req } = request(env)
    // Worker A admits and then never reaches the provider (it hangs until the execute timeout).
    let entered!: () => void
    const inside = new Promise<void>(ok => { entered = ok })
    env.rt.component(EXEC).adapter.execute = () => { entered(); return new Promise(() => {}) }
    const pending = env.rt.submit(req)
    await inside
    const lease = env.rt.store.getOperation(req.operation_id).lease_until
    assert.ok(lease > T0, 'the lease is live at admission')
    const at = async (ms: number) => {
      const rt = await Runtime.create({ policy: env.policy, dbPath: env.dbPath, secrets: { provider_api_key: env.apiKey }, clock: () => new Date(ms) })
      try { return await rt.submit(req) } finally { rt.close() }
    }
    for (const t of [T0 + 1, lease - 1]) assert.equal((await at(t)).status, 'in_flight')
    assert.equal(env.provider.requests, 0)
    const after = await at(lease + 1)
    assert.equal(after.status, 'provider_confirmed', JSON.stringify(after))
    assert.equal((after as any).attempt, 2)
    assert.equal(env.provider.refunds.length, 1)
    assert.equal(env.provider.refunds[0].idempotency_key, req.operation_id)
    await pending  // A's own timeout records attempt 1 as unknown; the later attempt keeps the state
    assert.equal(env.rt.store.getOperation(req.operation_id).state, 'provider_confirmed')
  } finally { await env.close() }
})

test('CP-07d retry refusals are checked in the contract\'s order: the first differing binding is the one reported', async () => {
  const env = await setup()
  try {
    const { req } = request(env)
    env.provider.setFault({ mode: 'drop_after_commit', count: 1 })
    assert.equal((await env.rt.submit(req)).status, 'unknown')
    const otherEvidence = { [APS]: new Uint8Array([...req.evidence[APS], 0x20]) }
    const otherArgs = { tool: 'refund', args: { ...APPROVED_REFUND, amount_minor: 3900 } }
    const cases: [string, any, string][] = [
      ['tenant, action, evidence', { ...req, tenant: 't-b', action: otherArgs, evidence: otherEvidence }, 'operation_tenant_mismatch'],
      ['action, evidence', { ...req, action: otherArgs, evidence: otherEvidence }, 'operation_id_reused_for_different_action'],
      ['approval id, evidence', { ...req, approval_id: 'apr-other', evidence: otherEvidence }, 'operation_id_reused_for_different_action'],
      ['evidence alone', { ...req, evidence: otherEvidence }, 'operation_evidence_changed'],
    ]
    for (const [what, retry, code] of cases) assert.deepEqual(reasonsOf(await env.rt.submit(retry)), [code], what)
    // Evidence and policy both changed: evidence precedes the execution context.
    await restart(env, { ...env.policy, policy_id: 'another-policy' })
    assert.deepEqual(reasonsOf(await env.rt.submit({ ...req, evidence: otherEvidence })), ['operation_evidence_changed'])
    assert.deepEqual(reasonsOf(await env.rt.submit(req)), ['operation_context_changed:policy_id'])
    // None of the refusals changed the stored operation: under the original policy it recovers.
    await restart(env, env.policy)
    assert.equal((await env.rt.submit(req)).status, 'provider_confirmed')
    assert.equal(env.provider.refunds.length, 1)
  } finally { await env.close() }
})

// ---- section 9: provenance ------------------------------------------------------------------

test('CP-09a provenance holds no action arguments, evidence bytes or secrets of its own making', async () => {
  const env = await setup()
  try {
    const marker = 'pay_MARKER7f3a'
    const ok = request(env, { ...APPROVED_REFUND, payment_id: marker }, { ...APPROVED_REFUND, payment_id: marker })
    const refusedBySchema = request(env, { ...APPROVED_REFUND, payment_id: marker, amount_minor: 'MARKER_AMOUNT' as any })
    // Admitted and dispatched; the simulator knows no such payment, so the attempt itself fails.
    assert.equal((await env.rt.submit(ok.req)).status, 'failed')
    assert.equal((await env.rt.submit(refusedBySchema.req)).status, 'refused')
    for (const { req } of [ok, refusedBySchema]) {
      const prov = JSON.stringify(env.rt.provenance(req.operation_id))
      for (const secret of [marker, 'MARKER_AMOUNT', env.apiKey, Buffer.from(req.evidence[APS]).toString('base64')]) {
        assert.ok(!prov.includes(secret), `provenance of ${req.operation_id} carries ${secret.slice(0, 16)}`)
      }
    }
  } finally { await env.close() }
})

// ---- findings, now regression probes: fixed upstream in aeoess/federation-port#1 -------------

test('CP-F1 FIXED (section 7): a confirmation from an attempt whose lease another worker took over is final; the operation is confirmed, not failed', async () => {
  // At 92d5078 the operation stayed failed and closed past the deadline while the refund existed.
  const env = await setup()
  try {
    const T0 = new Date(Date.now() - 1000)
    const nowA = new Date(T0.getTime() + 500)
    await restart(env, env.policy, () => nowA)
    const a = env.operator.issue(APPROVED_REFUND, { issuedAt: T0, ttlMs: 60_000 })
    const req = { workflow: 'refund', operation_id: opId(), approval_id: a.approval_id, action: { tool: 'refund', args: { ...APPROVED_REFUND } }, evidence: { [APS]: a.evidence } }
    let release!: () => void, entered!: () => void
    const gate = new Promise<void>(ok => { release = ok }), inside = new Promise<void>(ok => { entered = ok })
    const ca = env.rt.component(EXEC)
    const originalA = ca.adapter.execute.bind(ca.adapter)
    ca.adapter.execute = async (op: any) => { entered(); await gate; return originalA(op) }
    const fromA = env.rt.submit(req)
    await inside
    // Worker B, 2.5 s ahead, finds the lease expired and is cut off from the provider.
    const rtB = await Runtime.create({ policy: env.policy, dbPath: env.dbPath, secrets: { provider_api_key: env.apiKey }, clock: () => new Date(nowA.getTime() + 2_500) })
    rtB.component(EXEC).adapter.execute = async () => ({ outcome: 'failed', retriable: true, reason: 'provider_unreachable', evidence: new Uint8Array() })
    // B's attempt never reached the provider, but attempt 1 may have: unknown, not failed.
    assert.equal((await rtB.submit(req)).status, 'unknown')
    release()
    const resultA = await fromA
    assert.equal(resultA.status, 'provider_confirmed')
    assert.equal(rtB.store.getOperation(req.operation_id).state, 'provider_confirmed')
    assert.equal(env.provider.refunds.length, 1)
    const rtC = await Runtime.create({ policy: env.policy, dbPath: env.dbPath, secrets: { provider_api_key: env.apiKey }, clock: () => new Date(Date.parse(a.valid_until) + 1) })
    const later = await rtC.submit(req)
    assert.equal(later.status, 'provider_confirmed')
    assert.equal((later as any).replayed, true)
    rtB.close(); rtC.close()
  } finally { await env.close() }
})

test('CP-F2 FIXED (sections 5.5 and 7): nothing is dispatched after the deadline; an attempt that ended unknown before sending is never followed by a first request after valid_until', async () => {
  // At 92d5078 the provider's first request arrived an hour after the deadline.
  const env = await setup()
  try {
    const T0 = new Date(Date.now() - 1000)
    let now = new Date(T0.getTime() + 500)
    await restart(env, env.policy, () => now)
    const a = env.operator.issue(APPROVED_REFUND, { issuedAt: T0, ttlMs: 60_000 })
    const req = { workflow: 'refund', operation_id: opId(), approval_id: a.approval_id, action: { tool: 'refund', args: { ...APPROVED_REFUND } }, evidence: { [APS]: a.evidence } }
    const c = env.rt.component(EXEC)
    const original = c.adapter.execute.bind(c.adapter)
    let first = true
    c.adapter.execute = async (op: any) => { if (first) { first = false; throw new Error('socket closed before the request was written') } return original(op) }
    assert.equal((await env.rt.submit(req)).status, 'unknown')
    now = new Date(Date.parse(a.valid_until) + 3_600_000)
    const late = await env.rt.submit(req)
    assert.equal(late.status, 'unknown')
    assert.equal((late as any).reason, 'reconciliation_required')
    assert.equal(env.provider.requests, 0)
    assert.equal(env.provider.refunds.length, 0)
  } finally { await env.close() }
})

test('CP-F3 FIXED (section 9): an adapter\'s reason text is cut to 120 UTF-16 units before it reaches provenance; what fits in 120 units stays the adapter\'s obligation', async () => {
  // At 92d5078 a 100 kB reason was stored whole.
  const env = await setup()
  try {
    const c = env.rt.component(APS)
    const original = c.adapter.check.bind(c.adapter)
    c.adapter.check = async (input: any) => {
      const out = await original(input)
      return { ...out, claims: out.claims.map((x: any, i: number) => i === 0
        ? { ...x, status: 'not_established', reason: 'x'.repeat(100_000) } : x) }
    }
    const { req } = request(env)
    const r = await env.rt.submit(req)
    assert.equal(r.status, 'refused')
    const reason = (env.rt.provenance(req.operation_id) as any).admissions.at(-1).claims[0].reason
    assert.equal(reason, 'x'.repeat(120))
    assert.ok(JSON.stringify(env.rt.provenance(req.operation_id)).length < 10_000)
  } finally { await env.close() }
})

test('CP-F4 FIXED (sections 4 and 7): a lost response, then an outage, then the deadline: the operation stays unknown and is not closed as failed while the refund exists', async () => {
  // Found by formal/tla/LeaseRetry.tla (configuration pinned_outage). At 92d5078 the operation was
  // closed with approval_expired_before_retry while the provider had performed the refund.
  const env = await setup()
  let providerUp = true
  try {
    const T0 = new Date(Date.now() - 1000)
    await restart(env, env.policy, () => new Date(T0.getTime() + 500))
    const a = env.operator.issue(APPROVED_REFUND, { issuedAt: T0, ttlMs: 60_000 })
    const req = { workflow: 'refund', operation_id: opId(), approval_id: a.approval_id, action: { tool: 'refund', args: { ...APPROVED_REFUND } }, evidence: { [APS]: a.evidence } }
    env.provider.setFault({ mode: 'drop_after_commit', count: 1 })
    assert.equal((await env.rt.submit(req)).status, 'unknown')
    assert.equal(env.provider.refunds.length, 1)
    providerUp = false
    await env.provider.close()  // the provider is now unreachable (ECONNREFUSED)
    const retry = await env.rt.submit(req)
    assert.equal(retry.status, 'unknown')
    await restart(env, env.policy, () => new Date(Date.parse(a.valid_until) + 1))
    const late = await env.rt.submit(req)
    assert.equal(late.status, 'unknown')
    assert.equal((late as any).reason, 'reconciliation_required')
    const row = env.rt.store.getOperation(req.operation_id)
    assert.equal(row.state, 'unknown')
    assert.deepEqual(env.rt.store.attempts(req.operation_id).map((x: any) => x.outcome), ['unknown', 'failed'])
  } finally { if (providerUp) await env.close(); else env.rt.close() }
})

// ---- the coverage map resolves --------------------------------------------------------------

test('contract-coverage.json names only tests that exist, and every probe here is in it', () => {
  const testDir = join(FP, 'test')
  const sources = readdirSync(testDir).filter(f => f.endsWith('.test.ts'))
    .map(f => readFileSync(join(testDir, f), 'utf8')).join('\n')
  const self = readFileSync(new URL(import.meta.url), 'utf8')
  const probeIds = [...self.matchAll(/^test\('(CP-[0-9F]+[a-z0-9]*) /gm)].map(m => m[1])
  const listed = new Set<string>()
  for (const clause of COVERAGE.clauses) {
    for (const t of clause.upstream ?? []) {
      // An upstream test is named by its id (C05, D1b, RE-c) or, when it has none, by its full title.
      const title = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      assert.ok(new RegExp(`test\\(['\`]${title}[ '\`]`).test(sources), `upstream test ${t} (${clause.id}) exists at the pinned revision`)
    }
    for (const t of clause.probes ?? []) { assert.ok(probeIds.includes(t), `probe ${t} (${clause.id}) exists`); listed.add(t) }
  }
  for (const f of COVERAGE.findings) { assert.ok(probeIds.includes(f.probe), `finding probe ${f.probe} exists`); listed.add(f.probe) }
  assert.deepEqual(probeIds.filter(p => !listed.has(p)), [], 'every probe is mapped to a clause or a finding')
  assert.equal(new Set(probeIds).size, probeIds.length, 'probe ids are unique')
  const digest = 'sha256:' + createHash('sha256').update(readFileSync(join(FP, 'spec/CONTRACT.md'))).digest('hex')
  assert.equal(COVERAGE.contract.digest, digest, 'the map was written against this CONTRACT.md')
})
