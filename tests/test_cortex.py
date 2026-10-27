from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cortex.agent import Op, OpList, RulePlanner, apply_ops, propose
from cortex.app import create_app
from cortex.graph import DEFAULT_GRAPH, CompileFailed, Edge, Graph, Node, compile_graph
from cortex.llm import OfflineModels
from cortex.runtime import Runtime
from cortex.store import Store
from evals.run_eval import evaluate

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 27)


@pytest.fixture
def store():
    return Store(ROOT / "demo_brain")


@pytest.fixture
def runtime(store):
    return Runtime(store, OfflineModels(), today=TODAY)


def codes(g: Graph) -> set[str]:
    with pytest.raises(CompileFailed) as e:
        compile_graph(g)
    return {x.code for x in e.value.errors}


def edit(**changes) -> Graph:
    g = DEFAULT_GRAPH.model_copy(deep=True)
    for k, v in changes.items():
        setattr(g, k, v)
    return g


# ---- compiler ----

def test_default_graph_compiles_in_topological_order():
    plan = compile_graph(DEFAULT_GRAPH)
    order = [s.id for s in plan.steps]
    for e in DEFAULT_GRAPH.edges:
        assert order.index(e.source) < order.index(e.target)
    assert plan.worst_case_usd > 0 and len(plan.hash) == 12


def test_plan_hash_is_stable_and_changes_with_params():
    a, b = compile_graph(DEFAULT_GRAPH), compile_graph(DEFAULT_GRAPH)
    assert a.hash == b.hash
    g = apply_ops(DEFAULT_GRAPH, [Op(op="set_param", node="confident", key="threshold", value=.9)])
    assert compile_graph(g).hash != a.hash


def test_cycle_is_rejected():
    g = edit(edges=DEFAULT_GRAPH.edges + [Edge(source="verify", target="retrieve", when="pass")])
    assert "cycle" in codes(g) or "branch_edges" in codes(g)


def test_gate_needs_both_branches():
    g = edit(edges=[e for e in DEFAULT_GRAPH.edges if not (e.source == "confident" and e.when == "fail")])
    assert "branch_edges" in codes(g)


def test_unknown_kind_and_bad_params_are_reported_together():
    with pytest.raises(Exception):
        Node(id="x", kind="teleport")
    nodes = [n if n.id != "retrieve" else Node(id="retrieve", kind="retrieve", params={"k": 99, "extra": 1}) for n in DEFAULT_GRAPH.nodes]
    assert codes(edit(nodes=nodes)) == {"bad_param"}


def test_model_call_without_retrieval_is_rejected():
    g = Graph(id="t", nodes=[Node(id="q", kind="input"), Node(id="m", kind="llm"), Node(id="v", kind="verify"),
                             Node(id="e", kind="emit"), Node(id="r", kind="refuse")],
              edges=[Edge(source="q", target="m"), Edge(source="m", target="v"),
                     Edge(source="v", target="e", when="pass"), Edge(source="v", target="r", when="fail")])
    assert "no_evidence" in codes(g)


def test_unreachable_node_is_rejected():
    g = edit(nodes=DEFAULT_GRAPH.nodes + [Node(id="orphan", kind="emit")])
    assert "unreachable" in codes(g)


def test_budget_is_enforced_on_worst_case_path():
    g = apply_ops(DEFAULT_GRAPH, [Op(op="set_param", node="draft", key="tier", value="strong"),
                                  Op(op="set_param", node="draft", key="max_tokens", value=4000)])
    assert "over_budget" in codes(g)


# ---- runtime ----

def test_confident_question_is_answered_without_a_model(runtime):
    r = runtime.run(compile_graph(DEFAULT_GRAPH), "How are dashboard changes released?")
    assert r.outcome == "answered" and "draft" not in r.route and r.cost_usd == 0
    assert "release-rules" in {e.note_id for e in r.evidence}


def test_out_of_scope_question_is_refused_for_free(runtime):
    r = runtime.run(compile_graph(DEFAULT_GRAPH), "What is the capital of Australia?")
    assert r.outcome == "refused" and r.answer is None and r.cost_usd == 0


