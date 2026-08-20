---
title: Storefront Search Latency Spike
incident_id: INC-1031
service: storefront-search
severity: SEV2
date: 2026-04-18
duration: 22 minutes
tags: [cache, redis, thundering-herd, collections]
---

# Postmortem: Storefront Search Latency Spike

## Summary
The cache key for the "Best Sellers" collection expired at 09:00 UTC exactly, causing a cache stampede that spiked storefront-search p99 latency from 150ms to over 3 seconds for 22 minutes.

## Impact
- p99 latency on `/collections/best-sellers` and general `/search` exceeded 3s for 22 minutes.
- Estimated 8% of storefront search/collection requests during the window timed out client-side.
- No data corruption or incorrect product results served.

## Timeline (UTC)
- **08:00** — "Best Sellers" collection cache key set with a flat 1-hour TTL as part of the previous day's deploy.
- **09:00** — Key expires. All concurrent homepage/collection requests miss cache simultaneously and each independently queries the product catalog DB to recompute the collection.
- **09:00:15** — Product catalog Postgres read-replica CPU spikes to 95%.
- **09:01** — storefront-search p99 latency alert fires.
- **09:04** — On-call identifies synchronized cache miss pattern via Redis `INFO stats`.
- **09:08** — On-call manually re-warms the Best Sellers key via `scripts/cache_warm.py`.
- **09:12** — Latency begins recovering as the freshly warmed key serves subsequent requests.
- **09:22** — p99 latency back to baseline; incident resolved.

## Root Cause
The Best Sellers cache key was set with a flat, non-jittered 1-hour TTL. Because it was originally set at a round-number timestamp (08:00), it expired at another round-number timestamp (09:00) — a time of naturally high storefront traffic (start of business hours). Every concurrent request that missed cache independently recomputed the same expensive best-sellers aggregation query against Postgres, overwhelming the read replica.

## Resolution
Manually re-warmed the cache key to stop the bleeding. Follow-up fix added jittered TTLs (base TTL ± 10% random) for all high-traffic collection cache keys, and added a request-coalescing lock so only one request recomputes a missing key while others wait for the result.

## Action Items
1. Apply jittered TTL to all cache keys tagged `high-traffic` in the cache config, starting with all curated collections. (Owner: storefront-search team, done 2026-04-22)
2. Implement request-coalescing lock for cache misses (`SEARCH_CACHE_LOCK_ENABLED` flag). (Owner: storefront-search team, done 2026-04-25)
3. Add a synthetic check that pre-warms known hot collection keys 5 minutes before their scheduled expiry. (Owner: SRE, done 2026-04-24)

## Lessons Learned
Round-number TTLs on high-traffic keys create synchronized expiry with traffic patterns that are themselves often round-number-aligned (top of the hour, start of business day). Jitter should be the default, not an exception. See runbook: `runbook_redis_cache_stampede.md`.
