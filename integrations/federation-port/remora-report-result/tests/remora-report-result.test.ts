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
import { randomBytes } from 'node:crypto'

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
