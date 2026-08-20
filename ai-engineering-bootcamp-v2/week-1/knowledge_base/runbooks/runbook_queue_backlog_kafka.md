---
title: Kafka Consumer Backlog
service: webhook-dispatcher
component: kafka
tags: [queue, kafka, backlog, webhooks, oncall]
last_updated: 2026-06-15
---

# Runbook: Kafka Consumer Backlog

## Symptoms
- Delivery delay for `orders/create`, `inventory_levels/update`, and other topic webhooks climbs from seconds to minutes/hours.
- Consumer group lag (`kafka-consumer-groups.sh --describe --group webhook-consumers`) growing steadily rather than holding steady.
- Merchant/partner-app complaints about delayed webhook delivery, not missing events.
- No error spike — the pipeline is slow, not broken.
- **Time-critical**: any destination whose delivery attempts have been failing (not just slow) approaches our retry ceiling — modeled on Shopify's own webhook policy of 19 retries over 48 hours, after which the subscription is auto-deleted and must be re-registered from scratch. A backlog that looks merely "slow" can silently cross into "subscription about to be deleted" if failures, not just latency, are involved.

## Diagnostic Steps
1. Check consumer lag per partition: `kafka-consumer-groups.sh --bootstrap-server $BROKER --describe --group webhook-consumers`.
2. Check consumer pod count vs partition count — under-provisioned consumers can't parallelize past partition count.
3. Check for a single slow partition (hot key skew, e.g. one very high-volume merchant) vs uniform lag across all partitions.
4. Check destination endpoint latency (merchant/partner webhook receivers) in the Datadog `webhook-dispatcher-deps` dashboard — a slow merchant endpoint can throttle the whole consumer if delivery is synchronous per partition.
5. Check for a recent surge in produced events (a large merchant's bulk product import or a flash-sale order spike) in the producer-side metrics.
6. **Check failed-attempt count per destination**, not just lag: `SELECT destination_id, count(*) FROM delivery_attempts WHERE status != 'success' AND ts > now() - interval '48 hours' GROUP BY destination_id;`. Any destination nearing 19 failed attempts within a 48-hour window is at risk of automatic subscription deletion, distinct from and more urgent than plain latency-driven lag.
7. For `inventory_levels/update` specifically, remember events fire per location — a backlog affecting one location (e.g. a 3PL-fulfilled location) but not another (e.g. Shop) points to a location-specific downstream integration issue, not a platform-wide one.

## Common Causes
- Consumer count below partition count, leaving partitions unconsumed.
- A slow destination endpoint (a merchant's app server or an ERP integration like Celigo/NetSuite) causing each event to take longer to deliver.
- Hot-key skew: one partition receiving disproportionate traffic (e.g. all events for one very high-volume merchant).
- A poison-pill payload causing repeated retries/backoff on one partition.

## Remediation Steps
1. **Immediate relief**: scale consumer replicas up to match partition count (`kubectl scale deployment webhook-consumer --replicas=<partition_count>`).
2. If a specific merchant/partner endpoint is slow, move that merchant to an isolated async delivery queue with its own backoff, so it doesn't throttle other merchants sharing the partition.
3. If a poison-pill payload is suspected, check the dead-letter queue and manually skip/quarantine the offending offset.
4. If hot-key skew is confirmed, consider re-partitioning by a higher-cardinality key (e.g. event ID instead of shop ID).
5. **If any destination is within 3 attempts of the 19-attempt/48-hour deletion ceiling**, pause automatic retries for that destination and either fix the receiving endpoint immediately or proactively re-register the subscription before deletion occurs — recovering from an auto-deleted subscription requires manual re-registration and a full backfill, which is far more disruptive than a delayed-but-intact backlog.
6. When re-verifying delivery after remediation, confirm the receiving endpoint is validating the `X-Shopify-Hmac-Sha256` signature and deduplicating on `X-Shopify-Webhook-Id` — a burst of redelivered events after backlog recovery can otherwise cause duplicate processing downstream.

## Escalation
- If lag doesn't start decreasing within 15 minutes of scaling consumers, page the platform on-call — likely a downstream dependency issue, not a consumer capacity issue.
- If any destination crosses the 19-attempt deletion ceiling before remediation completes, treat as a separate, higher-severity issue — the subscription must be re-created via `webhookSubscriptionCreate` and a manual backfill initiated for the gap.
- See postmortem: `postmortem_2026-06-11_webhook_dispatcher_delay.md`.
