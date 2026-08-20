---
title: Redis Cache Stampede
service: storefront-search
component: redis
tags: [cache, redis, latency, thundering-herd, oncall]
last_updated: 2026-04-20
---

# Runbook: Redis Cache Stampede

## Symptoms
- Sudden spike in storefront-search latency (p99 from ~150ms to 3s+) on the Storefront API `search`/`predictiveSearch` queries and `collection.products` filtered listings.
- Redis CPU utilization near 100% with a sharp step-change on the graph.
- Product catalog Postgres read-replica load spikes in lockstep with the Redis spike (cache misses falling through to the DB).
- Error rate on collection and search resolvers climbing without a corresponding deploy.

## Diagnostic Steps
1. Check Redis `INFO stats` for `keyspace_misses` vs `keyspace_hits` ratio — a stampede shows misses spiking together.
2. Check whether a popular cache key (e.g. the "Best Sellers" collection or a trending search facet) recently expired: `TTL <key>` on suspected hot keys.
3. Correlate with the Datadog `storefront-search-cache` dashboard for a synchronized drop in hit rate across many pods simultaneously.
4. Check for a recent cache flush (`FLUSHALL`/`FLUSHDB` in Redis audit log) or a deploy that changed TTL values.

## Common Causes
- A high-traffic key expires (e.g. "Best Sellers" collection cache) and hundreds of concurrent storefront requests all miss the cache at once, all hammering the product catalog DB to recompute the same collection.
- A deploy resets TTLs to a uniform value, causing many collection caches to expire simultaneously later.
- A manual or scripted cache flush during a maintenance window without a warm-up step.

## Remediation Steps
1. **Immediate relief**: enable the request coalescing flag (`SEARCH_CACHE_LOCK_ENABLED=true`) so only one request per key recomputes while others wait — this is a feature-flagged fix, no deploy needed.
2. If the product catalog read replica is the bottleneck, temporarily route reads to the secondary replica pool.
3. Manually re-warm the top 100 known-hot collection/search keys via `scripts/cache_warm.py --top=100`.
4. Once traffic stabilizes, apply jittered TTLs (base TTL ± random 10%) to prevent synchronized expiry going forward.

## Escalation
- If product catalog replica lag exceeds 30s during the incident, page the database on-call — inventory/price consistency shown to shoppers is at risk.
- Note: Search & Discovery app config (synonyms, boosts, custom filters) is resolved live from the product catalog on cache miss, not cached separately — a stampede does not corrupt synonym/boost behavior, but does amplify DB load while resolving it repeatedly.
- See postmortem: `postmortem_2026-04-18_storefront_search_latency_spike.md` for the original incident and the jittered-TTL fix that followed.
