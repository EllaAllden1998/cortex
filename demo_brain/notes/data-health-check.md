---
name: data-health-check
description: "The data health card: freshness per source, row counts vs. last week, and alerts on silent drops"
tags: [område/dashboard]
metadata:
  type: project
  modified: 2026-10-22
---

The card compares today's row count per source with the 7-day median. A drop over 40 % or a missing day raises an alert. Silent failures, not crashes, were the most common incident type.

**Why:** keeps agents consistent across sessions.
**How to apply:** read before working in this area.
Related: [[dashboard-data-sources]]
