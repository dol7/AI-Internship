---
title: Phantom Stock / Overselling from Stalled 3PL Push
service: inventory-sync
component: 3pl-push
tags: [inventory, overselling, phantom-stock, 3pl, oncall]
last_updated: 2026-06-28
---

# Runbook: Phantom Stock / Overselling from Stalled 3PL Push

## Background
Our 3PL is the single source of truth for `on_hand` quantity and pushes updates to Shopify via the `inventorySetQuantities` mutation (push model), one `InventoryLevel` per `InventoryItem` per location. If this push stalls, Shopify's `available` quantity (`on_hand` minus `committed`) goes stale but keeps serving as truth to every sales channel (storefront, Shop app, POS) — this is "phantom stock": Shopify believes stock exists that the 3PL has already depleted.

## Symptoms
- Spike in order cancellations/refunds specifically for items later confirmed out-of-stock at the 3PL.
- Customer complaints about items marked "in stock" at checkout that turn out to be backordered.
- A sampled SKU's `available` quantity in Shopify's Admin (or via the `inventoryItem` GraphQL query) doesn't match the 3PL portal's on-hand figure for the same location.
- Gap in `inventory_levels/update` webhook activity for a location where order volume would normally guarantee frequent updates.

## Diagnostic Steps
1. Check the last successful `inventorySetQuantities` push timestamp per location: `SELECT location_id, max(pushed_at) FROM inventory_push_log GROUP BY location_id ORDER BY max(pushed_at) ASC;` — a location with a stale timestamp relative to order volume indicates a stalled feed.
2. Check the 3PL's batch job status directly (their ops dashboard or status API) for the corresponding feed job — a crashed or stuck job is the most common cause.
3. Spot-check a handful of high-velocity SKUs: compare Shopify's `available` quantity via the `inventoryItem` GraphQL query against the 3PL portal's on-hand figure for the same location.
4. Check whether the push job is failing auth (expired Admin API access token) vs. failing silently mid-batch (partial success, some `InventoryLevel` records updated and others not).
5. Check for `inventory_levels/update` webhook delivery gaps in the same window, which would indicate the problem is upstream (3PL not pushing) rather than downstream (Shopify not accepting).

## Common Causes
- 3PL's nightly/scheduled batch push job crashed or hung without alerting on their side.
- Admin API access token used for `inventorySetQuantities` expired or was revoked, causing every push attempt to fail auth silently if the 3PL's error handling doesn't surface it clearly.
- Partial batch failure: `inventorySetQuantities` rejected some line items (e.g. hitting GraphQL query cost limits on a very large batch) while others succeeded, leaving a subset of SKUs stale without an obvious full-outage signal.
- Network/connectivity issue between the 3PL and Shopify's Admin API that only affects one direction of a bidirectional integration.

## Remediation Steps
1. **Immediate relief**: for any SKU confirmed oversold or at high risk, temporarily set inventory policy to deny overselling (block further sales) via bulk update or Shopify Flow, rather than waiting for the feed to catch up.
2. Trigger a manual full reconciliation sync from the 3PL's source-of-truth on-hand data, not an incremental delta — a stalled feed may have missed multiple incremental updates, so only a full resync guarantees correctness.
3. If the cause is an expired access token, rotate/reissue it and confirm the 3PL's integration is using the new token before resuming the automated push.
4. Once reconciliation completes, spot-check the same sample SKUs from diagnostics to confirm `available` now matches the 3PL portal.
5. Identify orders placed against phantom stock during the stall window and route them to customer service for backorder communication or cancellation/refund — this is a merchant-facing consequence that needs handling regardless of the technical fix.

## Escalation
- If the 3PL's push job cannot be restarted or the vendor is unresponsive, page the 3PL integration on-call and loop in the merchant success team to proactively communicate expected fulfillment delays.
- If oversold orders exceed a small handful, escalate to the merchant directly — this has direct customer-trust and revenue impact, not just a technical one.
- See postmortem: `postmortem_2026-06-25_inventory_phantom_stock_overselling.md`.