def test_every_cited_note_was_retrieved(runtime):
    plan = compile_graph(DEFAULT_GRAPH)
    for q in ["When may an agent say something is verified?", "What is our north star metric?"]:
        r = runtime.run(plan, q)
        hits = {h for t in r.trace if t.kind == "retrieve" for h in t.detail["hits"]}
        assert {e.note_id for e in r.evidence} <= hits


def test_stale_evidence_is_refused(store):
    rt = Runtime(store, OfflineModels(), today=date(2027, 6, 1))   # every note now older than 90 days
    r = rt.run(compile_graph(DEFAULT_GRAPH), "How are dashboard changes released?")
    assert r.outcome == "refused"
    v = next(t for t in r.trace if t.kind == "verify")
    assert v.status == "fail" and "older than" in v.detail["problems"][0]


def test_runs_are_written_to_the_activity_log(store, runtime):
    before = len(store.events)
    r = runtime.run(compile_graph(DEFAULT_GRAPH), "What is our north star metric?")
    assert len(store.events) > before and store.events[-1].session == f"run:{r.run_id}"


def test_eval_regression_gate(runtime):
    report = evaluate(runtime, compile_graph(DEFAULT_GRAPH))
    assert report["accuracy"] >= .9 and report["refusal_correct"]
    assert report["model_calls"] <= report["cases"] // 3     # the cost gate must keep most questions off the model


# ---- agent ----

def test_rule_planner_proposal_compiles_and_bumps_version():
    p = propose("Only trust notes newer than 30 days", DEFAULT_GRAPH, RulePlanner())
    assert p.status == "pending" and p.graph.version == DEFAULT_GRAPH.version + 1
    assert next(n for n in p.graph.nodes if n.id == "verify").params["max_age_days"] == 30


class BrokenThenFixed:
    """Proposes an invalid edit first, then repairs it from the compiler's feedback."""
    name = "fake"

    def __init__(self):
        self.feedback = []

    def plan(self, instruction, graph, feedback):
        self.feedback.append(feedback)
        if not feedback:
            return OpList(rationale="first try", ops=[Op(op="disconnect", source="confident", target="worth_a_model")])
        return OpList(rationale="fixed", ops=[Op(op="set_param", node="confident", key="threshold", value=.8)])


def test_compile_errors_are_fed_back_for_repair():
    planner = BrokenThenFixed()
    p = propose("make it stricter", DEFAULT_GRAPH, planner)
    assert p.status == "pending" and p.attempts == 2
    assert any("pass" in m for m in planner.feedback[1])


def test_invalid_ops_never_produce_a_graph():
    class Bad:
        name = "bad"
        def plan(self, *a):
            return OpList(rationale="x", ops=[Op(op="add_node", node="Bad Id!", kind="emit")])
    p = propose("x", DEFAULT_GRAPH, Bad(), max_attempts=2)
    assert p.status == "invalid" and p.graph is None and p.errors[0].code == "bad_op"


# ---- API ----

@pytest.fixture
def client(store, runtime):
    return TestClient(create_app(store, runtime, RulePlanner()))


def test_api_run_and_fetch(client):
    r = client.post("/runs", json={"question": "What is our north star metric?"}).json()
    assert r["outcome"] == "answered"
    assert client.get(f"/runs/{r['run_id']}").json()["plan_hash"] == r["plan_hash"]


def test_api_compile_returns_all_errors(client):
    bad = DEFAULT_GRAPH.model_dump()
    bad["edges"] = [e for e in bad["edges"] if e["source"] != "confident"]
    res = client.post("/graph/compile", json=bad)
    assert res.status_code == 422 and {"branch_edges", "unreachable"} & {e["code"] for e in res.json()["detail"]["errors"]}


def test_api_deploy_needs_confirmation_and_rejects_stale(client):
    v0 = client.get("/graph").json()["graph"]["version"]
    a = client.post("/agent/proposals", json={"instruction": "require confidence 90"}).json()
    b = client.post("/agent/proposals", json={"instruction": "only notes newer than 30 days"}).json()
    assert client.get("/graph").json()["graph"]["version"] == v0          # nothing deployed yet
    assert client.post(f"/agent/proposals/{a['id']}/confirm").status_code == 200
    assert client.post(f"/agent/proposals/{b['id']}/confirm").status_code == 409   # built on the old version
    assert client.get("/graph").json()["graph"]["version"] == v0 + 1
