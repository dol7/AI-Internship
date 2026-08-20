---
title: Webhook Delivery Delay
incident_id: INC-1059
service: webhook-dispatcher
severity: SEV3
date: 2026-06-11
duration: 3 hours 10 minutes
tags: [kafka, queue, backlog, webhooks, third-party]
---

# Postmortem: Webhook Delivery Delay

## Summary
A large partner integration's endpoint became degraded, causing webhook-dispatcher's Kafka consumers to slow down per-message delivery time on the shared partition, building a backlog that delayed `orders/create` and `inventory_levels/update` webhook delivery by up to 3 hours for a subset of merchants sharing that partition. No webhooks were lost.

## Impact
- Webhook delivery delayed by 20 minutes to 3 hours for ~15% of events produced during the window, concentrated among merchants integrated with the affected partner app.
- Order and inventory data in Shopify itself was unaffected — only the downstream webhook notification was delayed, not the underlying order/inventory state.
- No message loss; all backlogged webhooks eventually delivered with correct HMAC signatures and payloads.
- **Near-miss**: the affected partner's destination accumulated 11 failed/timed-out delivery attempts by 08:15 (its 5-second response window was frequently exceeded during its degradation) — approaching, but not reaching, the 19-attempt/48-hour threshold that would have triggered automatic deletion of its webhook subscription. Had isolation not occurred when it did, this destination was on track to hit that ceiling within the incident window.

## Timeline (UTC)
- **06:00** — A large partner ERP integration's receiving endpoint begins experiencing elevated latency (their status page later confirmed this, no advance notice given).
- **06:20** — Consumer lag on `webhook-consumers` group begins climbing steadily rather than holding steady.
- **07:45** — Datadog lag monitor crosses warning threshold; on-call begins investigation during business hours.
- **08:00** — On-call confirms lag is concentrated on the partition serving the affected partner's merchants (rules out uniform platform-wide issue) and correlates with elevated latency on that endpoint in the dependency dashboard.
- **08:15** — On-call moves the affected partner to an isolated async delivery queue with independent backoff via `WEBHOOK_ISOLATE_ENDPOINT` flag, so it stops throttling other merchants sharing the partition.
- **08:30** — Per-message processing time for the main partition drops; lag stops climbing there but the isolated queue's backlog still needs to drain against the slow endpoint.
- **09:10** — Main partition backlog fully drained; isolated queue continues draining slowly against the still-degraded partner endpoint, delivering all events without further platform impact.

## Root Cause
webhook-dispatcher's consumer processes events synchronously per-partition, meaning a slow destination endpoint directly throttles overall consumer throughput for every merchant sharing that partition — not just the affected one. There was no independent alert on individual destination-endpoint latency — the issue was only caught indirectly via consumer lag, adding roughly 90 minutes of detection delay. Separately, there was no alert on failed-attempt count approaching the 19-attempt deletion ceiling either — the near-miss on automatic subscription deletion was identified only in this postmortem's retrospective analysis, not caught live.

## Resolution
Isolated the affected partner integration onto its own async delivery queue with independent backoff, which stopped it from throttling other merchants and allowed the shared partition to drain immediately. The isolated queue continued draining against the slow endpoint without further platform-wide impact.

## Action Items
1. Add a direct latency/error-rate monitor per high-volume destination endpoint, independent of consumer lag. (Owner: webhook-dispatcher team, done 2026-06-14)
2. Automatically isolate any endpoint whose p95 delivery latency exceeds a threshold for 5+ minutes, rather than requiring manual intervention. (Owner: webhook-dispatcher team, in progress)
3. Document the endpoint-isolation procedure as a first-response step, not a discovered-mid-incident step. (Owner: on-call lead, done 2026-06-12, folded into `runbook_queue_backlog_kafka.md`)
4. Add a monitor on failed-delivery-attempt count per destination approaching the 19-attempt/48-hour deletion ceiling, surfaced as its own alert independent of latency or lag — this incident's near-miss on automatic subscription deletion was invisible to on-call in real time. (Owner: webhook-dispatcher team, done 2026-06-20)

## Lessons Learned
Detecting a downstream integration's degradation via its symptom on shared infrastructure (consumer lag) instead of directly monitoring per-endpoint latency added significant time-to-detection, and meant unrelated merchants were affected by one partner's slow endpoint. Per-destination isolation should be the default delivery model for high-volume integrations, not an incident-time mitigation. Separately, a delayed backlog and a destination approaching automatic subscription deletion look identical on a lag graph but require very different urgency — the failed-attempt count, not just lag or latency, needs its own first-class signal. See runbook: `runbook_queue_backlog_kafka.md`.
