"""HTTP API: notes, the activity log, the active pipeline, runs, and agent proposals.

Run:  uvicorn cortex.app:app --port 8000
"""
from __future__ import annotations

import os
import threading
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .agent import ClaudePlanner, Proposal, RulePlanner, propose
from .graph import DEFAULT_GRAPH, CompileFailed, Graph, Plan, compile_graph
from .llm import default_models
from .models import RunRequest, RunResult
from .runtime import Runtime
from .store import Store

BRAIN = Path(os.environ.get("CORTEX_BRAIN", Path(__file__).resolve().parent.parent / "demo_brain"))


class InstructionRequest(BaseModel):
    instruction: str


def create_app(store: Store | None = None, runtime: Runtime | None = None, planner=None) -> FastAPI:
    store = store or Store(BRAIN)
    runtime = runtime or Runtime(store, default_models())
    live = os.environ.get("CORTEX_LIVE_MODELS") == "1"
    planner = planner or (ClaudePlanner() if live else RulePlanner())
    state = {"graph": DEFAULT_GRAPH, "plan": compile_graph(DEFAULT_GRAPH)}
    runs: dict[str, RunResult] = {}
    proposals: dict[str, Proposal] = {}
    lock = threading.Lock()   # deploys swap graph + plan together

    app = FastAPI(title="Cortex", version="1.0",
                  description="A shared memory for AI agents, with a compiled answer pipeline and an auditable trace.")
    # Read-mostly demo API, opened for the static showcase page (file:// sends Origin: null).
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/health")
    def health():
        return {"ok": True, "notes": len(store.notes), "events": len(store.events), "live_models": live}

    @app.get("/notes")
    def notes():
        return [n.model_dump(exclude={"body"}) for n in store.notes.values()]

    @app.get("/notes/{note_id}")
    def note(note_id: str):
        if note_id not in store.notes:
            raise HTTPException(404, f"no note {note_id!r}")
        return store.notes[note_id]

    @app.get("/events")
    def events(limit: int = 100, session: str | None = None):
        ev = [e for e in store.events if session is None or e.session == session]
        return ev[-min(max(limit, 1), 1000):]

    @app.get("/stats")
    def stats():
        ops = Counter(e.op for e in store.events)
        return {"notes": len(store.notes), "areas": len({n.area for n in store.notes.values()}),
                "events": len(store.events), "reads": ops["collect"], "writes": ops["push"],
                "sessions": len({e.session for e in store.events}), "runs": len(runs)}

    @app.get("/graph")
    def graph() -> dict:
        return {"graph": state["graph"], "plan": state["plan"]}

    @app.post("/graph/compile")
    def compile_endpoint(g: Graph) -> Plan:
        try:
            return compile_graph(g)
        except CompileFailed as e:
            raise HTTPException(422, {"errors": [x.model_dump() for x in e.errors]})

    @app.post("/runs")
    def run(req: RunRequest) -> RunResult:
        result = runtime.run(state["plan"], req.question)
        runs[result.run_id] = result
        return result

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> RunResult:
        if run_id not in runs:
            raise HTTPException(404, f"no run {run_id!r}")
        return runs[run_id]

    @app.post("/agent/proposals")
    def make_proposal(req: InstructionRequest) -> Proposal:
        p = propose(req.instruction, state["graph"], planner)
        proposals[p.id] = p
        return p

    @app.post("/agent/proposals/{pid}/confirm")
    def confirm(pid: str) -> dict:
        p = proposals.get(pid)
        if not p:
            raise HTTPException(404, f"no proposal {pid!r}")
        with lock:
            if p.status != "pending":
                raise HTTPException(409, f"proposal is {p.status}")
            if p.base_version != state["graph"].version:
                p.status = "stale"
                raise HTTPException(409, f"graph changed since the proposal (v{p.base_version} -> v{state['graph'].version}); propose again")
            plan = compile_graph(p.graph)            # compile again at deploy time, never trust a cached result
            state["graph"], state["plan"] = p.graph, plan
            p.status = "deployed"
        return {"deployed_version": plan.graph_version, "plan_hash": plan.hash}

    return app


app = create_app()
