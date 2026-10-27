---
name: whole-chain-checks
description: "Every data flow is checked end to end: source, database, dashboard, plus dependencies"
tags: [område/kvalitet]
metadata:
  type: feedback
  modified: 2026-10-21
---

A fix is not done when the code compiles. Follow the value from the source API through the ingest job and the database row to the number on screen, and check the jobs that depend on it.

**Why:** keeps agents consistent across sessions.
**How to apply:** read before working in this area.
Related: [[never-overstate]] [[dashboard-data-sources]]
