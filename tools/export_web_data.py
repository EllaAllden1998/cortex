"""Builds web/data.js for the static showcase page.

Everything the page shows offline comes from running the real service code:
demo notes and events, the compiled default plan, recorded runs for the preset
questions, a recorded agent proposal and the eval report. The only thing taken
from the private brain is a handful of counts (never names or content).

    python -m tools.export_web_data [path-to-real-brain]
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from cortex.agent import RulePlanner, propose
from cortex.graph import DEFAULT_GRAPH, compile_graph
from cortex.llm import OfflineModels
from cortex.runtime import Runtime
from cortex.store import Store
from evals.run_eval import TODAY, evaluate

ROOT = Path(__file__).resolve().parent.parent

AREAS = {   # key: (public label, colour) -- keys match the anatomy baked into brain-lite.js
    "kvalitet": ("Quality", "#e15759"), "samarbete": ("Collaboration", "#f28e2b"),
    "dashboard": ("Dashboard", "#4e79a7"), "hemsida": ("Website", "#76b7b2"),
    "presentationer": ("Design", "#b07aa1"), "sms": ("Clients", "#59a14f"),
    "lokaler": ("Venues", "#edc948"), "projekt": ("Future projects", "#ff8fd0"),
    "verktyg": ("Tools & routines", "#9c755f"), "bolaget": ("Company", "#9aa5b1"),
    "growth": ("Growth", "#8f7ae6"), "kod": ("Code", "#2fe0b0"), "seo": ("SEO", "#b5e550"),
}
PRESETS = [
    "How are dashboard changes released?",
    "When may an agent say something is verified?",
    "Should we A/B test with under 1000 visitors a month?",
    "Why do the hook scripts live outside the synced folder?",
    "What is the capital of Australia?",
]


def real_counts(brain: Path) -> dict:
    events = []
    for line in (brain / "_system" / "activity.jsonl").read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    ops = Counter(e.get("op") for e in events)
    notes = list((brain / "notes").glob("*.md"))
    areas = {l.split("område/")[1].split("]")[0].split(",")[0].strip()
             for p in notes for l in p.read_text(encoding="utf-8", errors="replace").splitlines()[:8] if "område/" in l}
    return {"notes": len(notes), "areas": len(areas), "events": len(events), "reads": ops["collect"], "writes": ops["push"],
            "sessions": len({e.get("session") for e in events}), "days": len({str(e.get("ts", ""))[:10] for e in events}),
            "since": min(str(e.get("ts", "9"))[:10] for e in events)}


def main():
    store = Store(ROOT / "demo_brain")
    rt = Runtime(store, OfflineModels(), today=TODAY)
    plan = compile_graph(DEFAULT_GRAPH)
    runs = {q: json.loads(rt.run(plan, q).model_dump_json()) for q in PRESETS}
    store = Store(ROOT / "demo_brain")            # fresh log: recorded runs should not pollute the replayed feed
    report = evaluate(Runtime(Store(ROOT / "demo_brain"), OfflineModels(), today=TODAY), plan)
    proposal = propose("Only trust notes newer than 30 days", DEFAULT_GRAPH, RulePlanner())
    data = {
        "areas": {k: {"label": label, "color": color} for k, (label, color) in AREAS.items()},
        "notes": [n.model_dump(mode="json", exclude={"body"}) | {"body": n.body} for n in store.notes.values()],
        "events": [e.model_dump(mode="json") for e in store.events],
        "graph": json.loads(DEFAULT_GRAPH.model_dump_json()),
        "plan": json.loads(plan.model_dump_json()),
        "presets": PRESETS, "runs": runs,
        "proposal": json.loads(proposal.model_dump_json()),
        "eval": report,
        "real": real_counts(Path(sys.argv[1])) if len(sys.argv) > 1 else None,
    }
    out = ROOT / "web" / "data.js"
    out.write_text("window.CORTEX = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(f"wrote {out.name}: {out.stat().st_size // 1024} KB; real counts: {data['real']}")


if __name__ == "__main__":
    main()
