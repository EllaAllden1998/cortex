"""One interface in front of every model the runtime can call.

`AnthropicModels` calls Claude. `OfflineModels` is a deterministic stand-in so
tests, evals and the public demo run without a key; it reports token usage
estimates with the same price table, and every trace says which one ran.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from .graph import PRICES
from .retrieval import best_sentences

MODEL_IDS = {"cheap": "claude-haiku-5-5", "strong": "claude-opus-5-5"}

SYSTEM = (
    "You answer questions about an operator's shared memory using only the notes provided. "
    "Cite every claim with the note id in square brackets, e.g. [working-style]. "
    "If the notes do not answer the question, reply exactly: NOT_IN_BRAIN. Two to three sentences."
)


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    offline: bool

    @property
    def cost_usd(self) -> float:
        tier = next(t for t, m in MODEL_IDS.items() if m == self.model)
        pin, pout, _ = PRICES[tier]
        return round(self.input_tokens * pin + self.output_tokens * pout, 6)


class Models(Protocol):
    def complete(self, tier: str, question: str, notes: list[tuple[str, str]], max_tokens: int) -> Completion: ...


def render(question: str, notes: list[tuple[str, str]]) -> str:
    docs = "\n\n".join(f'<note id="{i}">\n{text}\n</note>' for i, text in notes)
    return f"{docs}\n\nQuestion: {question}"


class OfflineModels:
    def complete(self, tier, question, notes, max_tokens):
        parts = [f"{best_sentences(question, text, 1)} [{i}]" for i, text in notes[:2]]
        text = " ".join(parts) or "NOT_IN_BRAIN"
        prompt = render(question, notes)
        return Completion(text=text, model=MODEL_IDS[tier], input_tokens=len(prompt) // 4 + len(SYSTEM) // 4,
                          output_tokens=len(text) // 4, offline=True)


class AnthropicModels:
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic()

    def complete(self, tier, question, notes, max_tokens):
        model = MODEL_IDS[tier]
        kwargs = dict(model=model, max_tokens=max_tokens, system=SYSTEM,
                      messages=[{"role": "user", "content": render(question, notes)}],
                      output_config={"effort": "low"})
        if tier == "strong":
            # Server-side fallback: a policy decline is re-run on a fallback model inside the same call.
            msg = self.client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            msg = self.client.messages.create(**kwargs)
        if msg.stop_reason == "refusal":
            text = "NOT_IN_BRAIN"
        else:
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return Completion(text=text, model=model, input_tokens=msg.usage.input_tokens,
                          output_tokens=msg.usage.output_tokens, offline=False)


def default_models() -> Models:
    return AnthropicModels() if os.environ.get("CORTEX_LIVE_MODELS") == "1" else OfflineModels()
