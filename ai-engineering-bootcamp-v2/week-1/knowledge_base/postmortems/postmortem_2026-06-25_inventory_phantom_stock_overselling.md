---
title: Phantom Stock Overselling Incident
incident_id: INC-1063
service: inventory-sync
severity: SEV1
date: 2026-06-25
duration: 6 hours 40 minutes
tags: [inventory, overselling, phantom-stock, 3pl, access-token]
---

# Postmortem: Phantom Stock Overselling Incident

## Summary
The 3PL's nightly `inventorySetQuantities` push job failed silently for 6 hours 40 minutes after its Shopify Admin API access token expired without a renewal alert on either side, leaving `available` quantities stale across one location while storefront and Shop app orders continued to be accepted against phantom stock. 47 orders were placed for SKUs that were actually out of stock at the 3PL by the time the orders were placed.

## Impact
- 47 orders accepted for products that had zero real on-hand stock at the 3PL, across a single location.
- All 47 orders required manual handling: 31 were fulfilled via an emergency inter-location transfer from a secondary location that still had stock, 16 required customer outreach for backorder consent or cancellation with refund.
- No data loss or corruption — this was a stale-data problem with direct customer and revenue impact, not a data-integrity problem.

## Timeline (UTC)
- **02:00** — The Admin API access token used by the 3PL's push integration expires (90-day rotation policy; no automated renewal was configured on the 3PL's side).
- **02:05** — 3PL's nightly `inventorySetQuantities` batch job begins, receives an authentication failure on every call, and logs the failure to a log file that isn't monitored by an alert — the job's own completion status still reports "success" because it treats auth failures as retryable rather than fatal.
- **02:05–08:40** — `available` quantities in Shopify remain frozen at their pre-expiry values for the affected location while real on-hand at the 3PL continues to deplete from overnight and early-morning order fulfillment against other channels.
- **06:00–08:30** — Storefront and Shop app orders continue to be accepted against the frozen (phantom) stock figures; 47 orders placed for now-out-of-stock SKUs during this window.
- **08:40** — Customer service escalates a cluster of "item unavailable" fulfillment exceptions from the 3PL's own warehouse system, which does correctly reflect zero stock, flagging the mismatch with Shopify.
- **08:44** — On-call confirms via the `inventoryItem` GraphQL query that `available` figures for the affected SKUs are stale relative to the 3PL portal.
- **08:50** — On-call identifies the expired access token as the root cause after checking the 3PL's push job auth logs.
- **08:55** — New access token issued and provided to the 3PL; automated push resumes and completes a full reconciliation sync (not incremental) within 10 minutes.
- **09:05** — Spot-check of sample SKUs confirms `available` now matches the 3PL portal.
- **09:05–12:45** — Customer service works through the 47 affected orders: 31 fulfilled via inter-location transfer, 16 require customer contact for backorder/cancellation.

## Root Cause
Three compounding issues: (1) the Admin API access token had a 90-day expiry with no automated renewal or expiry-warning alert configured on the 3PL's side, (2) the 3PL's push job treated authentication failures as retryable rather than fatal, so it reported "success" to its own monitoring even while every call failed for over 6 hours, and (3) we had no independent staleness check on our side — nothing alerted on "this location's inventory hasn't been updated in an abnormally long time relative to its normal update frequency."

## Resolution
Issued a new access token to the 3PL and triggered a full (not incremental) reconciliation sync to guarantee correctness after a stall of unknown partial-update state. Routed the 47 affected orders to customer service for manual resolution.

## Action Items
1. Add a staleness monitor per location: alert if no `inventorySetQuantities` push has landed within an expected interval based on that location's normal update frequency. (Owner: inventory-sync team, done 2026-06-27)
2. Require the 3PL integration to treat authentication failures as fatal, not retryable-and-silently-successful, and to alert their own on-call accordingly. (Owner: inventory-sync team + 3PL vendor, done 2026-07-02)
3. Move access token rotation to an automated flow with a renewal alert at 75%/90% of token lifetime, rather than a manual 90-day calendar reminder. (Owner: infrastructure team, done 2026-07-05)
4. Document phantom-stock incident response (deny-oversell toggle, full reconciliation sync, order-triage handoff to customer service) as a first-response runbook rather than something improvised during this incident. (Owner: on-call lead, done 2026-06-26, published as `runbook_inventory_phantom_stock_overselling.md`)

## Lessons Learned
A push-model integration's "job completed successfully" signal is meaningless if the job itself doesn't distinguish "nothing to push" from "every call failed but I kept going anyway." The failure was invisible on both sides for over six hours because each side trusted a different, individually incomplete signal — the 3PL trusted its own job-completion status, and we trusted the absence of error webhooks. A staleness check based on expected update cadence, independent of either side's self-reported health, is what actually would have caught this early. See runbook: `runbook_inventory_phantom_stock_overselling.md`.
