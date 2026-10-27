"""Pipeline graphs and the compiler that turns one into an execution plan.

A graph is what a person (or the agent) draws: nodes with parameters and edges,
some of them conditional. The compiler refuses anything the runtime could not
execute safely, and returns *all* problems at once with machine-readable codes,
so an LLM proposing an edit can read the errors and repair its proposal.
"""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

NodeKind = Literal["input", "retrieve", "gate", "extract", "llm", "verify", "refuse", "emit"]
When = Literal["always", "pass", "fail"]

# What a model call can cost at most, per tier: (USD per input token, USD per output token, est. input tokens).
PRICES = {"cheap": (0.10e-6, 0.50e-6, 1500), "strong": (4.0e-6, 20.0e-6, 1500)}


class RetrieveParams(BaseModel, extra="forbid"):
    k: int = Field(4, ge=1, le=10)


class GateParams(BaseModel, extra="forbid"):
    threshold: float = Field(ge=0, le=1)


class LlmParams(BaseModel, extra="forbid"):
    tier: Literal["cheap", "strong"] = "cheap"
    max_tokens: int = Field(400, ge=50, le=4000)


class VerifyParams(BaseModel, extra="forbid"):
    max_age_days: int = Field(90, ge=1, le=3650)


class NoParams(BaseModel, extra="forbid"):
    pass


PARAMS: dict[str, type[BaseModel]] = {
    "input": NoParams, "retrieve": RetrieveParams, "gate": GateParams, "extract": NoParams,
    "llm": LlmParams, "verify": VerifyParams, "refuse": NoParams, "emit": NoParams,
}
BRANCHING = {"gate", "verify"}          # exactly one pass edge and one fail edge
TERMINAL = {"refuse", "emit"}
NEEDS_EVIDENCE = {"gate", "extract", "llm", "verify", "emit"}   # must have a retrieve upstream


