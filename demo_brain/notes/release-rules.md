---
name: release-rules
description: "How dashboard changes are released: preview build, cache-busting keys, operator approval, then deploy"
tags: [område/dashboard]
metadata:
  type: project
  modified: 2026-10-21
---

Changes go to a preview URL first. Static assets carry a version key (?v=) so browsers do not serve stale files. The operator approves in chat, then the deploy runs. Rollback is the previous preview.

**Why:** keeps agents consistent across sessions.
**How to apply:** read before working in this area.
Related: [[working-style]] [[dashboard-data-sources]]
