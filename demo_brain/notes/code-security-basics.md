---
name: code-security-basics
description: "Security basics for the brain tooling: least privilege, no secrets in synced folders, hooks outside the sync"
tags: [område/kod]
metadata:
  type: reference
  modified: 2026-10-21
---

Scripts that run in every session live outside the synced folder, so a synced file cannot inject code. Secrets never enter the brain; the health check scans notes for key-like strings.

Related: [[brain-hooks]]
