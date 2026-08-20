---
title: Storefront Custom Domain Certificate Expiry
service: storefront
component: managed-ssl
tags: [tls, certificate, custom-domain, caa, dns, outage, oncall]
last_updated: 2026-07-05
---

# Runbook: Storefront Custom Domain Certificate Expiry

## Background
Custom domain SSL is auto-provisioned and auto-renewed via **Let's Encrypt**, not a self-managed cert-manager/ACME pipeline. Provisioning normally completes within minutes, but can take up to **48 hours** depending on DNS propagation. There is no manual "our team issues the cert" step in the normal path — most incidents in this space are a merchant-side DNS/CAA misconfiguration blocking Shopify's automated issuance, not an internal automation failure.

## Symptoms
- Browsers show `NET::ERR_CERT_DATE_INVALID` or equivalent for a merchant's custom storefront domain.
- Admin → Settings → Domains shows an "SSL unavailable" warning for the domain.
- Complete traffic drop-off for the affected domain in the Datadog `storefront-traffic` dashboard (browsers refuse to connect, no request even reaches the server).
- Uptime monitors (Pingdom/Datadog Synthetics) report SSL handshake failures, not HTTP errors, scoped to that one custom domain.
- Distinct symptom, not a cert failure: **mixed content warnings** (padlock shows but browser flags insecure content) — this means SSL is fine but the theme has hardcoded `http://` asset links; do not treat as a certificate incident.
- Distinct symptom, not a cert failure: **redirect loop** on an otherwise-valid cert — usually a conflicting proxy in front of the domain (see Cloudflare cause below), not an expiry issue.

## Diagnostic Steps
1. Check certificate status directly: `echo | openssl s_client -connect shop.merchantdomain.com:443 2>/dev/null | openssl x509 -noout -dates -issuer`. Confirm the issuer is `Let's Encrypt` — a different issuer means the cert was provisioned outside the normal path (e.g. during a migration) and may not be tracked for auto-renewal the same way.
2. Check DNS propagation for the domain: confirm the A/CNAME record correctly points to Shopify's servers via `dig shop.merchantdomain.com`.
3. **Check for a blocking CAA record**: `dig CAA shop.merchantdomain.com`. If any CAA record exists, it must explicitly include `letsencrypt.org` as an authorized issuer, e.g. `shop.merchantdomain.com. CAA 0 issue "letsencrypt.org"`. A CAA record that only authorizes a different CA (common when a merchant's security/compliance team hardens DNS) silently blocks all future Let's Encrypt issuance and renewal.
4. Check whether the merchant is running the domain through **Cloudflare (or another proxy) in full-proxy/orange-cloud mode**. Shopify needs to terminate SSL directly — a proxied domain intercepts the connection before Shopify's provisioning can complete, and can also cause redirect loops on an otherwise-valid cert.
5. Check when the domain was last connected/disconnected/reconnected in Admin → Settings → Domains — a disconnect-reconnect cycle restarts the provisioning window and can explain an in-progress "SSL unavailable" state that isn't actually broken, just still within the up-to-48-hour window.

## Common Causes
- A CAA record added or changed (often by a merchant's own IT/security team, unannounced) that doesn't authorize `letsencrypt.org`, silently blocking renewal until corrected.
- DNS not fully propagated yet, or reverted mid-propagation by a merchant-side change.
- Domain proxied through Cloudflare or a similar service in full-proxy mode instead of DNS-only ("grey cloud"), preventing Shopify from completing SSL termination.
- A cert issued manually outside the normal flow during a migration, not tracked by the standard renewal path.

## Remediation Steps
1. **If a CAA record is the cause**: work with the merchant (or their DNS admin) to add or correct the CAA record to explicitly authorize `letsencrypt.org`. Provisioning typically resumes automatically within the normal window once the record is fixed — there is usually no need to force anything on our side.
2. **If Cloudflare/proxy mode is the cause**: have the merchant switch the domain's DNS record to DNS-only (grey cloud, not orange/proxied) so Shopify can terminate SSL directly.
3. **If DNS is simply still propagating**: this is expected within the 48-hour window; confirm propagation status and set merchant expectations rather than treating it as an incident.
4. **If none of the above and the domain is fully correctly configured but still failing**: escalate to Shopify's domain/SSL platform team for manual investigation — this is the genuine "our automation is broken" case, not a merchant-config case, and is comparatively rare.
5. Verify recovery: repeat the `openssl s_client` check from diagnostics and confirm issuer is `Let's Encrypt` with a valid, current expiry date.

## Escalation
- If a CAA or DNS fix has been confirmed correct but provisioning still hasn't completed after the full 48-hour window, escalate to the domain/SSL platform team — this is now a genuine platform-side issue, not a merchant misconfiguration.
- See postmortem: `postmortem_2026-07-01_storefront_cert_expiry.md`.
