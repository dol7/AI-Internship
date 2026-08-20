---
title: Storefront Custom Domain Certificate Expiry Outage
incident_id: INC-1071
service: storefront
severity: SEV2
date: 2026-07-01
duration: 26 minutes
tags: [tls, certificate, caa, dns, custom-domain, outage]
---

# Postmortem: Storefront Custom Domain Certificate Expiry Outage

## Summary
The Let's Encrypt-issued TLS certificate for a top-20 merchant's custom storefront domain failed to auto-renew because the merchant's security team added a CAA DNS record restricting certificate issuance to a different CA, unaware that this would silently block Shopify's automated Let's Encrypt renewal for their storefront domain.

## Impact
- Complete inability to load the affected merchant's storefront for 26 minutes — browsers rejected the connection outright due to the expired certificate.
- Checkout and Admin access for the merchant were on separate domains and unaffected.
- Estimated all active shopper sessions on that storefront during the window were unable to load new pages; the merchant reported abandoned carts in the immediate aftermath.

## Timeline (UTC)
- **(3 weeks prior)** — The merchant's security team adds a CAA record to their domain (`shop.merchantdomain.com. CAA 0 issue "digicert.com"`) as part of an unrelated vendor-consolidation policy, not realizing their storefront's SSL depends on Let's Encrypt issuance.
- **(3 weeks prior through incident)** — The next scheduled Let's Encrypt renewal attempt fails because the CAA record no longer authorizes `letsencrypt.org`. The renewal-failure alert was scoped to a specific error class and did not fire for CAA-rejection failures, so the failure went unnoticed for three weeks while the existing (still-valid) certificate continued serving traffic normally.
- **03:00** — The existing certificate reaches its expiry timestamp with no successful renewal behind it.
- **03:00** — Uptime monitors report SSL handshake failures; traffic drops to near-zero on the storefront dashboard for that domain.
- **03:04** — On-call paged by synthetic monitor failure.
- **03:09** — On-call confirms via `openssl s_client -issuer` that the certificate expired at 03:00 exactly, still showing Let's Encrypt as the last successful issuer.
- **03:12** — On-call runs `dig CAA shop.merchantdomain.com` and identifies the CAA record authorizing only `digicert.com`, blocking Let's Encrypt.
- **03:14** — On-call escalates to the merchant's technical contact to request an emergency CAA record correction, and in parallel requests a break-glass manual certificate from the domain/SSL platform team as an immediate stopgap.
- **03:22** — Break-glass certificate loaded, restoring traffic while the merchant's DNS fix propagates.
- **03:26** — Full traffic recovery confirmed; incident resolved. Merchant's CAA record corrected later that day, and normal Let's Encrypt auto-renewal resumed on schedule.

## Root Cause
Two independent failures compounded: (1) the merchant added a CAA record for an unrelated compliance reason without visibility into its effect on Shopify-managed SSL — this dependency was not documented anywhere merchant-facing, and (2) the renewal-failure alert was scoped too narrowly and did not fire for CAA-rejection specifically, so the silent failure went unnoticed for three weeks until the existing certificate actually expired.

## Resolution
Requested a break-glass manual certificate to restore service immediately while working with the merchant to correct their CAA record. Once the CAA record was updated to explicitly authorize `letsencrypt.org`, standard automated renewal resumed without further intervention.

## Action Items
1. Add a synthetic check alerting at 30/14/7 days before certificate expiry, independent of renewal automation health, for every custom domain on file. (Owner: infrastructure team, done 2026-07-03)
2. Broaden renewal-failure alerting to explicitly cover CAA-rejection as its own alertable failure mode, not lumped into a generic error class. (Owner: infrastructure team, done 2026-07-03)
3. Publish merchant-facing documentation explaining that any CAA record on a storefront domain must explicitly authorize `letsencrypt.org`, aimed at merchant security/IT teams who may add CAA records for unrelated reasons. (Owner: merchant success team, done 2026-07-10)
4. Add a periodic CAA-compliance check across all connected custom domains, flagging any domain whose CAA record would block renewal before the certificate is actually due to expire. (Owner: infrastructure team, done 2026-07-15)

## Lessons Learned
Silent automation failures are only as safe as the alerting covering them — an alert scoped to specific known failure modes will miss unanticipated ones, including ones triggered by a merchant's own DNS changes made for reasons entirely unrelated to SSL. A time-based backstop (expiry countdown) is a more robust safety net than trusting the automation's own health signal, and proactive CAA-compliance scanning catches this entire class of failure before it becomes an expiry event at all. See runbook: `runbook_tls_certificate_expiry.md`.
