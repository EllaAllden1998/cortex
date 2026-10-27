"""Scores the active pipeline against golden questions.

Answerable questions list the notes that hold the answer; unanswerable ones
expect a refusal. Offline by default (deterministic, free, runs in CI);
CORTEX_LIVE_MODELS=1 runs the same set against Claude and reports real cost.

    python -m evals.run_eval
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from cortex.graph import DEFAULT_GRAPH, compile_graph
from cortex.llm import default_models
from cortex.runtime import Runtime
from cortex.store import Store

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 27)   # pinned so note ages, and therefore results, do not drift


def evaluate(runtime: Runtime, plan) -> dict:
    cases = [json.loads(l) for l in (ROOT / "evals" / "golden.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = []
    for c in cases:
        r = runtime.run(plan, c["q"])
        expect = set(c["expect"])
        retrieved = {h for t in r.trace if t.kind == "retrieve" for h in t.detail.get("hits", [])}
        cited = {e.note_id for e in r.evidence} if r.outcome == "answered" else set()
        if expect:
            ok = r.outcome == "answered" and bool(cited & expect)
        else:
            ok = r.outcome == "refused"
        rows.append({"q": c["q"], "ok": ok, "outcome": r.outcome, "route": [s for s in r.route if s not in ("question", "retrieve")],
                     "recall": bool(retrieved & expect) if expect else None, "cited": sorted(cited), "cost": r.cost_usd})
    answerable = [r for r in rows if r["recall"] is not None]
    return {
        "cases": len(rows),
        "accuracy": round(sum(r["ok"] for r in rows) / len(rows), 3),
        "retrieval_recall": round(sum(r["recall"] for r in answerable) / len(answerable), 3),
        "refusal_correct": all(r["ok"] for r in rows if r["recall"] is None),
        "model_calls": sum("draft" in r["route"] for r in rows),
        "total_cost_usd": round(sum(r["cost"] for r in rows), 6),
        "rows": rows,
    }


def main():
    store = Store(ROOT / "demo_brain")
    report = evaluate(Runtime(store, default_models(), today=TODAY), compile_graph(DEFAULT_GRAPH))
    for r in report.pop("rows"):
        print(("PASS" if r["ok"] else "FAIL"), f"{r['outcome']:9}", " > ".join(r["route"])[:48].ljust(48), r["q"])
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
