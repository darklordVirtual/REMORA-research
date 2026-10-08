// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// Acceptance for REMORA's report-result component, run inside an unmodified federation-port runtime.
//
//   FEDERATION_PORT_DIR=/path/to/federation-port node --test tests/remora-report-result.test.ts
//
// or copied into federation-port's test/ by ../remora-adapter/reproduce.sh, with
// REMORA_REPORT_COMPONENT_DIR, REMORA_ADAPTER_DIR and REMORA_INTEROP_DIR set.
//
// The LATE and LATE-CONFLICT cases reproduce, locally and synthetically, the semantics of
// Rul1an's public fixtures (aeoess/agent-governance-vocabulary#177). Each report is evaluated
// separately, so all four expectations are checked: collapsing a case to one result per
// operation would erase what it tests. It tests the adapter's selection, not the runtime.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { createHash, createPrivateKey, randomBytes, sign as signBytes } from 'node:crypto'

const FP: string = process.env.FEDERATION_PORT_DIR ?? ''
if (!FP) throw new Error('set FEDERATION_PORT_DIR to a federation-port checkout')
const COMPONENT = resolve(process.env.REMORA_REPORT_COMPONENT_DIR ?? resolve(import.meta.dirname, '..'))
const AUTHORITY = resolve(process.env.REMORA_ADAPTER_DIR ?? resolve(import.meta.dirname, '../../remora-adapter'))
const INTEROP = resolve(process.env.REMORA_INTEROP_DIR
  ?? resolve(import.meta.dirname, '../../../../artifacts/interop/federation-port-v0'))
const REPORTS = JSON.parse(readFileSync(join(INTEROP, 'report-results.json'), 'utf8'))
const ACTIONS = JSON.parse(readFileSync(join(INTEROP, 'fixtures.json'), 'utf8'))

const runtimeMod = await import(pathToFileURL(join(FP, 'src/runtime/index.ts')).href)
const providerMod = await import(pathToFileURL(join(FP, 'sim/provider.ts')).href)
const { Runtime, artifactDigest, digestJson } = runtimeMod

const REPORT = 'remora-research/report-result'
const AUTH = 'remora-research/authorization-evidence'
const EXEC = 'example.sim/refund-executor'
const CLAIM = 'remora.report_result'
const AUTH_CLAIMS = ['remora.authorization_integrity', 'remora.port_v0.bound_action', 'remora.authorization_unexpired']
const REFUND = { payment_id: 'pay_A', amount_minor: 4000, currency: 'EUR' }

function pin(path: string, config: Record<string, unknown>) {
  const m = JSON.parse(readFileSync(join(path, 'manifest.json'), 'utf8'))
  return { path, version: m.artifact.version, manifest_digest: digestJson(m),
    artifact_digest: artifactDigest(path, m.artifact.files), privileges_granted: [...m.privileges_requested],
    destinations_allowed: [...m.data_destinations], config }
}

async function env(o: { gated?: boolean; nativeClaim?: string; now?: string } = {}) {
  const apiKey = randomBytes(24).toString('hex')
  const provider = await providerMod.startProvider({ apiKey })
  const components: Record<string, unknown> = {
    [REPORT]: pin(COMPONENT, { trusted_keys: [REPORTS.test_keys.result_public_key_hex],
                               native_claim: o.nativeClaim ?? REPORTS.native_claim }),
    [EXEC]: pin(join(FP, 'sim/executor'), { base_url: provider.url }),
  }
  const required = [{ component: REPORT, claim: CLAIM }]
  if (o.gated) {
    components[AUTH] = pin(AUTHORITY, { trusted_keys: [ACTIONS.test_keys.public_key_hex] })
    required.push(...AUTH_CLAIMS.map(claim => ({ component: AUTH, claim })))
  }
  const policy = {
    policy_id: 'remora-report-result-test', components,
    workflows: { refund: { executor: EXEC, tool: 'refund', approval: o.gated ? 'required' : 'none',
      required_claims: required, optional_claims: [], check_timeout_ms: 500, execute_timeout_ms: 1000 } },
  }
  let rt
  try {
    rt = await Runtime.create({ policy, dbPath: join(mkdtempSync(join(tmpdir(), 'remora-rr-')), 'port.db'),
      secrets: { provider_api_key: apiKey }, ...(o.now ? { clock: () => new Date(o.now as string) } : {}) })
  } catch (err) {
    await provider.close()
    throw err
  }
  return { rt, provider, async close() { rt.close(); await provider.close() } }
}

