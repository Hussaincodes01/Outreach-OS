# Threat model

> Stub. The full threat model is part of Phase 8 (hardening) in the master
> plan. This document is a starting checklist, not a finished artefact.

## Assets

| Asset | Where | Sensitivity |
|---|---|---|
| Customer OAuth refresh tokens | `mailbox.refresh_token_ciphertext` | High — full mailbox access. |
| Customer LLM / scraping API keys | `credential.ciphertext` | High — cost + impersonation. |
| Customer SMTP passwords | `mailbox.smtp_config_ciphertext` | High — sending impersonation. |
| Tenant data (leads, emails) | Phase 2+ tables | High — GDPR / DPDP. |
| Master KEK (`VAULT_MASTER_KEY`) | Env / secret manager | Critical — derives every DEK. |
| JWT signing key (`JWT_SECRET`) | Env / secret manager | Critical — forges any tenant token. |
| Audit log | `audit_event` | High — tampering = regulatory risk. |

## Trust boundaries

- Web (Next.js) ↔ API (FastAPI): HTTPS, bearer JWT.
- API ↔ Postgres: same-network, RLS-gated.
- API ↔ Customer's Gmail/Outlook: OAuth refresh tokens we hold.
- API ↔ Customer's SMTP server: password we hold.
- API ↔ LLM provider (LiteLLM): API key we hold; PII may pass through.
- API ↔ Scraping provider (Scrapling + Proxycurl): API key + scrape targets.

## Top threats (with current mitigations)

| Threat | Mitigation in Phase 0+1 | Residual risk |
|---|---|---|
| Cross-tenant data leak | Postgres RLS + tenant-scoped sessions + tests | Low (RLS is enforced in tests). |
| Vault KEK exfiltration | KEK in env; not logged; not in DB | If the env leaks, all DEKs leak. **Phase 9: move to KMS.** |
| JWT secret leak | HS256 with secret in env | If the env leaks, any token can be forged. **Phase 9: rotate + RS256 with JWKS.** |
| Audit log tampering | Triggers block UPDATE/DELETE; rows are hash-chained | A superuser can drop the trigger. **Phase 9: revoke superuser from app role; daily hash anchoring to a public timestamping service.** |
| OAuth refresh-token theft | Tokens encrypted at rest; never returned to the frontend | Application-level log leakage. |
| LLM cost runaway | Per-tenant spend caps land in Phase 4 | Phase 0+1 has no LLM call paths. |
| Spam / unsubscribe non-compliance | Unsubscribe handling lands in Phase 4 | Until then, the system cannot send. |
| LinkedIn ToS violation | All LinkedIn data via resellers; we never scrape directly | Provider T&Cs apply; resellers handle enforcement. |
| CSRF on cookie-auth flows | Phase 0+1 uses bearer in `Authorization` header, not cookies — CSRF surface is small | When we move to cookies (Auth.js), add double-submit + SameSite=Strict. |
| SQL injection | SQLAlchemy parameterised queries + RLS as backstop | Any raw `text()` we add must be reviewed. |
| Dependency supply chain | Dependabot + `pip-audit` (CI) | Known-CVE window. |
| Open redirect on OAuth callback | State token is signed + single-use | Replay protection is a Phase 4 hardening item. |

## Out of scope for Phase 0+1 (Phase 8 hardening)

- Paid external pentest
- Full STRIDE walkthrough per data flow
- Customer-managed encryption keys (CMEK)
- SAML SSO
- SIEM export

## Open questions for the maintainer

- Do we need a row-level encryption layer in addition to the column-level
  Fernet DEK? Probably not until enterprise customers ask for it.
- Should the audit log be replicated to an off-host immutable store from
  day one? It is for V1; for Phase 0+1 the chain is detectable but a
  malicious superuser could rewrite history.
