---
title: Customer Accounts Mass Logout Incident
incident_id: INC-1018
service: customer-accounts
severity: SEV1
date: 2026-03-22
duration: 34 minutes
tags: [auth, jwt, key-rotation, mass-logout]
---

# Postmortem: Customer Accounts Mass Logout Incident

## Summary
A scheduled JWT signing key rotation was deployed without a grace period, immediately invalidating every outstanding customer session token platform-wide and logging out effectively all active shoppers simultaneously, including several mid-checkout.

## Impact
- ~100% of logged-in shoppers across storefront and order-history pages were signed out within a 2-minute window.
- 401 error rate across all downstream services (storefront, order history, subscription management) spiked to 40x baseline for the duration.
- Support ticket volume increased 6x for the following 24 hours; several tickets reported abandoned checkouts due to being logged out mid-purchase.

## Timeline (UTC)
- **11:00** — Scheduled key rotation job runs as part of routine security hygiene, rotating the JWT signing key.
- **11:00:30** — Old signing key is fully deactivated for verification (not just issuance) — this was the bug; the intent was to keep it valid for verification during a grace period.
- **11:01** — 401 error rate spikes across storefront, order-history, and subscription-management services.
- **11:03** — On-call paged by automated alert on 401 rate.
- **11:09** — Root cause identified: key rotation script deactivated the old key for both issuance and verification instead of issuance only.
- **11:15** — On-call reactivates the old key for verification purposes via `/admin/signing-keys/{key_id}/reactivate`.
- **11:18** — 401 error rate begins dropping as tokens signed with the old key start verifying successfully again.
- **11:34** — Error rate back to baseline; incident resolved.

## Root Cause
The key rotation automation had a single "deactivate" action that removed a key from both the issuance path and the verification path simultaneously. The intended design was for old keys to remain valid for verification for at least 2x the maximum token TTL after being retired from issuance, but this distinction did not exist in the automation's data model — a key was either fully active or fully inactive.

## Resolution
Manually reactivated the old key for verification, which allowed already-issued tokens to continue validating while new tokens used the new key. Root fix separated "issuance-active" and "verification-active" as independent states in the signing key data model, with automation now requiring an explicit grace period before fully deactivating a key.

## Action Items
1. Redesign signing key state model to separate issuance and verification activity. (Owner: customer-accounts team, done 2026-03-29)
2. Add a minimum grace-period enforcement (2x max token TTL) to the rotation automation, rejecting rotations that skip it. (Owner: customer-accounts team, done 2026-03-29)
3. Add a canary check post-rotation that verifies a token issued just before rotation still validates. (Owner: security team, done 2026-04-02)

## Lessons Learned
"Deactivate" is not a single concept for credentials that have both an issuance role and a verification role — conflating them turns a routine rotation into a checkout-abandoning outage. See runbook: `runbook_auth_token_expiry_storm.md`.
