# Cortex

A shared memory for a team of AI agents, with a compiled answer pipeline, cost gating, an auditable trace, and an agent that edits the pipeline only with human confirmation.

I run about a dozen Claude Code sessions in parallel across client projects. They share one "brain": a folder of one-fact-per-file Markdown notes that every session reads at start-up and writes back to when it learns something. Hooks log every read and write to an append-only event log, and a 3D view lights up the part of the brain being touched. My real brain holds 148 notes in 13 areas and has logged 3,312 reads and writes from 110 sessions. It contains client work, so this repository runs the same machinery on a fictional demo brain.

Cortex is the part I would show an engineer: the question-answering service that sits on top of that memory.

```
question → retrieve → cost gate ─pass→ extract ($0) ─┐
                         └fail→ worth a model? ─pass→ draft (Haiku 5.5) ─┤
                                         └fail→ refuse          verify ─pass→ emit (answer + evidence)
                                                                       └fail→ refuse
```

## What is in here

| Path | What it does |
|---|---|
| `cortex/graph.py` | Pipeline graphs and the **compiler**. It validates node kinds and parameters, branch edges, cycles, reachability, and dataflow (no model call without retrieval upstream). It prices the worst-case path against a budget, and emits a topologically ordered plan with a stable hash. It returns *all* errors at once with codes, so an LLM can repair its own proposal. |
| `cortex/runtime.py` | Executes a plan. Every step leaves a trace event: status, why a branch was taken, cost and time. Evidence reads go to the activity log like any other agent's. |
| `cortex/retrieval.py` | BM25 plus an explainable confidence score: the share of the question's content words found in the best note. The score costs nothing to compute, which is why it gates the model call. |
| `cortex/llm.py` | One interface for models: Claude (Haiku 5.5 for drafts, Opus 5.5 with server-side fallback for the strong tier) and a deterministic offline stand-in for CI and the public demo. The offline model is priced with the same table. |
| `cortex/agent.py` | Turns plain language into **typed graph edits** via structured outputs. It applies them to a copy and compiles it, then feeds compile errors back for up to 3 repair attempts. Deploying needs a human confirm and fails if the graph version moved (optimistic concurrency). |
| `cortex/app.py` | FastAPI: notes, events, stats, graph, compile, runs, proposals, confirm. |
| `evals/` | Golden questions, both answerable and unanswerable. Scores accuracy, retrieval recall, refusal correctness, model-call share and cost. |
| `tests/` | 20 tests: compiler failure modes, routing, stale-evidence refusal, the repair loop, the stale-deploy conflict, the API, and an eval regression gate. |
| `web/` | The showcase page. It runs on recorded runs from this code, or live against the API. |

## Run it

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # bin/ on macOS/Linux
python -m pytest -q
python -m evals.run_eval
uvicorn cortex.app:app --port 8000          # then open web/index.html
CORTEX_LIVE_MODELS=1 uvicorn cortex.app:app # real Claude calls (needs Anthropic credentials)
```

`python -m tools.export_web_data <path-to-real-brain>` rebuilds `web/data.js`. The only thing it reads from a real brain is counts.

## Decisions worth explaining

- **The model proposes operations, not graphs.** A whole graph from an LLM is hard to validate and hard to diff. A short list of `set_param` / `connect` / `remove_node` ops is easy to show a human, easy to apply to a copy, and the compiler's error codes give the repair loop something precise to work with.
- **Refusing is a first-class outcome.** If the retrieval score is too low, the run refuses for $0 without calling a model. The verifier also refuses any draft that cites a note that wasn't retrieved, or one older than the freshness limit.
- **Compile again at deploy time.** A proposal stores the compiled graph, but `confirm` compiles it again and checks the base version. A cached "it compiled" is not trusted.
- **The eval found a real bug.** On the first run, accuracy was 71 %. Note footers contain `[[links]]`, the quoted evidence picked them up, and the verifier correctly read them as citations to notes that were never retrieved. The fix went into the store (link lines are metadata), not into loosening the verifier.

## Limits, honestly

- The golden set is 17 questions I wrote alongside the demo notes. It is a regression gate, not a quality claim. With a live model, the next step would be sampling real questions from the activity log and grading with a rubric.
- State (runs, proposals, deployed graph) is in memory. In production, notes, events and runs belong in PostgreSQL, with a `workspace_id` on every row and row-level security policies, so one tenant's agent can never read another's notes, even through a bug in the API layer.
- "A human confirms" is enforced as a separate API call, but the demo API has no authentication, so anyone who can reach it can confirm. Hosted, `confirm` needs an authenticated operator identity, written into the deploy event.
- The live Claude path (`CORTEX_LIVE_MODELS=1`) is written against the current SDK docs, but CI runs only the offline stand-in.
- Retrieval is lexical. Past a few hundred notes I would add embeddings and keep BM25 as the cheap first stage.

## Credits

3D brain: Human Reference Atlas (HuBMAP) / Allen Human Reference Atlas 3D, 2020, CC BY 4.0, reduced to 162k triangles. Built with Claude Code. The architecture, rules and decisions are mine.
