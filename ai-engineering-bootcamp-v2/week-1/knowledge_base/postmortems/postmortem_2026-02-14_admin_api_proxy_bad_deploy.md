---
title: Admin API Proxy Bad Deploy
incident_id: INC-0987
service: admin-api-proxy
severity: SEV1
date: 2026-02-14
duration: 18 minutes
tags: [deploy, rollback, 500-errors, canary, graphql]
---

# Postmortem: Admin API Proxy Bad Deploy

## Summary
A deploy introducing new GraphQL query-cost header validation logic contained a null-pointer bug that crashed request handling for any request missing an optional cost-tracing header, causing a sharp 500 error spike across all partner app traffic routed through admin-api-proxy.

## Impact
- 5xx error rate reached 35% of all admin-api-proxy traffic for 18 minutes.
- All partner apps calling the Admin GraphQL API through the proxy were affected simultaneously.
- No data loss; failed requests were client-retried or surfaced as errors, no silent corruption of merchant data.

## Timeline (UTC)
- **16:02** — admin-api-proxy v4.7.2 deploy completes, including new optional-header validation logic for GraphQL query-cost tracing.
- **16:03** — Canary stage (5% traffic) shows no elevated error rate — canary traffic happened to include the optional header on all sampled requests.
- **16:04** — Full rollout proceeds to 100% traffic.
- **16:05** — 5xx error rate begins climbing as traffic mix includes requests without the optional header.
- **16:07** — Automated alert fires on error rate threshold.
- **16:10** — On-call confirms error spike began exactly at full rollout, pulls the deploy diff.
- **16:14** — Root cause identified: null-pointer when optional cost-tracing header absent.
- **16:16** — Rollback initiated to v4.7.1.
- **16:20** — Rollback completes; error rate returns to baseline.

## Root Cause
The new validation logic assumed the optional cost-tracing header would always be present based on staging traffic patterns, where an internal test client always sent it. Production traffic includes many legitimate partner apps that omit the optional header, triggering a null-pointer exception on that code path. The canary stage's 5% traffic sample happened not to include any header-omitting requests, so it did not catch the bug before full rollout.

## Resolution
Rolled back to v4.7.1. Fixed the null-pointer bug to handle the header's absence correctly, added a unit test explicitly covering the missing-header case, and shipped as v4.7.3 the following day with a longer canary window.

## Action Items
1. Add explicit test case for optional-header-absent path. (Owner: admin-api-proxy team, done 2026-02-15)
2. Increase canary traffic percentage from 5% to 15% and canary duration from 2 minutes to 10 minutes for proxy-tier deploys, to increase odds of catching low-frequency-pattern bugs. (Owner: platform team, done 2026-02-20)
3. Add a canary success gate requiring a minimum diversity of request shapes (header presence/absence, query complexity, app type) sampled, not just volume. (Owner: platform team, in progress)

## Lessons Learned
A canary that only checks volume/error-rate threshold, without ensuring representative traffic diversity across the wide range of partner app integration patterns, can pass cleanly while missing a bug that only manifests for a traffic pattern absent from the sample. See runbook: `runbook_deployment_rollback.md`.
