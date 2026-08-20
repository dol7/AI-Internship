---
title: Database Connection Pool Exhaustion
service: subscription-billing
component: postgres
tags: [database, connection-pool, latency, oncall]
last_updated: 2026-05-10
---

# Runbook: Database Connection Pool Exhaustion

## Symptoms
- API latency on subscription-billing spikes above 2s p99.
- Application logs show `FATAL: remaining connection slots are reserved` or `timeout waiting for idle connection`.
- Postgres `pg_stat_activity` shows connection count near `max_connections`.
- Merchant-facing subscription renewal charges start failing with 504s, and the Shopify Billing API charge-confirmation callback queue starts backing up.

## Diagnostic Steps
1. Check current connection count: `SELECT count(*) FROM pg_stat_activity;`
2. Compare against pool config in `subscription-billing/config/db.yaml` (`pool_size`, `max_overflow`).
3. Look for long-running or idle-in-transaction queries: `SELECT pid, state, query, now() - query_start AS age FROM pg_stat_activity WHERE state != 'idle' ORDER BY age DESC;`
4. Check for a recent deploy that changed query patterns or removed connection cleanup (`git log -- subscription-billing/db/`).
5. Check for a traffic spike in the Datadog dashboard `subscription-billing-overview` correlating with the connection climb — often aligned with the nightly bulk renewal batch.

## Common Causes
- A slow query holding a connection open (missing index, N+1 pattern) during the bulk renewal batch.
- Connection leak from a code path that doesn't release connections on exception when a Shopify Billing API call times out.
- Pool size configured too low for current merchant volume after a scale-up event.
- The nightly renewal batch job running against the same pool as live storefront checkout traffic.

## Remediation Steps
1. **Immediate relief**: kill the oldest idle-in-transaction sessions: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND now() - query_start > interval '5 minutes';`
2. If a specific query is identified as the culprit, disable the feature flag or endpoint calling it.
3. If pool size is the bottleneck and DB CPU/memory has headroom, bump `pool_size` in config and redeploy (requires on-call lead approval for prod).
4. If the nightly renewal batch is competing for connections, pause it via the scheduler admin panel.
5. Verify recovery: connection count trending down, p99 latency back under 300ms for 10 consecutive minutes.

## Escalation
- If connection count doesn't recover after step 1, page the database on-call (#db-oncall).
- If root cause is a code defect, open a SEV ticket and tag the subscription-billing team.
- See postmortem: `postmortem_2026-05-03_subscription_billing_outage.md` for the incident that originated this runbook.