class Node(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    kind: NodeKind
    params: dict = {}


class Edge(BaseModel):
    source: str
    target: str
    when: When = "always"


class Graph(BaseModel):
    id: str
    version: int = 1
    budget_usd: float = Field(0.05, gt=0)   # worst-case cost of one run
    nodes: list[Node]
    edges: list[Edge]


class CompileError(BaseModel):
    code: str
    message: str
    node: str | None = None


class Step(BaseModel):
    id: str
    kind: str
    params: dict
    inputs: list[Edge]     # the step runs if any of these edges is taken
    outputs: list[Edge]


class Plan(BaseModel):
    graph_id: str
    graph_version: int
    hash: str
    steps: list[Step]       # topological order
    worst_case_usd: float


class CompileFailed(Exception):
    def __init__(self, errors: list[CompileError]):
        super().__init__("; ".join(e.message for e in errors))
        self.errors = errors


def compile_graph(g: Graph) -> Plan:
    errs: list[CompileError] = []
    err = lambda code, msg, node=None: errs.append(CompileError(code=code, message=msg, node=node))

    ids = [n.id for n in g.nodes]
    for d in {i for i in ids if ids.count(i) > 1}:
        err("duplicate_node", f"node id '{d}' is used more than once", d)
    nodes = {n.id: n for n in g.nodes}

    params: dict[str, dict] = {}
    for n in g.nodes:
        try:
            params[n.id] = PARAMS[n.kind].model_validate(n.params).model_dump()
        except ValidationError as e:
            for x in e.errors():
                err("bad_param", f"{n.id}.{'.'.join(map(str, x['loc'])) or 'params'}: {x['msg']}", n.id)

    out: dict[str, list[Edge]] = {i: [] for i in nodes}
    inc: dict[str, list[Edge]] = {i: [] for i in nodes}
    for e in g.edges:
        bad = [x for x in (e.source, e.target) if x not in nodes]
        if bad:
            err("unknown_node", f"edge {e.source}->{e.target} refers to missing node {bad[0]}", bad[0])
            continue
        out[e.source].append(e)
        inc[e.target].append(e)

    inputs = [n.id for n in g.nodes if n.kind == "input"]
    if len(inputs) != 1:
        err("input_count", f"graph needs exactly one input node, found {len(inputs)}")

    for i, n in nodes.items():
        whens = sorted(e.when for e in out[i])
        if n.kind in BRANCHING and whens != ["fail", "pass"]:
            err("branch_edges", f"{i} ({n.kind}) needs exactly one 'pass' and one 'fail' edge, has {whens or 'none'}", i)
        if n.kind not in BRANCHING and any(w != "always" for w in whens):
            err("conditional_edge", f"{i} ({n.kind}) cannot have conditional edges", i)
        if n.kind not in BRANCHING | TERMINAL and len(out[i]) != 1:
            err("fan_out", f"{i} ({n.kind}) needs exactly one outgoing edge, has {len(out[i])}", i)
        if n.kind in TERMINAL and out[i]:
            err("terminal_has_edges", f"{i} ({n.kind}) ends a run and cannot have outgoing edges", i)
        if n.kind == "input" and inc[i]:
            err("input_has_edges", f"input {i} cannot have incoming edges", i)

    # Topological order (Kahn). Anything left over sits on a cycle.
    indeg = {i: len({e.source for e in inc[i]}) for i in nodes}
    ready = sorted(i for i, d in indeg.items() if d == 0)
    order: list[str] = []
    while ready:
        i = ready.pop(0)
        order.append(i)
        for t in sorted({e.target for e in out[i]}):
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
    for i in sorted(set(nodes) - set(order)):
        err("cycle", f"{i} is part of a cycle", i)

    if len(inputs) == 1 and not errs:
        reach, todo = set(), [inputs[0]]
        while todo:
            i = todo.pop()
            if i not in reach:
                reach.add(i)
                todo += [e.target for e in out[i]]
        for i in sorted(set(nodes) - reach):
            err("unreachable", f"{i} can never run: no path from the input", i)

        # Dataflow: on every path into a node that needs evidence, a retrieve must come first.
        has_ev = {}
        for i in order:
            preds = [e.source for e in inc[i]]
            has_ev[i] = nodes[i].kind == "retrieve" or (bool(preds) and all(has_ev[p] for p in preds))
            if nodes[i].kind in NEEDS_EVIDENCE and not (bool(preds) and all(has_ev[p] for p in preds)):
                err("no_evidence", f"{i} ({nodes[i].kind}) can be reached without a retrieve step before it", i)

    worst = 0.0
    if not errs:
        # Most expensive path through the DAG: model calls are the only cost.
        best: dict[str, float] = {}
        for i in order:
            own = 0.0
            if nodes[i].kind == "llm":
                pin, pout, est_in = PRICES[params[i]["tier"]]
                own = est_in * pin + params[i]["max_tokens"] * pout
            best[i] = own + max((best[e.source] for e in inc[i]), default=0.0)
        worst = round(max(best.values()), 6)
        if worst > g.budget_usd:
            err("over_budget", f"worst-case run costs ${worst:.4f}, budget is ${g.budget_usd:.4f}")

    if errs:
        raise CompileFailed(errs)

    steps = [Step(id=i, kind=nodes[i].kind, params=params[i], inputs=inc[i], outputs=out[i]) for i in order]
    canon = json.dumps([s.model_dump() for s in steps], sort_keys=True)
    return Plan(graph_id=g.id, graph_version=g.version, hash=hashlib.sha256(canon.encode()).hexdigest()[:12],
                steps=steps, worst_case_usd=worst)


DEFAULT_GRAPH = Graph(
    id="answer-with-evidence",
    nodes=[
        Node(id="question", kind="input"),
        Node(id="retrieve", kind="retrieve", params={"k": 4}),
        Node(id="confident", kind="gate", params={"threshold": 0.75}),
        Node(id="extract", kind="extract"),
        Node(id="worth_a_model", kind="gate", params={"threshold": 0.4}),
        Node(id="draft", kind="llm", params={"tier": "cheap", "max_tokens": 400}),
        Node(id="verify", kind="verify", params={"max_age_days": 90}),
        Node(id="emit", kind="emit"),
        Node(id="refuse", kind="refuse"),
    ],
    edges=[
        Edge(source="question", target="retrieve"),
        Edge(source="retrieve", target="confident"),
        Edge(source="confident", target="extract", when="pass"),
        Edge(source="confident", target="worth_a_model", when="fail"),
        Edge(source="worth_a_model", target="draft", when="pass"),
        Edge(source="worth_a_model", target="refuse", when="fail"),
        Edge(source="extract", target="verify"),
        Edge(source="draft", target="verify"),
        Edge(source="verify", target="emit", when="pass"),
        Edge(source="verify", target="refuse", when="fail"),
    ],
)
