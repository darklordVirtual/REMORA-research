// Author: Stian Skogbrott
// SPDX-License-Identifier: BUSL-1.1
//
// REMORA authorization-evidence component for federation-port/v0 (Mode A: portable verifier).
//
// It receives REMORA evidence bytes (remora-federation-evidence-v1), verifies the Ed25519
// signature in REMORA/FEDERATION-ACTION/v1 against a key the customer pins, and compares the
// signed federation-port/v0 projection with the action the runtime will dispatch. It holds no
// secret, reaches no network and does not run REMORA. It reports only the three claims REMORA's
// projection map exports for V0 (artifacts/interop/federation-port-v0/projection-map.yaml):
// never full exact-call binding, principal binding, custody isolation or an effect.
import { createHash, createPublicKey, verify as verifySignature } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { Adapter, AdapterContext, CheckInput, CheckOutput, ClaimResult, Manifest } from '../../src/contract/types.ts'

const manifest: Manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url), 'utf8'))

export const INTEGRITY = 'remora.authorization_integrity'
export const BOUND = 'remora.port_v0.bound_action'
export const UNEXPIRED = 'remora.authorization_unexpired'
const FORMAT = 'remora-federation-evidence-v1'
const DOMAIN = 'REMORA/FEDERATION-ACTION/v1'
const ENVELOPE = 'remora-federation-action-v1'
const CANONICALIZATION = 'remora-canonical-json-v1'
const EXACT_UTC_MS = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/

/** Sorted-key JSON, the comparison form for values as this runtime carries them. */
function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']'
  const obj = value as Record<string, unknown>
  return '{' + Object.keys(obj).filter(k => obj[k] !== undefined).sort()
    .map(k => JSON.stringify(k) + ':' + canonical(obj[k])).join(',') + '}'
}

/** REMORA key id: "ed25519-" + SHA-256 of the raw public key, so a label cannot name another key. */
const kidOf = (raw: Buffer) => 'ed25519-' + createHash('sha256').update(raw).digest('hex')

const instant = (v: unknown): number | undefined => {
  if (typeof v !== 'string' || !EXACT_UTC_MS.test(v)) return undefined
  const ms = Date.parse(v)
  return Number.isNaN(ms) || new Date(ms).toISOString() !== v ? undefined : ms
}

interface Port {
  transport: string; component: string; workflow: string; operation_id: string
  tenant: string | null; approval_id: string; valid_until: string; action: unknown
}

export function createAdapter(ctx: AdapterContext): Adapter {
  const keys = new Map<string, ReturnType<typeof createPublicKey>>()
  for (const hex of (ctx.config.trusted_keys as string[] | undefined) ?? []) {
    const raw = Buffer.from(hex, 'hex')
    if (raw.length !== 32) throw new Error('trusted_keys: Ed25519 public keys are 32 bytes of hex')
    keys.set(kidOf(raw), createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: raw.toString('base64url') }, format: 'jwk' }))
  }
  const all = (status: ClaimResult['status'], reason: string): ClaimResult[] =>
    [INTEGRITY, BOUND, UNEXPIRED].map(claim => ({ claim, status, reason }))

  return {
    describe: () => manifest,
    async check(input: CheckInput): Promise<CheckOutput> {
      const evidence = input.evidence ?? new Uint8Array()
      if (evidence.byteLength === 0) return { evidence, claims: all('not_established', 'evidence_missing') }
      let payload: Buffer, signature: { algorithm?: string; domain?: string; kid?: string; signature?: string }
      try {
        const outer = JSON.parse(Buffer.from(evidence).toString('utf8'))
        if (outer.format !== FORMAT) return { evidence, claims: all('unsupported', 'evidence_format_unknown') }
        payload = Buffer.from(String(outer.envelope_b64), 'base64')
        signature = outer.signature ?? {}
      } catch {
        return { evidence, claims: all('failed', 'evidence_malformed') }
      }
      // Integrity: the signature over domain || 0x00 || envelope bytes, under a pinned key.
      const key = keys.get(String(signature.kid))
      let integrity: string | null = null
      if (signature.algorithm !== 'Ed25519') integrity = 'algorithm_unsupported'
      else if (signature.domain !== DOMAIN) integrity = 'domain_mismatch'
      else if (!key) integrity = 'unknown_kid'
      else {
        const preimage = Buffer.concat([Buffer.from(DOMAIN, 'ascii'), Buffer.from([0]), payload])
        const sig = Buffer.from(String(signature.signature), 'base64')
        if (sig.length !== 64 || !verifySignature(null, preimage, key, sig)) integrity = 'signature_invalid'
      }
      if (integrity) {
        return { evidence, claims: [{ claim: INTEGRITY, status: 'not_established', reason: integrity },
          { claim: BOUND, status: 'not_established', reason: 'integrity_not_established' },
          { claim: UNEXPIRED, status: 'not_established', reason: 'integrity_not_established' }] }
      }
      let envelope: any
      try { envelope = JSON.parse(payload.toString('utf8')) } catch { return { evidence, claims: all('failed', 'envelope_malformed') } }
      if (envelope.schema_version !== ENVELOPE) return { evidence, claims: all('unsupported', 'envelope_version_unknown') }
      if (envelope.action?.canonicalization !== CANONICALIZATION) return { evidence, claims: all('failed', 'canonicalization_mismatch') }
      const port = envelope.transport_projection as Port | undefined
      if (!port || port.transport !== 'federation-port/v0' || port.component !== manifest.id) {
        return { evidence, claims: [{ claim: INTEGRITY, status: 'established' },
          { claim: BOUND, status: 'not_established', reason: 'evidence_not_addressed_to_this_component' },
          { claim: UNEXPIRED, status: 'not_established', reason: 'evidence_not_addressed_to_this_component' }] }
      }

      // Bound action: the dimensions V0 carries, and only those.
      const mismatch =
        port.workflow !== input.workflow ? 'workflow_differs'
        : port.operation_id !== input.operation_id ? 'operation_id_differs'
        : (port.tenant ?? undefined) !== (input.tenant ?? undefined) ? 'tenant_differs'
        : port.approval_id !== input.approval_id ? 'approval_id_differs'
        : canonical(port.action) !== canonical(input.action) ? 'action_differs'
        : null
      const deadline = instant(port.valid_until)
      const now = instant(input.now)
      const unexpired: ClaimResult = deadline === undefined || now === undefined
        ? { claim: UNEXPIRED, status: 'failed', reason: 'instant_malformed' }
        : now <= deadline ? { claim: UNEXPIRED, status: 'established' }
        : { claim: UNEXPIRED, status: 'not_established', reason: 'authorization_expired' }
      return {
        evidence,
        claims: [{ claim: INTEGRITY, status: 'established' },
          mismatch ? { claim: BOUND, status: 'not_established', reason: mismatch } : { claim: BOUND, status: 'established' },
          unexpired],
        ...(deadline !== undefined ? { valid_until: port.valid_until } : {}),
      }
    },
  }
}
