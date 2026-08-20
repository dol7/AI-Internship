---
title: Inventory Sync Worker Disk Full
incident_id: INC-1049
service: inventory-sync
severity: SEV2
date: 2026-05-27
duration: 55 minutes
tags: [disk, storage, inventory, erp, logs]
---

# Postmortem: Inventory Sync Worker Disk Full

## Summary
Log rotation was silently disabled on a subset of inventory-sync worker nodes after a base image update, causing application logs to fill available disk space and halt multi-location inventory sync jobs on those nodes for 55 minutes.

## Impact
- 3 of 12 worker nodes stopped accepting new sync jobs due to full disks.
- Overall sync throughput dropped ~25% during the window; on-hand quantities for merchants assigned to those nodes went stale by up to 55 minutes but no sync jobs were lost — they queued and processed once capacity was restored.
- No incorrect inventory quantities were pushed to the Shopify Admin API; the failure mode was delayed sync, not corrupted sync.

## Timeline (UTC)
- **(9 days prior)** — Base worker image updated to a new OS version as part of routine patching; the update reset `/etc/logrotate.d/pipeline` to a default that didn't include the inventory-sync-specific rotation config, though this went unnoticed since disk fill takes time to manifest.
- **13:40** — Disk usage on 3 nodes crosses the 90% critical Datadog alert threshold.
- **13:44** — On-call pages, begins investigation.
- **13:50** — `df -h` and `du -sh` confirm application logs, not ERP feed data, are the primary disk consumer, growing unbounded.
- **13:55** — On-call confirms logrotate config is missing the inventory-sync-specific rule via `cat /etc/logrotate.d/inventory-sync` (file present but empty/default).
- **14:02** — On-call manually compresses and ships old logs off-node to free immediate space.
- **14:10** — Affected nodes drop below 70% disk usage; scheduler resumes placing sync jobs on them.
- **14:35** — Backlog of queued sync jobs from the affected nodes finishes draining; on-hand quantities caught up to current ERP state.

## Root Cause
A base image update overwrote the custom logrotate configuration with a default that excluded the inventory-sync application's log directory, and this was not caught because: (1) there was no explicit test or check for logrotate config presence post-image-update, and (2) the only disk alert was the 90% "critical" threshold, giving no early warning as usage grew gradually over 9 days.

## Resolution
Manually cleared and compressed logs to restore capacity immediately. Root fix restored the inventory-sync-specific logrotate config as part of the image build (baked in rather than applied post-boot, to survive future base image updates) and added a config-presence check to the node health check script.

## Action Items
1. Bake logrotate config into the custom image layer rather than applying it as a post-boot step. (Owner: inventory-sync team, done 2026-05-29)
2. Add a node health check verifying logrotate config presence and last-rotation timestamp. (Owner: inventory-sync team, done 2026-05-29)
3. Add a Datadog monitor at 75% disk usage (warning) in addition to the existing 90% (critical), to give earlier warning for slow-building issues. (Owner: SRE, done 2026-05-28)

## Lessons Learned
Slow-building resource issues (gradual disk fill over 9 days) are poorly served by a single high-threshold alert — a warning-level early signal would have surfaced this days before it became a scheduling-impacting incident, and on inventory-sync specifically, staleness has a direct merchant-facing cost (overselling risk if on-hand quantities lag ERP truth). See runbook: `runbook_disk_space_critical.md`.
