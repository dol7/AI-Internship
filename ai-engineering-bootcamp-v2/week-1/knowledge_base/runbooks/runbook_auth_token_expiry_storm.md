---
title: Customer Account Token Expiry Storm
service: customer-accounts
component: jwt-issuer
tags: [auth, jwt, mass-logout, oncall]
last_updated: 2026-03-25
---

# Runbook: Customer Account Token Expiry Storm

## Symptoms
- Sudden spike in `401 Unauthorized` errors across storefront, order history, and subscription-management pages simultaneously.
- Customer support tickets reporting shoppers unexpectedly signed out mid-checkout.
- customer-accounts `/refresh` endpoint traffic spikes 10-20x baseline (this proxies the OIDC token exchange endpoint at `https://shopify.com/authentication/{shop-id}/oauth/token`).
- `id_token` verification failures against our JWKS endpoint (`.well-known/openid-configuration` → `jwks_uri`) appearing in Customer Account API logs.
- No corresponding deploy on storefront or checkout — the spike originates from customer-accounts' key management, not the OIDC flow itself.

## Diagnostic Steps
1. Check the JWKS signing key rotation log: `SELECT * FROM signing_keys ORDER BY rotated_at DESC LIMIT 5;` — a rotation without a grace period invalidates all outstanding `id_token`/`access_token` pairs at once.
2. Check whether all issued tokens share the same `exp` claim due to a clock or config bug (tokens should have staggered expiry based on issue time).
3. Check customer-accounts logs for `invalid signature` / `kid not found in JWKS` errors, which indicate old tokens are being rejected against a JWKS document that no longer lists the key that signed them.
4. Confirm with the Datadog `customer-accounts-token-lifecycle` dashboard whether this is a rotation event or a batch of tokens issued at the same instant expiring together.

## Common Causes
- Signing key rotated without keeping the previous key valid for a grace period (should overlap by at least 2x max token TTL).
- A deploy that issued all tokens with a hardcoded absolute expiry instead of relative-to-issue-time expiry.
- Clock skew between customer-accounts instances causing premature expiry judgments.

## Remediation Steps
1. **Immediate relief**: re-enable the previous signing key as a valid verification key (do not use it to issue new tokens) so old tokens verify successfully: `POST /admin/signing-keys/{key_id}/reactivate`.
2. Force a soft refresh wave: instruct storefront clients (via feature flag) to proactively refresh tokens on next request rather than waiting for natural expiry, to spread out load.
3. Monitor `/refresh` endpoint for secondary overload from the refresh wave itself — scale customer-accounts horizontally if needed.
4. Once stable, audit the key rotation process to require a minimum overlap window before deprecating an old key.

## Escalation
- If reactivating the old key doesn't resolve 401s within 5 minutes, page the security on-call — this may not be a rotation issue.
- See postmortem: `postmortem_2026-03-22_customer_accounts_incident.md`.