const caseOf = (name: string) => REPORTS.cases.find((c: any) => c.name === name)
const resultsOf = (c: any) => c.results.map((r: any) => r.evidence_b64)
let n = 0
const opId = () => `rr-${process.pid}-${Date.now()}-${n++}`

function check(requested: Record<string, unknown> | undefined, results: string[]): Uint8Array {
  return new Uint8Array(Buffer.from(JSON.stringify({ format: 'remora-report-check-v1',
    ...(requested ? { requested } : {}), results })))
}

async function run(e: any, evidence: Uint8Array) {
  const op = opId()
  const r = await e.rt.submit({ workflow: 'refund', operation_id: op, action: { tool: 'refund', args: { ...REFUND } },
    evidence: { [REPORT]: evidence } })
  const record = JSON.parse(Buffer.from(e.rt.store.evidence(op, REPORT, 'check:0')).toString('utf8'))
  return { r, record }
}

test('the pinned federation-port revision is checked out, and its src/ is unmodified', () => {
  const head = execFileSync('git', ['-C', FP, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  assert.equal(`aeoess/federation-port@${head}`, ACTIONS.transport_revision)
  assert.equal(execFileSync('git', ['-C', FP, 'status', '--porcelain', '--', 'src'], { encoding: 'utf8' }), '')
})

// The four expectations, each evaluated on its own submission.
for (const name of ['LATE', 'LATE-CONFLICT']) {
  for (const reportId of ['report-1', 'report-2']) {
    test(`${name} ${reportId}: the requested report's own native result`, async () => {
      const c = caseOf(name)
      const expected = c.expected[reportId]
      const fixture = c.results.find((r: any) => r.report_id === reportId)
      const e = await env()
      try {
        const { r, record } = await run(e, check({ operation_id: c.operation_id, report_id: reportId }, resultsOf(c)))
        assert.equal(r.status, expected === 'ESTABLISHED' ? 'provider_confirmed' : 'refused', JSON.stringify(r))
        assert.equal(e.provider.requests, expected === 'ESTABLISHED' ? 1 : 0)
        // The evidence keeps the selection and the native result next to the claim status.
        assert.equal(record.selected.subject.report_id, reportId)
        assert.equal(record.selected.subject.report_digest, fixture.report_digest)
        assert.equal(record.selected.adapter_selection_rule, 'explicit_report_id')
        assert.deepEqual([record.native_result.status, record.native_result.reason_code],
          [fixture.native_status, fixture.native_reason])
        assert.equal(record.claim.status, expected === 'ESTABLISHED' ? 'established' : 'not_established')
        if (expected !== 'ESTABLISHED') {
          assert.ok(r.reasons.some((x: string) => x.endsWith(`:native_contradicted:${fixture.native_reason}`)), JSON.stringify(r.reasons))
        }
      } finally { await e.close() }
    })
  }
}

test('the two reports of one operation get different results in both cases', () => {
  for (const name of ['LATE', 'LATE-CONFLICT']) {
    const statuses = caseOf(name).results.map((r: any) => r.native_status)
    assert.equal(new Set(statuses).size, 2, name)
  }
})

const REFUSALS: [string, () => Uint8Array, string][] = [
  ['no request and two eligible reports', () => check(undefined, resultsOf(caseOf('LATE'))), 'report_selection_ambiguous'],
  ['a report that was not supplied', () => check({ operation_id: caseOf('LATE').operation_id, report_id: 'report-9' }, resultsOf(caseOf('LATE'))), 'selected_report_absent'],
  ['the right report id with another digest', () => check({ report_id: 'report-2', report_digest: 'sha256:' + '0'.repeat(64) }, resultsOf(caseOf('LATE'))), 'selected_report_absent'],
  ['another operation', () => check({ operation_id: 'op-other', report_id: 'report-2' }, resultsOf(caseOf('LATE'))), 'selected_report_absent'],
  ['reports of two operations', () => check({ report_id: 'report-2' }, [...resultsOf(caseOf('LATE')), ...resultsOf(caseOf('LATE-CONFLICT'))]), 'reports_for_different_operations'],
  ['only a result under an unpinned key', () => check({ report_id: 'report-1' }, [caseOf('LATE').untrusted_result_b64]), 'selected_report_absent'],
  ['a tampered result', () => {
    const c = caseOf('LATE')
    const outer = JSON.parse(Buffer.from(c.results[1].evidence_b64, 'base64').toString('utf8'))
    const doc = JSON.parse(Buffer.from(outer.result_b64, 'base64').toString('utf8'))
    doc.subject.report_id = 'report-1'  // relabel report-2's ESTABLISHED as report-1's
    outer.result_b64 = Buffer.from(JSON.stringify(doc)).toString('base64')
    return check({ report_id: 'report-1' }, [Buffer.from(JSON.stringify(outer)).toString('base64')])
  }, 'selected_report_absent'],
  ['no evidence', () => new Uint8Array(), 'evidence_missing'],
]
for (const [what, evidence, reason] of REFUSALS) {
  test(`refused before dispatch: ${what}`, async () => {
    const e = await env()
    try {
      const { r, record } = await run(e, evidence())
      assert.equal(r.status, 'refused', JSON.stringify(r))
      assert.ok(r.reasons.some((x: string) => x.endsWith(`#${CLAIM}:${reason}`)), JSON.stringify(r.reasons))
      assert.equal(e.provider.requests, 0)
      assert.equal(record.claim.reason, reason)
    } finally { await e.close() }
  })
}

test('a relabelled result fails its signature and is recorded as unverified', async () => {
  const e = await env()
  try {
    const c = caseOf('LATE')
    const outer = JSON.parse(Buffer.from(c.results[1].evidence_b64, 'base64').toString('utf8'))
    const doc = JSON.parse(Buffer.from(outer.result_b64, 'base64').toString('utf8'))
    doc.subject.report_id = 'report-1'
    outer.result_b64 = Buffer.from(JSON.stringify(doc)).toString('base64')
    const { record } = await run(e, check({ report_id: 'report-1' }, [Buffer.from(JSON.stringify(outer)).toString('base64')]))
    assert.deepEqual(record.unverified, ['signature_invalid'])
  } finally { await e.close() }
})

test('a single eligible report needs no request, and the rule says so', async () => {
  const e = await env()
  try {
    const c = caseOf('LATE')
    const { r, record } = await run(e, check(undefined, [c.results[1].evidence_b64]))
    assert.equal(r.status, 'provider_confirmed')
    assert.equal(record.selected.adapter_selection_rule, 'single_available')
  } finally { await e.close() }
})

test('a result for another native claim is not relied on', async () => {
  const e = await env({ nativeClaim: 'another_claim' })
  try {
    const c = caseOf('LATE')
    const { r, record } = await run(e, check({ report_id: 'report-2' }, resultsOf(c)))
    assert.equal(r.status, 'refused')
    assert.deepEqual(record.unverified, ['native_claim_differs', 'native_claim_differs'])
  } finally { await e.close() }
})

test('a new action gated on an earlier report, beside REMORA authorization', async () => {
  const action = ACTIONS.cases.find((c: any) => c.name === 'valid')
  const c = caseOf('LATE')
  for (const [reportId, admitted] of [['report-2', true], ['report-1', false]] as const) {
    const e = await env({ gated: true, now: action.now })
    try {
      const req = structuredClone(action.request)
      req.evidence = { [AUTH]: new Uint8Array(Buffer.from(action.evidence_b64, 'base64')),
                       [REPORT]: check({ operation_id: c.operation_id, report_id: reportId }, resultsOf(c)) }
      const r = await e.rt.submit(req)
      assert.equal(r.status, admitted ? 'provider_confirmed' : 'refused', JSON.stringify(r))
    } finally { await e.close() }
  }
})

test('the component exports one claim, and never a whole-operation verdict', () => {
  const manifest = JSON.parse(readFileSync(join(COMPONENT, 'manifest.json'), 'utf8'))
  assert.deepEqual(manifest.claims.map((c: any) => c.id), [CLAIM])
  assert.deepEqual(manifest.privileges_requested, [])
  assert.deepEqual(manifest.data_destinations, [])
})

// ---------------------------------------------------------------------------------------------
// Held-out cases, written after the component shipped (#793). They cover the selection and
// verification paths the LATE and LATE-CONFLICT fixtures do not reach: one report id naming two
// digests, selection by digest alone, every result-level refusal reason, a byte-by-byte signature
// sweep, and order/subset independence. Results are signed here with the published test seed, so
// nothing below says anything about a deployment.
// ---------------------------------------------------------------------------------------------
const adapterMod = await import(pathToFileURL(join(COMPONENT, 'adapter.ts')).href)
const SEED = Buffer.from(REPORTS.test_keys.result_signing_seed_hex, 'hex')
const PUB = Buffer.from(REPORTS.test_keys.result_public_key_hex, 'hex')
const KID = 'ed25519-' + createHash('sha256').update(PUB).digest('hex')
const DOMAIN = 'REMORA/FEDERATION-RESULT/v1'
const signingKey = createPrivateKey({ format: 'jwk',
  key: { kty: 'OKP', crv: 'Ed25519', d: SEED.toString('base64url'), x: PUB.toString('base64url') } })

const late = () => caseOf('LATE')
const outerOf = (blob: string) => JSON.parse(Buffer.from(blob, 'base64').toString('utf8'))
const docOf = (blob: string) => JSON.parse(Buffer.from(outerOf(blob).result_b64, 'base64').toString('utf8'))
const fixtureDoc = (reportId: string) => docOf(late().results.find((r: any) => r.report_id === reportId).evidence_b64)

/** Sign a result document the way REMORA does, with optional edits to the envelope. */
function seal(doc: unknown, envelope: Record<string, unknown> = {}, sig: Record<string, unknown> = {}): string {
  const payload = Buffer.from(JSON.stringify(doc))
  const preimage = Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload])
  const signature = signBytes(null, preimage, signingKey).toString('base64')
  const outer = { format: 'remora-federation-result-evidence-v1', result_b64: payload.toString('base64'),
    signature: { algorithm: 'Ed25519', domain: DOMAIN, kid: KID, signature, ...sig }, ...envelope }
  return Buffer.from(JSON.stringify(outer)).toString('base64')
}

