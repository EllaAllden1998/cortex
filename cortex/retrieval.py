"""BM25 retrieval over notes, plus a confidence score the router can gate on.

Confidence is deliberately simple and explainable: the share of the question's
content words that the best note actually contains. It costs nothing to compute,
which is the point -- it decides whether a model call is needed at all.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .models import Note

STOP = set("""a an and are as at be by can do does for from has have how i in is it its my of on or our should
the their there this to was we what when where which who why will with you your about into than that them
then these they does did any all""".split())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


class Index:
    K1, B = 1.4, 0.75

    def __init__(self, notes: list[Note]):
        self.notes = notes
        # Slug and description say what the note is about, so they count double.
        self.docs = [terms(f"{n.id.replace('-', ' ')} {n.description} " * 2 + n.body) for n in notes]
        self.tf = [Counter(d) for d in self.docs]
        self.avg = sum(map(len, self.docs)) / max(1, len(self.docs))
        df = Counter(t for d in self.tf for t in d)
        N = len(notes)
        self.idf = {t: math.log(1 + (N - f + .5) / (f + .5)) for t, f in df.items()}

    def search(self, question: str, k: int) -> list[tuple[Note, float]]:
        q = set(terms(question))
        scored = []
        for n, tf, d in zip(self.notes, self.tf, self.docs):
            s = 0.0
            for t in q & tf.keys():
                f = tf[t]
                s += self.idf[t] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * len(d) / self.avg))
            if s > 0:
                scored.append((n, s))
        scored.sort(key=lambda x: (-x[1], x[0].id))
        return scored[:k]

    def confidence(self, question: str, hits: list[tuple[Note, float]]) -> float:
        q = set(terms(question))
        if not q or not hits:
            return 0.0
        return round(len(q & self.tf[self.notes.index(hits[0][0])].keys()) / len(q), 3)


def best_sentences(question: str, text: str, n: int = 2) -> str:
    q = set(terms(question))
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    ranked = sorted(sents, key=lambda s: -len(q & set(terms(s))))
    keep = [s for s in sents if s in ranked[:n]]   # original order reads better
    return " ".join(keep)
