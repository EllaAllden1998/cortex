"""Executes a compiled plan step by step and records a trace of every decision.

The trace is the product: for each step it says what ran, why a branch was
taken, what it cost and which notes it relied on, so an operator can audit an
answer without rerunning it.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date, datetime, timezone

from .graph import Plan
from .llm import Models
from .models import Event, Evidence, RunResult, TraceEvent
from .retrieval import Index, best_sentences
from .store import Store

CITE = re.compile(r"\[([a-z0-9-]+)\]")


class Runtime:
    def __init__(self, store: Store, models: Models, today: date | None = None):
        self.store = store
        self.models = models
        self.index = Index(list(store.notes.values()))
        self.today = today or date.today()

    def run(self, plan: Plan, question: str) -> RunResult:
        run_id = uuid.uuid4().hex[:10]
        started = datetime.now(timezone.utc)
        ctx: dict = {"evidence": [], "confidence": 0.0, "draft": None}
        taken: set[tuple[str, str]] = set()      # (source, target) edges that fired
        trace: list[TraceEvent] = []
        route: list[str] = []
        outcome, answer = "refused", None

        for step in plan.steps:
            active = step.kind == "input" or any((e.source, e.target) in taken for e in step.inputs)
            if not active:
                trace.append(TraceEvent(step=step.id, kind=step.kind, status="skipped", ms=0))
                continue
            t0 = time.perf_counter()
            status, cost, detail = "ok", 0.0, {}
            p = step.params

            if step.kind == "input":
                detail = {"question": question}
            elif step.kind == "retrieve":
                hits = self.index.search(question, p["k"])
                ctx["evidence"] = [Evidence(note_id=n.id, area=n.area, quote=best_sentences(question, n.body),
                                            score=round(s, 3), modified=n.modified,
                                            age_days=(self.today - n.modified).days) for n, s in hits]
                ctx["confidence"] = self.index.confidence(question, hits)
                detail = {"hits": [e.note_id for e in ctx["evidence"]], "confidence": ctx["confidence"]}
                for e in ctx["evidence"]:
                    self.store.append(Event(ts=datetime.now(timezone.utc), session=f"run:{run_id}", op="collect", note=e.note_id))
            elif step.kind == "gate":
                status = "pass" if ctx["confidence"] >= p["threshold"] else "fail"
                detail = {"confidence": ctx["confidence"], "threshold": p["threshold"]}
            elif step.kind == "extract":
                ev = ctx["evidence"]
                top = [e for e in ev[:2] if e.score >= .6 * ev[0].score]   # a weak runner-up adds noise, not support
                ctx["draft"] = " ".join(f"{e.quote} [{e.note_id}]" for e in top)
                detail = {"model": None, "note": "answered from the notes without a model call"}
            elif step.kind == "llm":
                ev = ctx["evidence"]
                notes = [(e.note_id, self.store.notes[e.note_id].body) for e in ev if e.score >= .5 * ev[0].score]
                c = self.models.complete(p["tier"], question, notes, p["max_tokens"])
                ctx["draft"] = None if "NOT_IN_BRAIN" in c.text else c.text
                cost = c.cost_usd
                detail = {"model": c.model, "offline": c.offline, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens}
            elif step.kind == "verify":
                status, detail = self._verify(ctx, p["max_age_days"])
            elif step.kind == "emit":
                outcome, answer = "answered", ctx["draft"]
            elif step.kind == "refuse":
                outcome, answer = "refused", None
                detail = {"reason": "not in the brain, or the answer could not be backed by fresh notes"}

            for e in step.outputs:
                if e.when == "always" or e.when == status:
                    taken.add((e.source, e.target))
            route.append(step.id)
            trace.append(TraceEvent(step=step.id, kind=step.kind, status=status,
                                    ms=round((time.perf_counter() - t0) * 1000, 2), cost_usd=cost, detail=detail))

        cited = set(CITE.findall(answer or ""))
        evidence = [e for e in ctx["evidence"] if e.note_id in cited] if outcome == "answered" else ctx["evidence"]
        return RunResult(run_id=run_id, graph_id=plan.graph_id, graph_version=plan.graph_version, plan_hash=plan.hash,
                         question=question, outcome=outcome, answer=answer, confidence=ctx["confidence"], route=route,
                         evidence=evidence, trace=trace, cost_usd=round(sum(t.cost_usd for t in trace), 6), started_at=started)

    @staticmethod
    def _verify(ctx: dict, max_age: int) -> tuple[str, dict]:
        draft = ctx["draft"]
        if not draft:
            return "fail", {"problem": "no draft"}
        known = {e.note_id: e for e in ctx["evidence"]}
        cited = CITE.findall(draft)
        unknown = sorted({c for c in cited if c not in known})
        stale = sorted({c for c in cited if c in known and known[c].age_days > max_age})
        problems = []
        if not cited:
            problems.append("no citations")
        if unknown:
            problems.append(f"cites notes that were not retrieved: {unknown}")
        if stale:
            problems.append(f"cites notes older than {max_age} days: {stale}")
        return ("fail" if problems else "pass"), {"citations": sorted(set(cited)), "problems": problems}
