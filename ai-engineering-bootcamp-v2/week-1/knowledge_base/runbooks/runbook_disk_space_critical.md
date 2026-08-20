---
title: Disk Space Critical on Inventory Sync Workers
service: inventory-sync
component: worker-nodes
tags: [disk, storage, inventory, erp, oncall]
last_updated: 2026-05-30
---

# Runbook: Disk Space Critical on Inventory Sync Workers

## Symptoms
- Datadog host-level alert: disk usage above 90% on one or more `inventory-sync-worker-*` nodes.
- Multi-location inventory sync jobs (ERP → Shopify Admin API) failing with `No space left on device` in logs.
- New sync jobs stall on affected nodes as the scheduler avoids placing work there, causing on-hand quantities to drift stale for the merchants assigned to those nodes.

## Diagnostic Steps
1. SSH into the affected node and run `df -h` to confirm which volume is full.
2. Run `du -sh /var/lib/inventory-sync/* | sort -rh | head -20` to find the largest consumers.
3. Check whether temp/intermediate files from failed or crashed sync jobs are being cleaned up (`/var/lib/inventory-sync/tmp`) — a common source is a partially-downloaded ERP feed file from a job that crashed mid-transfer.
4. Check log rotation config — a misconfigured or disabled log rotation is a common silent cause.
5. Check whether a specific merchant's feed is unusually large (e.g. a merchant with hundreds of thousands of SKUs across many locations doing a full re-sync instead of a delta sync — every SKU/location pair is a separate `InventoryLevel` record, so a full re-sync scales with variants × locations, not just SKU count).
6. Note: this is a distinct failure mode from `runbook_inventory_phantom_stock_overselling.md` — that runbook covers stale/wrong `available` quantities reaching Shopify; this one covers the worker infrastructure itself running out of room to process the feed at all. A node in this state may also be unable to push `inventorySetQuantities` calls, which can cascade into phantom stock if it persists — check that runbook too if disk pressure has lasted long enough to also produce staleness symptoms.

## Common Causes
- Log rotation disabled or misconfigured, letting application logs grow unbounded.
- Failed sync jobs leaving behind partial ERP feed files that are never cleaned up.
- A specific merchant's feed producing much larger output than expected (full catalog re-sync triggered instead of delta, or a malformed feed causing duplicate rows).
- Node-local cache/scratch space not being cleared between sync runs.

## Remediation Steps
1. **Immediate relief**: clear known-safe temp directories: `find /var/lib/inventory-sync/tmp -mtime +1 -delete`.
2. If log files are the culprit, compress and ship old logs off-node, then fix log rotation config (`logrotate -f /etc/logrotate.d/inventory-sync`).
3. If a specific merchant's feed is the cause, pause that merchant's sync job via the scheduler admin panel and investigate feed size/format before re-enabling.
4. Once disk usage drops below 70%, re-enable job scheduling on the node.
5. Add a Datadog monitor at 75% disk usage (warning) in addition to the existing 90% (critical) to give earlier warning next time.

## Escalation
- If clearing temp/logs doesn't free enough space and no single large consumer is identified, page the infrastructure on-call to consider volume expansion.
- See postmortem: `postmortem_2026-05-27_inventory_sync_disk_full.md`.