/** A result document for one report, derived from the fixture's report-2 (ESTABLISHED) document. */
function resultDoc(o: { report_id?: string; digest?: string; operation_id?: string; status?: string;
                        reason?: string; edit?: (d: any) => void } = {}) {
  const d = structuredClone(fixtureDoc('report-2'))
  if (o.report_id) d.subject.report_id = o.report_id
  if (o.operation_id) d.subject.operation_id = o.operation_id
  if (o.digest) { d.subject.report_digest = o.digest; d.evidence_selection.selected_digest = o.digest }
  if (o.status) d.native_result.status = o.status
  if (o.reason) d.native_result.reason_code = o.reason
  if (o.edit) o.edit(d)
  return d
}
const DIGEST_B = 'sha256:' + 'b'.repeat(64)

/** The component on its own, outside the runtime, for sweeps that would be slow with a database each. */
function direct(config: Record<string, unknown> = {}) {
  return adapterMod.createAdapter({ config: { trusted_keys: [PUB.toString('hex')], native_claim: REPORTS.native_claim, ...config },
    secrets: {}, fetch: globalThis.fetch })
}
async function checkDirect(a: any, evidence: Uint8Array) {
  const out = await a.check({ operation_id: opId(), workflow: 'refund', action: { tool: 'refund', args: { ...REFUND } },
    evidence, now: new Date().toISOString() })
  return { out, record: JSON.parse(Buffer.from(out.evidence).toString('utf8')) }
}

