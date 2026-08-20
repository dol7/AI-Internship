---
title: Subscription Billing Outage
incident_id: INC-1042
service: subscription-billing
severity: SEV1
date: 2026-05-03
duration: 47 minutes
tags: [database, connection-pool, outage, appSubscription]
---

# Postmortem: Subscription Billing Outage

## Summary
On 2026-05-03, subscription-billing became unresponsive for 47 minutes due to Postgres connection pool exhaustion, blocking `appUsageRecordCreate` usage-charge reporting and `appSubscriptionCreate` confirmation-URL generation platform-wide.

## Impact
- 100% of usage-charge reporting requests failed (HTTP 504) between 14:12 and 14:59 UTC — apps calling `appUsageRecordCreate` for merchants on usage-based plans could not report usage during the window.
- ~3,200 pending `appSubscriptionCreate` confirmation-URL requests were delayed by up to 2 hours; merchants attempting to approve a new app subscription during this window saw a stalled approval flow.
- No billing data loss; all queued usage records and subscription creation requests eventually processed after recovery. No `ACTIVE` subscriptions were incorrectly transitioned to `EXPIRED` or `FROZEN`.

## Timeline (UTC)
- **14:08** — Deploy of subscription-billing v2.14.0 completes, introducing a new "bulk renewal preview" endpoint used internally to preview upcoming `AppRecurringPricingInput` charges across a merchant's active line items.
- **14:12** — p99 latency alert fires on `subscription-billing-overview` dashboard.
- **14:15** — On-call engineer begins investigation; identifies climbing Postgres connection count.
- **14:22** — Root cause suspected: new bulk renewal preview endpoint opens a DB connection per subscription line item (via `appSubscriptionLineItemUpdate` lookups) instead of reusing one connection per request.
- **14:30** — On-call terminates idle-in-transaction sessions per runbook, provides temporary relief.
- **14:38** — Connection count climbs again as traffic continues hitting the buggy endpoint.
- **14:45** — Decision made to roll back v2.14.0.
- **14:55** — Rollback completes; connection count normalizes.
- **14:59** — p99 latency returns to baseline; incident resolved.

## Root Cause
The new bulk renewal preview endpoint opened one database connection per subscription line item within a loop, instead of reusing a single connection or batching the query. Under moderate load (a merchant with 200+ usage-pricing line items being previewed), this alone could exhaust a meaningful fraction of the pool; under concurrent load from multiple merchants, the pool was exhausted within minutes.

This code path had test coverage for correctness (confirming the right `AppUsagePricingInput` caps were returned) but not for connection usage under load — the load test suite does not currently simulate concurrent bulk operations.

## Resolution
Rolled back to v2.14.0's previous version. Fix was re-implemented using a single connection with a batched query and shipped as v2.14.1 two days later, with a new load test case covering concurrent bulk preview requests.

## Action Items
1. Add connection-usage assertions to the load test suite for any endpoint touching the DB in a loop. (Owner: subscription-billing team, done 2026-05-09)
2. Add a Datadog monitor on connection pool utilization at 70% (warning), not just exhaustion. (Owner: SRE, done 2026-05-06)
3. Require a code review checklist item for "does this endpoint open connections in a loop?" for all new DB-touching endpoints. (Owner: eng leads, done 2026-05-12)

## Lessons Learned
Load testing correctness is not the same as load testing resource usage. A code review focused on functional correctness missed a resource-exhaustion bug that only manifested under concurrent load, on an endpoint dealing with billing objects where reliability matters most. See runbook: `runbook_database_connection_pool_exhaustion.md`.
