---
title: Admin API Rate Limit 429 Spike
service: admin-api-proxy
component: rate-limiter
tags: [rate-limit, 429, graphql-cost, admin-api, oncall]
last_updated: 2026-01-15
---

# Runbook: Admin API Rate Limit 429 Spike

## Symptoms
- Sudden spike in `429 Too Many Requests` / GraphQL `MAX_COST_EXCEEDED` responses on the Datadog `admin-api-proxy-status-codes` dashboard.
- Partner/app-developer tickets reporting their app integrations are being throttled unexpectedly.
- No corresponding real traffic spike in overall RPS — the 429s are disproportionate to actual request volume, suggesting a query-cost problem rather than a volume problem.

## Diagnostic Steps
1. Break down 429s/cost-exceeded errors by app/client ID: `SELECT client_id, count(*) FROM request_log WHERE status = 429 AND ts > now() - interval '1 hour' GROUP BY client_id ORDER BY count(*) DESC;` — determine if one app or many are affected.
2. Check if a recent change to rate-limit bucket sizes or GraphQL cost-point config was deployed (`config/rate_limits.yaml` git history).
3. Check if the affected app(s) recently shipped a change with a more expensive query (e.g. deeply nested connections without pagination limits), inflating cost points per request.
4. Check whether the leaky-bucket counter's Redis backing store is functioning correctly — a Redis issue can cause counters to reset or miscount, triggering false positives.

## Common Causes
- A config change accidentally lowered the cost-point bucket size or restore rate for a tier.
- A partner app's integration ships a new, more expensive query (e.g. fetching all variants of all products in one deeply nested query) and hits the ceiling repeatedly.
- Leaky-bucket counter (Redis) has clock skew or a bug causing incorrect counting across proxy replicas.
- A new app was provisioned on the wrong (lower) tier by mistake.

## Remediation Steps
1. **Immediate relief**: if a single app is affected and clearly correctly provisioned, temporarily raise their bucket size via `POST /admin/clients/{client_id}/rate-limit-override` while investigating.
2. If a config regression is confirmed, revert `rate_limits.yaml` and redeploy.
3. If a partner app's query cost is the cause, reach out via partner support with guidance on query cost optimization (pagination, field selection), and consider a short-term allowlist bump to unstick them.
4. Verify the Redis-backed counter is consistent across proxy replicas by comparing counts on two different pods for the same client.

## Escalation
- If multiple unrelated apps are affected simultaneously, treat as a platform bug, not an app-integration issue — page the admin-api-proxy on-call.
- No linked postmortem yet — this runbook was written proactively after a near-miss, not a full incident.