test('held-out: the fixtures are signed with the published test seed, and Ed25519 reproduces them exactly', () => {
  for (const c of REPORTS.cases) {
    for (const r of c.results) {
      const outer = outerOf(r.evidence_b64)
      assert.equal(outer.signature.kid, KID, `${c.name} ${r.report_id}`)
      const resigned = outerOf(seal(JSON.parse(Buffer.from(outer.result_b64, 'base64').toString('utf8'))))
      assert.equal(resigned.result_b64, outer.result_b64)
      assert.equal(resigned.signature.signature, outer.signature.signature)
    }
    assert.notEqual(outerOf(c.untrusted_result_b64).signature.kid, KID)
  }
})

const HELD_OUT: [string, () => Uint8Array, string, string | undefined][] = [
  // [what, evidence, expected reason, expected adapter selection rule]
  ['one report id naming two digests, requested by id',
    () => check({ report_id: 'report-2' }, [seal(resultDoc()), seal(resultDoc({ digest: DIGEST_B }))]), 'report_id_not_unique', undefined],
  ['one report id naming two digests, requested by digest',
    () => check({ report_digest: DIGEST_B }, [seal(resultDoc()), seal(resultDoc({ digest: DIGEST_B }))]), '', 'explicit_digest'],
  ['requested by digest alone, two reports of one operation',
    () => check({ report_digest: fixtureDoc('report-2').subject.report_digest }, resultsOf(late())), '', 'explicit_digest'],
  ['requested by digest with the other operation id',
    () => check({ operation_id: 'op-other', report_digest: fixtureDoc('report-2').subject.report_digest }, resultsOf(late())), 'selected_report_absent', undefined],
  ['requested by digest and a report id it does not belong to',
    () => check({ report_id: 'report-1', report_digest: fixtureDoc('report-2').subject.report_digest }, resultsOf(late())), 'selected_report_absent', undefined],
  ['no request and nothing verified',
    () => check(undefined, [late().untrusted_result_b64]), 'no_verified_result', undefined],
  ['no request and an empty result list', () => check(undefined, []), 'no_verified_result', undefined],
  ['the same signed result supplied twice is one report',
    () => check({ report_id: 'report-2' }, [seal(resultDoc()), seal(resultDoc())]), '', 'explicit_report_id'],
  // Found by the maintainer's own mutation check of this suite after #793: before the repair the first
  // of two differing signed results for one report decided the verdict.
  ['two differing signed results for one report, established first',
    () => check({ report_id: 'report-2' }, [seal(resultDoc()), seal(resultDoc({ status: 'CONTRADICTED', reason: 'later_revision' }))]), 'conflicting_results_for_report', undefined],
  ['two differing signed results for one report, contradicted first',
    () => check({ report_id: 'report-2' }, [seal(resultDoc({ status: 'CONTRADICTED', reason: 'later_revision' })), seal(resultDoc())]), 'conflicting_results_for_report', undefined],
  ['two differing signed results for one report, differing only in the selection count',
    () => check({ report_id: 'report-2' }, [seal(resultDoc()), seal(resultDoc({ edit: d => { d.evidence_selection.eligible = 3 } }))]), 'conflicting_results_for_report', undefined],
  ['two differing signed results for one report, no request',
    () => check(undefined, [seal(resultDoc()), seal(resultDoc({ status: 'CONTRADICTED', reason: 'later_revision' }))]), 'report_selection_ambiguous', undefined],
  ['a report of another kind (execution_attempt) is still report-specific',
    () => check({ report_id: 'attempt-1' }, [seal(resultDoc({ report_id: 'attempt-1', edit: d => { d.subject.kind = 'execution_attempt' } }))]), '', 'explicit_report_id'],
]
for (const [what, evidence, reason, rule] of HELD_OUT) {
  test(`held-out selection: ${what}`, async () => {
    // First the component alone, so the case discriminates on behaviour and not on the artifact pin.
    const alone = await checkDirect(direct(), evidence())
    assert.deepEqual([alone.record.claim.status, alone.record.claim.reason, alone.record.selected?.adapter_selection_rule],
      reason ? ['not_established', reason, undefined] : ['established', undefined, rule])
    // Then the same submission through the unmodified runtime.
    const e = await env()
    try {
      const { r, record } = await run(e, evidence())
      if (reason) {
        assert.equal(r.status, 'refused', JSON.stringify(r))
        assert.ok(r.reasons.some((x: string) => x.endsWith(`#${CLAIM}:${reason}`)), JSON.stringify(r.reasons))
        assert.equal(record.claim.reason, reason)
        assert.equal(record.selected, undefined)
        assert.equal(e.provider.requests, 0)
      } else {
        assert.equal(r.status, 'provider_confirmed', JSON.stringify(r))
        assert.equal(record.claim.status, 'established')
        assert.equal(record.selected.adapter_selection_rule, rule)
        assert.equal(e.provider.requests, 1)
      }
    } finally { await e.close() }
  })
}

