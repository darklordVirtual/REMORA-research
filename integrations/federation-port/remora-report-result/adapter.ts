// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// REMORA report-result component for federation-port/v0: gate an action on REMORA's native result
// for one explicitly requested report of an earlier operation.
//
// A claim result is about one report. Several reports of one operation are not interchangeable, so
// this component never picks one: the caller names the requested report in its input, the
// component selects exactly that report among the signed results it was given, and refuses when
// the request is missing and more than one report is eligible, or when the results it was given
// make two different signed statements about the selected report. Its output evidence keeps the
// requested report, the selected report's identity and digest, the selection rule, and REMORA's
// native result and reason next to the claim status it reported.
//
// V0 checks run before dispatch, so this gates a new action on the result of an earlier one. It
// cannot see the result of the action being dispatched (aeoess, #177).
//
// It verifies REMORA result evidence (remora-federation-result-evidence-v1, Ed25519 in
// REMORA/FEDERATION-RESULT/v1) against keys the customer pins. No secret, no network.
import { createHash, createPublicKey, verify as verifySignature } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { Adapter, AdapterContext, CheckInput, CheckOutput, ClaimResult, Manifest } from '../../src/contract/types.ts'

const manifest: Manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))

export const CLAIM = 'remora.report_result'
const CHECK_FORMAT = 'remora-report-check-v1'
const RESULT_FORMAT = 'remora-federation-result-evidence-v1'
const RESULT_SCHEMA = 'remora-federation-result-v1'
const DOMAIN = 'REMORA/FEDERATION-RESULT/v1'
const OBSERVATION_KINDS = new Set(['operation_report', 'execution_attempt', 'effect_observation'])

/** Sorted-key JSON for the output evidence, so its digest does not depend on key order. */
function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  const obj = value as Record<string, unknown>
  return '{' + Object.keys(obj).filter(k => obj[k] !== undefined).sort()
    .map(k => JSON.stringify(k) + ':' + canonical(obj[k])).join(',') + '}'
}
const sha256 = (b: Buffer | string) => 'sha256:' + createHash('sha256').update(b).digest('hex')
const kidOf = (raw: Buffer) => 'ed25519-' + createHash('sha256').update(raw).digest('hex')

interface Requested { operation_id?: unknown; report_id?: unknown; report_digest?: unknown }
interface Verified { subject: Record<string, unknown>; selection: unknown; native: Record<string, unknown>; digest: string }

