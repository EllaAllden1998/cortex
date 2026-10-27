---
name: dashboard-data-sources
description: "Where the client dashboard gets its numbers: GA4, Search Console, LinkedIn Ads, CRM, nightly ingest jobs"
tags: [område/dashboard]
metadata:
  type: reference
  modified: 2026-10-24
---

Five sources feed the dashboard. Nightly edge functions pull GA4, Search Console and LinkedIn Ads into Postgres; the CRM syncs hourly. Each table has a freshness check; a source older than 36 hours turns the health card amber.

Related: [[release-rules]] [[whole-chain-checks]] [[data-health-check]]