const MALFORMED: [string, Uint8Array, string, string][] = [
  // [what, evidence, claim status, reason]
  ['not JSON', new Uint8Array(Buffer.from('{"format":')), 'failed', 'evidence_malformed'],
  ['another format', new Uint8Array(Buffer.from(JSON.stringify({ format: 'something-else-v1', results: [] }))), 'unsupported', 'evidence_format_unknown'],
  ['results missing', new Uint8Array(Buffer.from(JSON.stringify({ format: 'remora-report-check-v1' }))), 'failed', 'results_missing'],
  ['results not a list', new Uint8Array(Buffer.from(JSON.stringify({ format: 'remora-report-check-v1', results: 'x' }))), 'failed', 'results_missing'],
]
for (const [what, evidence, status, reason] of MALFORMED) {
  test(`held-out input: ${what} is refused before dispatch as ${status}`, async () => {
    const e = await env()
    try {
      const { r, record } = await run(e, evidence)
      assert.equal(r.status, 'refused', JSON.stringify(r))
      assert.ok(r.reasons.some((x: string) => x.endsWith(`#${CLAIM}:${reason}`)), JSON.stringify(r.reasons))
      assert.deepEqual([record.claim.status, record.claim.reason], [status, reason])
      assert.equal(e.provider.requests, 0)
    } finally { await e.close() }
  })
}

