---
title: Payment Gateway Webhook Processing Failure
incident_id: INC-0951
service: payment-gateway
severity: SEV1
date: 2026-01-09
duration: 1 hour 12 minutes
tags: [payments, webhook, third-party, idempotency, checkout, financial-status]
---

# Postmortem: Payment Gateway Webhook Processing Failure

## Summary
This incident is scoped to merchants on a **third-party gateway** (Stripe, direct integration), not Shopify Payments — Shopify Payments confirmations are handled natively by Shopify and were unaffected throughout. A schema change from the third-party processor's webhook payload was not backward compatible with our parser, causing all incoming payment confirmation webhooks to fail silently. This left ~1,900 completed checkout payments with their Shopify order record stuck at `financial_status: pending` instead of transitioning to `paid`, for over an hour.

## Impact
- ~1,900 successful shopper payments were not reflected in Shopify's order `financial_status` (stuck at `pending` rather than transitioning to `paid`) for 1 hour 12 minutes. Because `financial_status` never flipped, downstream `orders/paid`-triggered flows (inventory decrement, fulfillment workflow kickoff, confirmation email content) were delayed for these orders as well.
- No payments were lost or double-charged — the processor's records remained authoritative and correct throughout; this was a status-sync gap, not a payment-integrity gap.
- Customer-facing impact: some shoppers saw "payment processing" status longer than expected on their Thank You / order status page; a number contacted support.

## Timeline (UTC)
- **10:00** — Payment processor rolls out a webhook payload schema update (renaming a field from `amount_cents` to `amount_minor_units`), announced in their changelog but not caught by our team.
- **10:02** — Webhook parser begins throwing `KeyError: amount_cents` on every incoming webhook; errors are logged but the webhook endpoint still returns 200 (bug: error was caught and swallowed to avoid triggering processor-side retries, an intentional but overly broad safeguard).
- **10:45** — A support ticket about a shopper's "stuck" order status prompts manual investigation.
- **11:02** — Engineer discovers the parser error pattern in logs, traces it to the field rename.
- **11:08** — Hotfix deployed to accept both field names during a transition period.
- **11:14** — New webhooks begin processing correctly.
- **11:14–11:30** — Backfill job runs against the payment processor's API to fetch and reprocess the ~1,900 payments missed during the outage window, updating `financial_status` to `paid` and re-firing the internal equivalent of `orders/paid`-triggered flows accordingly.
- **11:30–12:12** — Backfill completes and verified against processor records; all order statuses reconciled.
- **(follow-up, 2026-01-13)** — A merchant on Skio subscription billing reports a recurring order stuck at `pending` days after the incident window. Investigation finds the initial backfill only queried standard checkout-originated payments; subscription orders created via the subscription app's billing API (Skio/Recharge-style) fire their payment confirmation from a different origin than standard checkout and were not covered by the original backfill query. A second, targeted backfill is run against the subscription billing API to close this gap.

## Root Cause
Two compounding issues: (1) the payment processor changed a webhook field name without our team having a change-monitoring process for third-party webhook schemas, and (2) our webhook handler was designed to always return HTTP 200 to avoid triggering the processor's retry/backoff behavior, which meant the parsing failure was silent from the processor's perspective — no automatic retries occurred, and no alert fired on the swallowed error until a human noticed.

## Resolution
Deployed a hotfix accepting both old and new field names, then backfilled the 1 hour 12 minutes of missed webhooks via the processor's payments-list API, reconciling order status against their authoritative records.

## Action Items
1. Add an alert on webhook parsing error rate, even when the endpoint itself returns 200 — errors should never be fully silent, especially on the checkout payment path. (Owner: payment-gateway team, done 2026-01-10)
2. Subscribe to the payment processor's API changelog/webhook feed for schema change notifications. (Owner: payment-gateway team, done 2026-01-11)
3. Add a nightly reconciliation job comparing our order-status records against the processor's payment records, independent of webhook delivery, as a backstop against any future silent gap. (Owner: payment-gateway team, done 2026-01-20)
4. Extend the reconciliation job to explicitly cover subscription-app-originated orders (Skio/Recharge billing API) as a separate query path, not just standard checkout — the initial backfill's scope gap on this exact incident was only caught by a merchant report three days later. (Owner: payment-gateway team, done 2026-01-14)

## Lessons Learned
Swallowing errors to avoid third-party retry storms is a reasonable tradeoff, but it must never come at the cost of internal alerting — the two concerns (external retry behavior, internal observability) should be handled independently, and this matters most on the payment confirmation path where shopper trust is directly at stake. Separately, "reconcile against the processor's records" is only complete if the reconciliation query covers every order origin — standard checkout and subscription-app billing are structurally different paths to the same `financial_status` field, and a backfill scoped to one will silently miss the other. See runbook: none existed prior to this incident; this postmortem's action items established the reconciliation job now referenced in payment-gateway on-call documentation.
