"""Loads a brain folder (notes/*.md + events.jsonl) into memory.

Frontmatter is parsed by hand: the notes use a small, fixed subset of YAML and
this keeps the service free of a YAML dependency.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .models import Event, Note

LINK = re.compile(r"\[\[([^\]]+)\]\]")


def parse_note(text: str, slug: str) -> Note:
    if not text.startswith("---"):
        raise ValueError(f"{slug}: missing frontmatter")
    head, body = text[3:].split("\n---", 1)
    fields: dict[str, str] = {}
    for line in head.splitlines():
        m = re.match(r"\s*([a-z_]+):\s*(.*)$", line)
        if m and m.group(2):
            fields[m.group(1)] = m.group(2).strip().strip('"')
    area = re.search(r"område/([a-z]+)", fields.get("tags", ""))
    # Link lines and the Why/How footer are metadata; keeping them out of the body keeps
    # them out of retrieval and out of quoted evidence (a quoted [[link]] reads as a citation).
    content = [l for l in body.strip().splitlines() if not re.match(r"\s*(Related:|\*\*Why:\*\*|\*\*How to apply:\*\*)", l)]
    return Note(
        id=fields.get("name", slug),
        area=area.group(1) if area else "okategoriserat",
        type=fields.get("type", "reference"),
        description=fields.get("description", ""),
        body=LINK.sub(lambda m: m.group(1), "\n".join(content)).strip(),
        links=sorted(set(LINK.findall(body))),
        modified=date.fromisoformat(fields["modified"]) if "modified" in fields else date.min,
    )


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.notes: dict[str, Note] = {}
        for p in sorted((self.root / "notes").glob("*.md")):
            n = parse_note(p.read_text(encoding="utf-8"), p.stem)
            self.notes[n.id] = n
        self.events: list[Event] = []
        log = self.root / "events.jsonl"
        if log.exists():
            for line in log.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    self.events.append(Event.model_validate(json.loads(line)))

    def append(self, event: Event) -> None:
        """Runs are audited like any other agent: each evidence read is logged."""
        self.events.append(event)