export function createAdapter(ctx: AdapterContext): Adapter {
  const keys = new Map<string, ReturnType<typeof createPublicKey>>()
  for (const hex of (ctx.config.trusted_keys as string[] | undefined) ?? []) {
    const raw = Buffer.from(hex, 'hex')
    if (raw.length !== 32) throw new Error('trusted_keys: Ed25519 public keys are 32 bytes of hex')
    keys.set(kidOf(raw), createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: raw.toString('base64url') }, format: 'jwk' }))
  }
  const nativeClaim = String(ctx.config.native_claim ?? '')
  if (!nativeClaim) throw new Error('config.native_claim names the REMORA native claim this component gates on')

  /** The signed result document, or the reason it is not one this component can rely on. */
  function verifyResult(blob: unknown): Verified | string {
    let outer: any, payload: Buffer
    try {
      outer = JSON.parse(Buffer.from(String(blob), 'base64').toString('utf8'))
      if (outer.format !== RESULT_FORMAT) return 'result_format_unknown'
      payload = Buffer.from(String(outer.result_b64), 'base64')
    } catch { return 'result_malformed' }
    const sig = outer.signature ?? {}
    const key = keys.get(String(sig.kid))
    if (sig.algorithm !== 'Ed25519') return 'algorithm_unsupported'
    if (sig.domain !== DOMAIN) return 'domain_mismatch'
    if (!key) return 'unknown_kid'
    const raw = Buffer.from(String(sig.signature), 'base64')
    const preimage = Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload])
    if (raw.length !== 64 || !verifySignature(null, preimage, key, raw)) return 'signature_invalid'
    let doc: any
    try { doc = JSON.parse(payload.toString('utf8')) } catch { return 'result_malformed' }
    if (doc.schema_version !== RESULT_SCHEMA) return 'result_schema_unknown'
    const subject = doc.subject ?? {}
    if (!OBSERVATION_KINDS.has(subject.kind) || !subject.report_id || !subject.report_digest) return 'subject_not_report_specific'
    if (doc.evidence_selection?.selected_digest !== subject.report_digest) return 'selection_differs_from_subject'
    if (doc.native_claim !== nativeClaim) return 'native_claim_differs'
    return { subject, selection: doc.evidence_selection, native: doc.native_result ?? {}, digest: sha256(payload) }
  }

  return {
    describe: () => manifest,
    async check(input: CheckInput): Promise<CheckOutput> {
      const submitted = input.evidence ?? new Uint8Array()
      const respond = (status: ClaimResult['status'], reason: string | undefined, record: Record<string, unknown>): CheckOutput => ({
        evidence: new Uint8Array(Buffer.from(canonical({
          format: 'remora-report-check-result-v1', native_claim: nativeClaim,
          submitted_evidence_digest: sha256(Buffer.from(submitted)),
          claim: { id: CLAIM, status, ...(reason ? { reason } : {}) }, ...record,
        }))),
        claims: [{ claim: CLAIM, status, ...(reason ? { reason } : {}) }],
      })
      if (submitted.byteLength === 0) return respond('not_established', 'evidence_missing', {})
      let check: any
      try { check = JSON.parse(Buffer.from(submitted).toString('utf8')) } catch { return respond('failed', 'evidence_malformed', {}) }
      if (check.format !== CHECK_FORMAT) return respond('unsupported', 'evidence_format_unknown', {})
      if (!Array.isArray(check.results)) return respond('failed', 'results_missing', {})
      const requested: Requested = check.requested ?? {}

      const eligible: Verified[] = [], unverified: string[] = []
      for (const blob of check.results) {
        const v = verifyResult(blob)
        if (typeof v === 'string') unverified.push(v); else eligible.push(v)
      }
      const base = { requested: check.requested ?? null, eligible: eligible.length, unverified }
      if (new Set(eligible.map(e => e.subject.operation_id)).size > 1) {
        return respond('not_established', 'reports_for_different_operations', base)
      }

      // Selection: exactly the requested report, never an implicit first, last or established one.
      let chosen: Verified[], rule: string
      if (requested.report_id !== undefined || requested.report_digest !== undefined) {
        chosen = eligible.filter(e =>
          (requested.operation_id === undefined || e.subject.operation_id === requested.operation_id)
          && (requested.report_id === undefined || e.subject.report_id === requested.report_id)
          && (requested.report_digest === undefined || e.subject.report_digest === requested.report_digest))
        rule = requested.report_id !== undefined ? 'explicit_report_id' : 'explicit_digest'
      } else if (eligible.length === 1) {
        chosen = eligible; rule = 'single_available'
      } else {
        return respond('not_established', eligible.length ? 'report_selection_ambiguous' : 'no_verified_result', base)
      }
      if (chosen.length === 0) return respond('not_established', 'selected_report_absent', base)
      if (new Set(chosen.map(c => c.subject.report_digest)).size > 1) {
        return respond('not_established', 'report_id_not_unique', base)
      }
      // Two signed statements about the same report that are not the same statement are not
      // resolved here: the order they were supplied in must never decide the verdict.
      if (new Set(chosen.map(c => c.digest)).size > 1) {
        return respond('not_established', 'conflicting_results_for_report', base)
      }
      const selected = chosen[0]
      const native = selected.native
      const record = { ...base,
        selected: { subject: selected.subject, adapter_selection_rule: rule,
                    remora_selection: selected.selection, result_digest: selected.digest },
        native_result: native }
      if (native.vocabulary !== 'remora-claim-result-v1') return respond('unsupported', 'native_vocabulary_unsupported', record)
      if (native.status === 'ESTABLISHED') return respond('established', undefined, record)
      return respond('not_established', `native_${String(native.status).toLowerCase()}:${String(native.reason_code)}`, record)
    },
  }
}
