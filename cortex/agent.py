"""The agent that edits pipeline graphs from plain language -- and never deploys on its own.

The model does not write a graph. It proposes a short list of typed edit
operations; the operations are applied to a copy, the copy is compiled, and any
compile errors are fed back for a bounded number of repair attempts. A proposal
that compiles waits for a human to confirm it, and confirmation fails if the
graph changed in the meantime (optimistic concurrency on the version number).
"""
from __future__ import annotations

import re
import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, ValidationError

from .graph import CompileError, CompileFailed, Edge, Graph, Node, compile_graph


class Op(BaseModel):
    op: Literal["add_node", "remove_node", "connect", "disconnect", "set_param"]
    node: str | None = None          # add_node / remove_node / set_param
    kind: str | None = None          # add_node
    key: str | None = None           # set_param
    value: float | int | str | None = None
    source: str | None = None        # connect / disconnect
    target: str | None = None
    when: Literal["always", "pass", "fail"] | None = None


class OpList(BaseModel):
    rationale: str
    ops: list[Op]


class Proposal(BaseModel):
    id: str
    instruction: str
    base_version: int
    rationale: str
    ops: list[Op]
    graph: Graph | None
    errors: list[CompileError]
    attempts: int
    planner: str
    status: Literal["pending", "deployed", "invalid", "stale"]


class OpError(Exception):
    pass


def apply_ops(g: Graph, ops: list[Op]) -> Graph:
    """Pure: returns a new graph one version up; raises OpError on an op that cannot apply."""
    nodes = {n.id: n.model_copy(deep=True) for n in g.nodes}
    edges = [e.model_copy() for e in g.edges]
    for o in ops:
        if o.op == "add_node":
            if not o.node or not o.kind or o.node in nodes:
                raise OpError(f"add_node needs a new node id and a kind (got {o.node!r}, {o.kind!r})")
            nodes[o.node] = Node(id=o.node, kind=o.kind)
        elif o.op == "remove_node":
            if o.node not in nodes:
                raise OpError(f"remove_node: no node {o.node!r}")
            del nodes[o.node]
            edges = [e for e in edges if o.node not in (e.source, e.target)]
        elif o.op == "set_param":
            if o.node not in nodes or not o.key:
                raise OpError(f"set_param: no node {o.node!r} or missing key")
            nodes[o.node].params = {**nodes[o.node].params, o.key: o.value}
        elif o.op == "connect":
            edges.append(Edge(source=o.source or "", target=o.target or "", when=o.when or "always"))
        elif o.op == "disconnect":
            before = len(edges)
            edges = [e for e in edges if not (e.source == o.source and e.target == o.target)]
            if len(edges) == before:
                raise OpError(f"disconnect: no edge {o.source}->{o.target}")
    return Graph(id=g.id, version=g.version + 1, budget_usd=g.budget_usd, nodes=list(nodes.values()), edges=edges)


class Planner(Protocol):
    name: str

    def plan(self, instruction: str, graph: Graph, feedback: list[str]) -> OpList: ...


class RulePlanner:
    """Offline stand-in for the model: handles a few common requests deterministically."""
    name = "offline-rules"

    def plan(self, instruction, graph, feedback):
        s = instruction.lower()
        num = re.search(r"(\d+(?:\.\d+)?)", s)
        ops: list[Op] = []
        if num and ("days" in s or "fresh" in s or "older" in s):
            v = next(n.id for n in graph.nodes if n.kind == "verify")
            ops.append(Op(op="set_param", node=v, key="max_age_days", value=int(float(num.group(1)))))
        elif num and ("threshold" in s or "confiden" in s or "strict" in s):
            x = float(num.group(1))
            ops.append(Op(op="set_param", node="confident", key="threshold", value=x / 100 if x > 1 else x))
        elif "strong" in s or "opus" in s or "better model" in s:
            ops.append(Op(op="set_param", node="draft", key="tier", value="strong"))
        elif "never" in s and ("model" in s or "llm" in s):
            ops += [Op(op="remove_node", node="draft"),
                    Op(op="connect", source="worth_a_model", target="refuse", when="pass")]
        return OpList(rationale="Matched a known edit pattern." if ops else "No known edit pattern matched.", ops=ops)


class ClaudePlanner:
    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5"):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def plan(self, instruction, graph, feedback):
        prompt = (f"Current pipeline graph (JSON):\n{graph.model_dump_json(indent=1)}\n\n"
                  f"Node kinds: input, retrieve(k), gate(threshold 0-1), extract, llm(tier cheap|strong, max_tokens), "
                  f"verify(max_age_days), refuse, emit. gate and verify need one 'pass' and one 'fail' edge; "
                  f"other non-terminal nodes need exactly one 'always' edge; refuse/emit end the run.\n\n"
                  f"Operator request: {instruction}\n\n"
                  "Propose the smallest list of edit operations that does what the operator asked. "
                  "If the request is unclear or unsafe, return no ops and say why in the rationale.")
        if feedback:
            prompt += "\n\nYour previous proposal did not compile:\n- " + "\n- ".join(feedback) + "\nFix it."
        resp = self.client.messages.parse(model=self.model, max_tokens=4000, output_config={"effort": "medium"},
                                          messages=[{"role": "user", "content": prompt}], output_format=OpList)
        return resp.parsed_output or OpList(rationale="The model returned no usable proposal.", ops=[])


def propose(instruction: str, graph: Graph, planner: Planner, max_attempts: int = 3) -> Proposal:
    feedback: list[str] = []
    out = OpList(rationale="", ops=[])
    errors: list[CompileError] = []
    candidate = None
    for attempt in range(1, max_attempts + 1):
        out = planner.plan(instruction, graph, feedback)
        if not out.ops:
            errors = [CompileError(code="no_ops", message=out.rationale)]
            break
        try:
            candidate = apply_ops(graph, out.ops)
            compile_graph(candidate)
            errors = []
            break
        except (OpError, ValidationError) as e:
            errors = [CompileError(code="bad_op", message=str(e).splitlines()[0] if isinstance(e, OpError) else
                                   "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))]
        except CompileFailed as e:
            errors = e.errors
        candidate = None
        feedback = [x.message for x in errors]
    return Proposal(id=uuid.uuid4().hex[:8], instruction=instruction, base_version=graph.version, rationale=out.rationale,
                    ops=out.ops, graph=candidate, errors=errors, attempts=attempt, planner=planner.name,
                    status="pending" if candidate else "invalid")