// Every reason a single result can be set aside for, each recorded under `unverified` and never
// treated as a report. The adapter checks envelope, signature, then document, in that order.
const UNVERIFIED: [string, () => string, string][] = [
  ['envelope with another format', () => seal(resultDoc(), { format: 'remora-federation-result-evidence-v2' }), 'result_format_unknown'],
  ['envelope that is not JSON', () => Buffer.from('not json').toString('base64'), 'result_malformed'],
  ['envelope that is not base64 JSON', () => 'AAAA', 'result_malformed'],
  ['another signature algorithm', () => seal(resultDoc(), {}, { algorithm: 'RSA-PSS' }), 'algorithm_unsupported'],
  ['another signing domain', () => seal(resultDoc(), {}, { domain: 'REMORA/FEDERATION-RESULT/v2' }), 'domain_mismatch'],
  ['a kid the customer did not pin', () => seal(resultDoc(), {}, { kid: 'ed25519-' + 'f'.repeat(64) }), 'unknown_kid'],
  ['a 63-byte signature', () => seal(resultDoc(), {}, { signature: Buffer.alloc(63).toString('base64') }), 'signature_invalid'],
  ['a signature over the wrong domain', () => {
    const payload = Buffer.from(JSON.stringify(resultDoc()))
    const bad = signBytes(null, Buffer.concat([Buffer.from('OTHER/v1', 'ascii'), Buffer.from([0]), payload]), signingKey)
    return seal(resultDoc(), {}, { signature: bad.toString('base64') })
  }, 'signature_invalid'],
  ['a signed payload that is not JSON', () => {
    const payload = Buffer.from('{"schema_version":')
    const sig = signBytes(null, Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload]), signingKey)
    return Buffer.from(JSON.stringify({ format: 'remora-federation-result-evidence-v1', result_b64: payload.toString('base64'),
      signature: { algorithm: 'Ed25519', domain: DOMAIN, kid: KID, signature: sig.toString('base64') } })).toString('base64')
  }, 'result_malformed'],
  ['another result schema', () => seal(resultDoc({ edit: d => { d.schema_version = 'remora-federation-result-v2' } })), 'result_schema_unknown'],
  ['a subject that is not a report (kind)', () => seal(resultDoc({ edit: d => { d.subject.kind = 'operation' } })), 'subject_not_report_specific'],
  ['a subject without a report id', () => seal(resultDoc({ edit: d => { delete d.subject.report_id } })), 'subject_not_report_specific'],
  ['a subject without a report digest', () => seal(resultDoc({ edit: d => { delete d.subject.report_digest } })), 'subject_not_report_specific'],
  ['a selection that names another digest than the subject', () => seal(resultDoc({ edit: d => { d.evidence_selection.selected_digest = DIGEST_B } })), 'selection_differs_from_subject'],
  ['no selection at all', () => seal(resultDoc({ edit: d => { delete d.evidence_selection } })), 'selection_differs_from_subject'],
  ['a result for another native claim', () => seal(resultDoc({ edit: d => { d.native_claim = 'another_claim' } })), 'native_claim_differs'],
]
for (const [what, blob, reason] of UNVERIFIED) {
  test(`held-out verification: ${what} is set aside as ${reason}`, async () => {
    const { out, record } = await checkDirect(direct(), check({ report_id: 'report-2' }, [blob()]))
    assert.deepEqual(record.unverified, [reason])
    assert.equal(record.eligible, 0)
    assert.deepEqual([record.claim.status, record.claim.reason], ['not_established', 'selected_report_absent'])
    assert.equal(out.claims.length, 1)
  })
}

