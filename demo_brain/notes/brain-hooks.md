---
name: brain-hooks
description: "The hooks that feed the brain: SessionStart auto-load, PostToolUse event log, Stop reminder to save lessons"
tags: [område/verktyg]
metadata:
  type: reference
  modified: 2026-10-21
---

SessionStart injects the working rules plus the notes for the folder's area. PostToolUse appends every brain read/write to activity.jsonl. Stop asks the session to save what it learned after a few turns.

Related: [[code-security-basics]] [[scheduled-routines]]
