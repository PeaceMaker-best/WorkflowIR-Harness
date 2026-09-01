from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


NODE_BLOCK_RE = re.compile(
    r"(?ms)^- Node:\s*(?P<name>[^\n]+)\n(?P<body>.*?)(?=^- Node:|^## Output Format)"
)


@dataclass(frozen=True)
class NodeCard:
    name: str
    node_type: str
    description: str
    full_schema: str

    @property
    def summary(self) -> str:
        return f"{self.node_type}: {self.description.strip()}"


def parse_node_catalog(builder_prompt: str) -> List[NodeCard]:
    cards: List[NodeCard] = []
    for match in NODE_BLOCK_RE.finditer(builder_prompt):
        body = match.group("body")
        type_match = re.search(r"<type>(.*?)</type>", body, re.S | re.I)
        desc_match = re.search(r"<description>(.*?)</description>", body, re.S | re.I)
        if not type_match:
            continue
        node_type = type_match.group(1).strip()
        description = desc_match.group(1).strip() if desc_match else match.group("name").strip()
        cards.append(
            NodeCard(
                name=match.group("name").strip(),
                node_type=node_type,
                description=description,
                full_schema=f"- Node: {match.group('name').strip()}\n{body.strip()}",
            )
        )
    if not cards:
        raise ValueError("No node schemas were parsed from builder_prompt.txt")
    return cards


def multihot_cosine(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


class TextEncoder:
    """Semantic embeddings when fastembed is present; deterministic TF-IDF fallback."""

    def __init__(self, corpus: Sequence[str]) -> None:
        self.backend = "tfidf"
        self.model: Any = None
        self.vectorizer: Any = None
        if os.environ.get("AGENT_EMBEDDING_BACKEND", "tfidf").lower() != "tfidf":
            try:
                from fastembed import TextEmbedding  # type: ignore

                self.model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
                self.backend = "bge-small-en-v1.5"
            except Exception:
                self.model = None
        if self.model is None:
            self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
            self.vectorizer.fit(list(corpus) or ["workflow"])

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self.model is not None:
            values = np.asarray(list(self.model.embed(list(texts))), dtype=np.float32)
        else:
            values = self.vectorizer.transform(list(texts)).toarray().astype(np.float32)
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        return values / np.maximum(norms, 1e-12)


class HybridRetriever:
    def __init__(self, cards: Sequence[NodeCard]) -> None:
        self.cards = list(cards)
        self.encoder = TextEncoder([card.summary for card in self.cards])
        self.node_vectors = self.encoder.encode([card.summary for card in self.cards])

    @property
    def backend(self) -> str:
        return self.encoder.backend

    def retrieve_nodes(
        self,
        requirement_text: str,
        predicted_types: Sequence[str],
        top_k: int = 8,
        semantic_weight: float = 0.75,
        required_types: Sequence[str] = (),
        optional_types: Sequence[str] = (),
        forbidden_types: Sequence[str] = (),
    ) -> List[Tuple[NodeCard, float]]:
        query = self.encoder.encode([requirement_text])[0]
        semantic = self.node_vectors @ query
        predicted = set(predicted_types)
        required = set(required_types) | {'start', 'end'}
        forbidden = set(forbidden_types) - required
        ranked: List[Tuple[NodeCard, float]] = []
        for card, sem in zip(self.cards, semantic):
            if card.node_type in forbidden:
                continue
            prior = 1.0 if card.node_type in predicted else 0.0
            score = semantic_weight * float(sem) + (1.0 - semantic_weight) * prior
            ranked.append((card, score))
        ranked.sort(key=lambda item: item[1], reverse=True)

        score_by_type = {card.node_type: (card, score) for card, score in ranked}
        budget = max(top_k, len(required))
        selected: Dict[str, Tuple[NodeCard, float]] = {}
        for node_type in required:
            if node_type in score_by_type:
                selected[node_type] = score_by_type[node_type]
        preferred = set(predicted) | set(optional_types)
        for card, score in ranked:
            if len(selected) >= budget:
                break
            if card.node_type in preferred:
                selected[card.node_type] = (card, score)
        for card, score in ranked:
            if len(selected) >= budget:
                break
            selected[card.node_type] = (card, score)
        return sorted(selected.values(), key=lambda item: item[1], reverse=True)

    def retrieve_experiences(
        self,
        requirement_text: str,
        predicted_types: Sequence[str],
        experiences: Sequence[Dict[str, Any]],
        top_k: int = 3,
        semantic_weight: float = 0.7,
        task_family: str = '',
        platform: str = 'dify',
        control_flow: Sequence[str] = (),
        min_semantic: float = 0.25,
        min_structural: float = 0.25,
        min_score: float = 0.45,
    ) -> List[Dict[str, Any]]:
        if not experiences:
            return []
        required_control = set(control_flow)
        eligible = [
            item
            for item in experiences
            if (not task_family or item.get('task_family') == task_family)
            and item.get('platform', 'dify') == platform
            and (
                not required_control
                or required_control.issubset(set(item.get('control_flow', [])))
            )
        ]
        if not eligible:
            return []
        texts = [str(item.get('requirement_text', '')) for item in eligible]
        vectors = self.encoder.encode([requirement_text] + texts)
        query, docs = vectors[0], vectors[1:]
        semantic = docs @ query
        scored: List[Tuple[float, Dict[str, Any]]] = []
        for sem, item in zip(semantic, eligible):
            structural = multihot_cosine(predicted_types, item.get('node_types', []))
            score = semantic_weight * float(sem) + (1.0 - semantic_weight) * structural
            if float(sem) < min_semantic or structural < min_structural or score < min_score:
                continue
            copy = dict(item)
            copy['retrieval_score'] = round(score, 6)
            copy['semantic_score'] = round(float(sem), 6)
            copy['structural_score'] = round(structural, 6)
            scored.append((score, copy))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:top_k]]


def load_experiences(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_experiences(path: Path, items: Sequence[Dict[str, Any]]) -> None:
    if not items:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

