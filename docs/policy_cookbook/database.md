# Database Policy Cookbook

Database agents become risky when reads turn into exports, writes, migrations,
or destructive operations. Start in Shadow Mode, then enforce only well-scoped
rules.

| Action | Environment | Risk | Recommended outcome | Required evidence |
|--------|-------------|------|---------------------|-------------------|
| `SELECT count(*) FROM table` | dev/test | low | ACCEPT | none |
| `SELECT * FROM users LIMIT 10` | dev/test | low | ACCEPT | none |
| Export customer data | production | high | VERIFY | ticket, data purpose, approval |
| Update non-critical reference data | staging | medium | VERIFY | rollback plan |
| Schema migration | production | high | ESCALATE | change ticket, rollback plan, backup |
| `DELETE FROM users` | production | critical | ESCALATE | human DBA approval |
| `DROP TABLE` | any production | critical | ESCALATE | human DBA approval, backup, rollback |
| Unknown SQL mutation | production | critical | ABSTAIN or ESCALATE | query review |

## Practical default

```yaml
database:
  production_destructive_write:
    default_gate: ESCALATE
    required_evidence:
      - change_ticket
      - rollback_plan
      - backup_reference
      - human_database_owner_approval

  production_export:
    default_gate: VERIFY
    required_evidence:
      - business_purpose
      - data_minimization_review
      - approval_ticket
```

