---
id: kubernetes_admission_control_summary
title: Kubernetes Admission Control — Analogy for REMORA Action Gating
source: Kubernetes Admission Controllers Reference
source_url: https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/
version_or_accessed_date: Kubernetes v1.29+ (accessed 2024)
license_note: CC BY 4.0 — Creative Commons Attribution 4.0
intended_use: Architectural analogy, policy rule design for IaC/K8s scenarios
---

## 1. What this source says

Kubernetes Admission Controllers intercept API requests before objects are
persisted in etcd, allowing validation and mutation. Key controllers:

- **ValidatingAdmissionWebhook**: calls external webhook to validate requests
- **MutatingAdmissionWebhook**: can modify requests before persistence
- **PodSecurity**: enforces Pod Security Standards (privileged/baseline/restricted)
- **LimitRanger**: enforces resource limits
- **ResourceQuota**: enforces namespace quotas

Pod Security Standards define three profiles:
- **Privileged**: unrestricted (dangerous)
- **Baseline**: minimally restrictive
- **Restricted**: heavily restricted, hardened

## 2. Why it matters for REMORA

REMORA is the AI-action equivalent of Kubernetes admission control:
- Every agent tool call = API request to K8s API server
- DecisionEnvelope = Admission webhook response
- ACCEPT = admission allowed
- VERIFY = mutating webhook requires modification/approval
- ESCALATE = validating webhook rejects with escalation

This analogy helps engineers understand REMORA's position in a system.

## 3. Gate rules derived from this source

| Condition | Gate | Rationale |
|-----------|------|-----------|
| Privileged container in production namespace | ESCALATE | PodSecurity violation |
| hostNetwork=true or hostPID=true | ESCALATE | Host access = critical risk |
| Container with root user, no securityContext | VERIFY | Baseline violation |
| Resource limits missing in production | VERIFY | LimitRanger equivalent |
| namespace=kube-system targeted | ESCALATE | System namespace critical |
| No NetworkPolicy for new service | VERIFY | Missing isolation |

## 4. Evidence fields REMORA should require

- `pod_security_profile`: privileged/baseline/restricted
- `namespace_classification`: production/staging/dev
- `change_ticket`: IaC change management reference
- `rollback_plan`: defined for ESCALATE cases

## 5. Example scenarios

- kubectl apply privileged pod in prod → ESCALATE
- terraform plan (dry-run) for dev cluster → ACCEPT
- kubectl delete deployment in production → ESCALATE
- create NetworkPolicy in staging → VERIFY

## 6. Limitations / do-not-overclaim notes

REMORA does not integrate with the Kubernetes API server or webhook mechanism.
This is an architectural analogy and policy inspiration, not a K8s plugin.
