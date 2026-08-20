---
title: Emergency Deployment Rollback
service: admin-api-proxy
component: deploy-pipeline
tags: [deploy, rollback, 500-errors, oncall]
last_updated: 2026-02-20
---

# Runbook: Emergency Deployment Rollback

## Symptoms
- Error rate (5xx) climbs sharply within minutes of a deploy completing on the layer proxying calls to the Shopify Admin GraphQL API.
- Datadog deployment marker on the `admin-api-proxy-errors` dashboard aligns exactly with the error spike.
- Partner apps calling through the proxy start reporting failed Admin API requests that worked pre-deploy.

## Diagnostic Steps
1. Confirm the timing correlation: check the deploy timestamp in the CI/CD tool against the error spike start time — should be within 1-2 minutes.
2. Pull the diff for the deployed change: `git log -1 --stat` on the deployed commit.
3. Check the specific error signature/stack trace to confirm it maps to the new code, not an unrelated coincidence.
4. Check canary metrics if the deploy used a canary stage — canary should have caught this; note why it didn't (insufficient traffic diversity, missing test coverage, canary skipped).

## Common Causes
- A code change with a bug that wasn't caught in CI (e.g. a bug in GraphQL query-cost header parsing that wasn't caught for requests without an optional header).
- A config/environment variable that differs between staging and prod, causing prod-only failures.
- A database migration that ran but the corresponding code expects a different schema state (migration/deploy ordering issue).
- A dependency version bump with a breaking change.

## Remediation Steps
1. **Immediate relief**: trigger rollback to the previous known-good revision: `./deploy.sh rollback admin-api-proxy --to-previous`.
2. Confirm error rate returns to baseline within 3-5 minutes of rollback completing.
3. If the deploy included a database migration, verify whether the migration itself needs to be rolled back separately (check `migrations/` for a corresponding `down` script) — do not blindly roll back migrations without checking for data written under the new schema.
4. Notify #deploys channel that a rollback occurred, with the commit hash and error signature for the owning team to investigate offline.

## Escalation
- If rollback does not resolve the error spike, the deploy may not be the root cause — page the on-call lead to investigate infrastructure/dependency issues in parallel.
- If a migration rollback is needed and touches merchant data, get explicit sign-off from the database on-call before running it.
- See postmortem: `postmortem_2026-02-14_admin_api_proxy_bad_deploy.md`.