test('held-out: a native result in another vocabulary is unsupported, with the record kept', async () => {
  const { record } = await checkDirect(direct(), check({ report_id: 'report-2' },
    [seal(resultDoc({ edit: d => { d.native_result.vocabulary = 'other-vocabulary-v9' } }))]))
  assert.deepEqual([record.claim.status, record.claim.reason], ['unsupported', 'native_vocabulary_unsupported'])
  assert.equal(record.selected.subject.report_id, 'report-2')
  assert.equal(record.native_result.vocabulary, 'other-vocabulary-v9')
})

test('held-out: every native status other than ESTABLISHED is not established, with the reason kept', async () => {
  for (const [status, reason] of [['CONTRADICTED', 'r1'], ['NOT_ESTABLISHED', 'r2'], ['UNKNOWN', 'r3'], ['established', 'r4']]) {
    const { record } = await checkDirect(direct(), check({ report_id: 'report-2' }, [seal(resultDoc({ status, reason }))]))
    assert.deepEqual([record.claim.status, record.claim.reason], ['not_established', `native_${status.toLowerCase()}:${reason}`], status)
    assert.equal(record.native_result.status, status)
  }
})

test('held-out sweep: flipping any bit of the signed payload or any byte of the signature invalidates the result', async () => {
  const a = direct()
  const good = outerOf(seal(resultDoc()))
  const payload = Buffer.from(good.result_b64, 'base64')
  const signature = Buffer.from(good.signature.signature, 'base64')
  assert.equal(signature.length, 64)
  const mutants: [string, string][] = []
  for (let i = 0; i < payload.length; i++) {
    for (const bit of [1, 128]) {
      const p = Buffer.from(payload); p[i] ^= bit
      mutants.push([`payload[${i}]^${bit}`, Buffer.from(JSON.stringify({ ...good, result_b64: p.toString('base64') })).toString('base64')])
    }
  }
  for (let i = 0; i < 64; i++) {
    const s = Buffer.from(signature); s[i] ^= 1
    mutants.push([`signature[${i}]^1`, Buffer.from(JSON.stringify({ ...good, signature: { ...good.signature, signature: s.toString('base64') } })).toString('base64')])
  }
  assert.ok(mutants.length > 2 * 400 + 64, `payload is ${payload.length} bytes`)
  // Control: the unmutated result is relied on.
  const ok = await checkDirect(a, check({ report_id: 'report-2' }, [Buffer.from(JSON.stringify(good)).toString('base64')]))
  assert.equal(ok.record.claim.status, 'established')
  const survivors: string[] = []
  for (const [name, blob] of mutants) {
    const { record } = await checkDirect(a, check({ report_id: 'report-2' }, [blob]))
    if (!(record.eligible === 0 && record.unverified.length === 1 && record.unverified[0] === 'signature_invalid'
          && record.claim.status === 'not_established')) survivors.push(`${name}:${record.unverified}`)
  }
  assert.deepEqual(survivors, [], `${survivors.length} of ${mutants.length} mutants survived`)
})

