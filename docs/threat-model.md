# Threat model

> Starting checklist for a single-user, self-hosted deployment — not a
> finished artefact. Re-review before exposing this beyond `localhost` /
> a private network.

## No authentication — the headline threat

**Outreach OS has no login, no session, no API token.** Every request that
reaches the API acts as the one local workspace, full stop. This is a
deliberate design choice for a single-user tool (see
[docs/architecture.md](architecture.md#tenancy-one-local-workspace-rls-still-enforced)),
but it means the API and web app must **never** be reachable by anyone other
than the operator:

- **Default-safe posture:** bind the stack to `localhost`/a private network
  only. The shipped `docker-compose.yml` publishes `api` (8000) and `web`
  (3000) to the host's network interfaces — on a machine with a public IP,
  that is publicly reachable unless a firewall blocks it.
- **If you need remote access:** put an authenticating reverse proxy in
  front (nginx/Caddy with basic auth or an OAuth gate, a Tailscale/WireGuard
  tunnel, an SSH tunnel, a cloud load balancer with its own auth). The API
  already trusts `X-Forwarded-*` via `--forwarded-allow-ips=*`, which is
  only safe behind a proxy you control — never put the API directly behind
  an untrusted proxy or expose it with no proxy at all.
- Anyone who can reach the API can read every lead, draft, send and reply,
  create/delete mailboxes (including reading back which provider is
  configured, though not the decrypted secret), and trigger real sends
  through the connected mailbox.

## Assets

| Asset | Where | Sensitivity |
|---|---|---|
| Mailbox SMTP/IMAP password | `mailbox.smtp_config_ciphertext` | High — sending impersonation, inbox read access. |
| Any provider key stored via the app (rather than `.env`) | `credential.ciphertext` | High — cost + impersonation. |
| Provider keys in `.env` / process environment | Host filesystem / container environment | High — same as above; never logged, never returned by the API. |
| Workspace data (leads, drafts, sends, replies) | Application tables | High — personal data, GDPR/DPDP scope. |
| Master KEK (`VAULT_MASTER_KEY`) | `.env` / secret manager | Critical — derives every DEK; losing it makes all stored secrets permanently undecryptable. |
| Inbound webhook secret (`INBOUND_WEBHOOK_SECRET`) | `.env` / secret manager | High — without it, anyone who can reach the webhook can inject fake replies. |
| Audit log | `audit_event` | Medium — tampering undermines the operational record. |

`mailbox.refresh_token_ciphertext` is an unused legacy column from the
removed Gmail/Outlook OAuth mailbox flow (SMTP/IMAP with an app password is
the only supported mailbox transport now); nothing writes to it.

## Trust boundaries

- Browser ↔ API/web: plain HTTP by default, no auth — see above. Add TLS +
  auth at a reverse proxy for anything beyond localhost.
- API ↔ Postgres: same Docker network, RLS-gated, non-superuser app role.
- API ↔ the operator's own mail server: SMTP password / IMAP credentials we
  hold, encrypted at rest.
- API ↔ LLM provider (LiteLLM): API key read from `.env`; PII may pass
  through in the prompt/context.
- API ↔ scraping provider (Serper, Proxycurl, ...): API key from `.env` +
  scrape targets.
- Inbound webhook: unauthenticated transport, HMAC-signed payload
  (`X-Outreach-Signature` vs `INBOUND_WEBHOOK_SECRET`).

## Top threats (with current mitigations)

| Threat | Mitigation | Residual risk |
|---|---|---|
| Unauthenticated access to the API/web app | None from the app itself — network-level only (bind to localhost, or a reverse proxy with its own auth) | **High if exposed without a proxy.** This is the primary threat in a no-auth build; mitigation is entirely the operator's deployment choice. |
| Cross-tenant data leak | Not applicable in normal single-user operation (one workspace), but the RLS mechanism is still exercised so a future multi-tenant reintroduction doesn't regress silently | Low. |
| Vault KEK exfiltration | `VAULT_MASTER_KEY` in env; not logged; not in DB | If the env/`.env` leaks, all stored DEKs leak — mailbox passwords and any app-stored provider key. Provider keys read directly from `.env` are exposed the same way `.env` itself is. |
| `.env` committed or otherwise leaked | `.gitignore`, pre-push secret grep in README/SETUP, never printed by the smoke script or logs | If it happens, rotate every key and the mailbox password, then regenerate `VAULT_MASTER_KEY` (accepting the existing-ciphertext loss) and `INBOUND_WEBHOOK_SECRET`. |
| Audit log tampering | Triggers block UPDATE/DELETE; rows are hash-chained | A superuser (`postgres`, migrations-only) could still drop the trigger by hand. |
| Mailbox credential theft | SMTP/IMAP password encrypted at rest via the vault; never returned by the API | Application-level log leakage; a compromised `VAULT_MASTER_KEY` exposes it. |
| LLM cost runaway | No per-workspace spend cap in a single-user build (there is only one workspace) | The operator's own provider account has no ceiling enforced here — set limits on the provider's side. |
| Spam / unsubscribe non-compliance | Every send gets an unsubscribe link + disclosure footer; suppression list checked before every send | Operator is responsible for complying with applicable law (CAN-SPAM, GDPR, etc.) for their own sending. |
| Inbound webhook forgery | HMAC-SHA256 signature check against `INBOUND_WEBHOOK_SECRET`; rate-limited per IP | If the secret leaks, forged replies can be injected. |
| SQL injection | SQLAlchemy parameterised queries + RLS as a backstop | Any raw `text()` added later must be reviewed. |
| Dependency supply chain | Dependabot + `pip-audit` (CI) | Known-CVE window. |

## Data export and deletion

- `GET /v1/gdpr/export` streams all workspace data as NDJSON. Like every
  other endpoint it is unauthenticated, so it is protected only by the same
  network-level controls described above.
- There is **no in-app erasure endpoint.** An unauthenticated delete of the
  only workspace would let anyone who reaches the API silently stop all
  sending. Wiping all data is an operator action on the host:
  `docker compose down -v` removes the Postgres, Redis and MinIO volumes.

## Out of scope for this build

- Paid external pentest.
- Full STRIDE walkthrough per data flow.
- Any form of multi-user access control (deliberately removed; see
  [docs/architecture.md](architecture.md)).
- TLS termination (left to the operator's reverse proxy).
- SIEM export / centralized log shipping.

## Open questions for the operator

- If you do put this behind a reverse proxy with auth, treat that proxy's
  credentials with the same care as the mailbox password — anyone who has
  them has full access to this workspace.
- Should the audit log be replicated to an off-host immutable store? For a
  single-user deployment the chain is detectable-but-not-prevented against a
  local superuser; decide based on how much you trust the host.
