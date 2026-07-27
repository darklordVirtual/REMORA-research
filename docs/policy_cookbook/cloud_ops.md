# Cloud Operations Policy Cookbook

Cloud agents can create cost, exposure, persistence, and availability risk.
REMORA should treat production changes as governed actions, not ordinary text
generation.

| Action | Environment | Risk | Recommended outcome | Required evidence |
|--------|-------------|------|---------------------|-------------------|
| Read metrics | any | low | ACCEPT | none |
| List resources | any | low | ACCEPT | none |
| Restart one dev service | dev | medium | VERIFY | service owner or ticket |
| Create public endpoint | production | high | ESCALATE | security review, owner approval |
| Change IAM role | production | critical | ESCALATE | access review, approval ticket |
| Rotate secret | production | high | VERIFY | rotation plan, rollback note |
| Terraform plan | staging | medium | VERIFY | plan artifact |
| Terraform apply | production | critical | ESCALATE | change window, approval, rollback |
| Terraform destroy | any production | critical | ESCALATE | explicit human approval |

## Practical default

```yaml
cloud_ops:
  public_exposure:
    default_gate: ESCALATE
    required_evidence:
      - security_review
      - service_owner_approval
      - rollback_plan

  read_only_observability:
    default_gate: ACCEPT
    required_evidence: []
```