test('held-out property: with no request, one eligible report is single_available and more than one is ambiguous, in every order', async () => {
  const a = direct()
  const r1 = late().results[0].evidence_b64, r2 = late().results[1].evidence_b64, u = late().untrusted_result_b64
  const perms = (xs: string[]): string[][] => xs.length <= 1 ? [xs]
    : xs.flatMap((x, i) => perms([...xs.slice(0, i), ...xs.slice(i + 1)]).map(p => [x, ...p]))
  const subsets = (xs: string[]): string[][] => xs.reduce<string[][]>((acc, x) => acc.concat(acc.map(s => [...s, x])), [[]])
  let seen = 0
  for (const subset of subsets([r1, r2, u])) {
    for (const order of perms(subset)) {
      const eligible = order.filter(x => x !== u).length
      const { record } = await checkDirect(a, check(undefined, order))
      seen++
      assert.equal(record.eligible, eligible, JSON.stringify(order.map(x => x === u ? 'u' : x === r1 ? 'r1' : 'r2')))
      assert.deepEqual(record.unverified, order.includes(u) ? ['unknown_kid'] : [])
      if (eligible === 0) assert.equal(record.claim.reason, 'no_verified_result')
      else if (eligible === 1) {
        assert.equal(record.selected.adapter_selection_rule, 'single_available')
        const only = order.includes(r1) ? 'report-1' : 'report-2'
        assert.equal(record.selected.subject.report_id, only)
        assert.equal(record.claim.status, only === 'report-2' ? 'established' : 'not_established')
      } else {
        assert.equal(record.claim.reason, 'report_selection_ambiguous')
        assert.equal(record.selected, undefined)
      }
    }
  }
  assert.equal(seen, 16)  // 1 + 3 + 6 + 6 orderings over the 8 subsets
})

test('held-out property: an explicit request gives the same record in every order, and key order never changes the evidence bytes', async () => {
  const a = direct()
  const r1 = late().results[0].evidence_b64, r2 = late().results[1].evidence_b64, u = late().untrusted_result_b64
  const strip = (rec: any) => { const { submitted_evidence_digest, unverified, ...rest } = rec; return { ...rest, unverified: [...unverified].sort() } }
  const orders = [[r1, r2, u], [r2, r1, u], [u, r2, r1], [r1, u, r2], [r2, u, r1], [u, r1, r2]]
  for (const reportId of ['report-1', 'report-2']) {
    const records = []
    for (const order of orders) {
      const { record } = await checkDirect(a, check({ report_id: reportId, operation_id: late().operation_id }, order))
      records.push(strip(record))
    }
    for (const rec of records) assert.deepEqual(rec, records[0], reportId)
    assert.equal(records[0].selected.subject.report_id, reportId)
  }
  // The output is canonical JSON: the request's key order is not visible in the evidence bytes.
  const asGiven = (requested: string) => new Uint8Array(Buffer.from(`{"format":"remora-report-check-v1","requested":${requested},"results":${JSON.stringify([r2])}}`))
  const x = await checkDirect(a, asGiven('{"report_id":"report-2","operation_id":"op-late"}'))
  const y = await checkDirect(a, asGiven('{"operation_id":"op-late","report_id":"report-2"}'))
  assert.notEqual(x.record.submitted_evidence_digest, y.record.submitted_evidence_digest)
  assert.deepEqual(strip(x.record), strip(y.record))
  assert.equal(Buffer.from(x.out.evidence).toString('utf8').replace(x.record.submitted_evidence_digest, ''),
               Buffer.from(y.out.evidence).toString('utf8').replace(y.record.submitted_evidence_digest, ''))
})

test('held-out: the record names what was submitted, and the claim never carries a valid_until', async () => {
  const evidence = check({ report_id: 'report-2' }, [late().results[1].evidence_b64])
  const { out, record } = await checkDirect(direct(), evidence)
  assert.equal(record.submitted_evidence_digest, 'sha256:' + createHash('sha256').update(evidence).digest('hex'))
  assert.equal(record.format, 'remora-report-check-result-v1')
  assert.equal(record.native_claim, REPORTS.native_claim)
  assert.equal(out.valid_until, undefined)
})
