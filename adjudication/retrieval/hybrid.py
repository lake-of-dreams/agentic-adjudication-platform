"""BM25 + dense retrieval, fused with RRF, reranked with a cross-encoder.

BM25 is hand-rolled so k1/b stay visible and tunable. Formula and the reasoning
behind RRF over ranks: docs/guides/03-concepts.md.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Doc:
    doc_id: str
    text: str
    tokens: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = tokenize(self.text)


@dataclass
class BM25:
    docs: list[Doc]
    k1: float = 1.5
    b: float = 0.75
    _df: Counter = field(default_factory=Counter, init=False)
    _avgdl: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        for d in self.docs:
            self._df.update(set(d.tokens))
        self._avgdl = sum(len(d.tokens) for d in self.docs) / max(1, len(self.docs))

    def idf(self, term: str) -> float:
        n = len(self.docs)
        df = self._df.get(term, 0)
        # Robertson-Sparck-Jones IDF, +0.5 smoothing. max() keeps it non-negative
        # for terms that appear in most of the corpus.
        return max(0.0, math.log((n - df + 0.5) / (df + 0.5) + 1.0))

    def score(self, query: str, doc: Doc) -> float:
        tf = Counter(doc.tokens)
        dl = len(doc.tokens)
        total = 0.0
        for term in tokenize(query):
            f = tf.get(term, 0)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
            total += self.idf(term) * (f * (self.k1 + 1)) / denom
        return total

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        scored = [(d.doc_id, self.score(query, d)) for d in self.docs]
        scored = [s for s in scored if s[1] > 0]
        return sorted(scored, key=lambda s: -s[1])[:top_k]


@dataclass
class DenseIndex:
    """Bag-of-words vectors standing in for an embedding model, so fusion and
    reranking can be tested without a GPU. Swap the vectoriser for a real one and
    nothing downstream notices."""
    docs: list[Doc]

    @staticmethod
    def _vec(tokens: list[str]) -> dict[str, float]:
        c = Counter(tokens)
        norm = math.sqrt(sum(v * v for v in c.values())) or 1.0
        return {k: v / norm for k, v in c.items()}

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        q = self._vec(tokenize(query))
        out = []
        for d in self.docs:
            v = self._vec(d.tokens)
            small, large = (q, v) if len(q) < len(v) else (v, q)
            out.append((d.doc_id, sum(val * large.get(k, 0.0) for k, val in small.items())))
        return sorted([o for o in out if o[1] > 0], key=lambda s: -s[1])[:top_k]


def rrf(rankings: list[list[tuple[str, float]]], k: int = 60, top_k: int = 10) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. Ranks only, the scores are thrown away."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, (doc_id, _score) in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda s: -s[1])[:top_k]


def cross_encode(query: str, doc: Doc) -> float:
    """Stand-in cross-encoder: query-term coverage plus proximity.

    A real one scores the (query, document) pair jointly, which is why it cannot
    be pre-computed and only ever runs over the shortlist. Same two-stage shape
    here, without the model."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return 0.0
    positions = [i for i, t in enumerate(doc.tokens) if t in q_terms]
    coverage = len({doc.tokens[i] for i in positions}) / len(q_terms)
    if len(positions) < 2:
        return coverage
    spread = positions[-1] - positions[0] + 1
    proximity = len(positions) / spread
    return 0.7 * coverage + 0.3 * proximity


@dataclass
class HybridRetriever:
    docs: list[Doc]

    def __post_init__(self) -> None:
        self.bm25 = BM25(self.docs)
        self.dense = DenseIndex(self.docs)
        self._by_id = {d.doc_id: d for d in self.docs}

    def retrieve(self, query: str, top_k: int = 3, shortlist: int = 8) -> list[tuple[str, float]]:
        lexical = self.bm25.search(query, shortlist)
        semantic = self.dense.search(query, shortlist)
        fused = rrf([lexical, semantic], k=60, top_k=shortlist)
        reranked = [(doc_id, cross_encode(query, self._by_id[doc_id])) for doc_id, _ in fused]
        return sorted(reranked, key=lambda s: -s[1])[:top_k]
