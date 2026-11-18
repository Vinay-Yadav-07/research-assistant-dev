"""S10 Knowledge Graph Service: the per-workspace build (SRS §9.1, D-081).

The build reads the stored mentions of the workspace's current papers and groups them, without
LLM calls: entity mentions of equal type and normalized name become one node, and an acronym
joins its expansion only when a passage of the workspace states both ("Long Short-Term Memory
(LSTM)"). Findings carry their paper in their key, so they never merge across papers. Relation
mentions between two nodes with one relationship type become one edge. The old graph is
replaced in one transaction, so a failed build leaves it unchanged.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractAsyncContextManager
from itertools import combinations
from typing import Protocol
from uuid import UUID, uuid4

from app.repositories.knowledge_graph import (
    BuildInputs,
    MentionRow,
    NewEdge,
    NewNode,
)
from app.services.knowledge_graph import fold
from app.services.knowledge_graph_jobs import source_fingerprint

MAX_ALIASES = 10
_ACRONYM = re.compile(r"^[A-Za-z0-9]{2,10}$")

NodeKey = tuple[str, str]


class GraphBuildStore(Protocol):
    """Persistence the build needs; `KnowledgeGraphRepository` implements it."""

    async def ready_document_ids(self, user_id: UUID, workspace_id: UUID) -> list[UUID]: ...

    async def build_inputs(
        self, user_id: UUID, document_ids: Collection[UUID], extractor_version: str
    ) -> BuildInputs: ...

    async def replace_graph(
        self,
        user_id: UUID,
        workspace_id: UUID,
        *,
        job_id: UUID,
        source_fingerprint: str,
        nodes: Collection[NewNode],
        edges: Collection[NewEdge],
    ) -> None: ...

    async def commit(self) -> None: ...


BuildStoreFactory = Callable[[], AbstractAsyncContextManager[GraphBuildStore]]


def is_acronym_of(short: str, long: str) -> bool:
    """True if `short` (e.g. "LSTM", "CNNs") is the initials of `long`'s words
    (e.g. "Long Short-Term Memory", "convolutional neural networks")."""
    letters = short.strip()
    if letters.endswith("s") and letters[:-1].isupper():
        letters = letters[:-1]
    if not _ACRONYM.match(letters) or sum(c.isupper() for c in letters) < 2:
        return False
    words = [word for word in re.split(r"[\s\-]+", long.strip()) if word]
    return len(words) >= 2 and "".join(w[0] for w in words).casefold() == letters.casefold()


def acronym_links(
    mentions: Sequence[MentionRow], chunk_texts: dict[UUID, str]
) -> list[tuple[NodeKey, NodeKey]]:
    """Pairs of (type, key) that a passage states as acronym and expansion."""
    by_passage: dict[tuple[UUID, str], list[MentionRow]] = defaultdict(list)
    for mention in mentions:
        if mention.entity_type != "finding":
            by_passage[(mention.chunk_id, mention.entity_type)].append(mention)
    links: list[tuple[NodeKey, NodeKey]] = []
    for (chunk_id, entity_type), group in by_passage.items():
        text = fold(chunk_texts.get(chunk_id, ""))
        for a, b in combinations(group, 2):
            for short, long in ((a, b), (b, a)):
                if not is_acronym_of(short.surface_text, long.surface_text):
                    continue
                s, lng = fold(short.surface_text), fold(long.surface_text)
                if f"{lng} ({s})" in text or f"{s} ({lng})" in text:
                    links.append(
                        ((entity_type, short.normalized_key), (entity_type, long.normalized_key))
                    )
    return links


def assemble(inputs: BuildInputs) -> tuple[list[NewNode], list[NewEdge]]:
    """Group the mentions into nodes and edges (deterministic apart from the new ids)."""
    parent: dict[NodeKey, NodeKey] = {}

    def root(key: NodeKey) -> NodeKey:
        while parent.get(key, key) != key:
            key = parent[key]
        return key

    for a, b in acronym_links(inputs.mentions, inputs.chunk_texts):
        ra, rb = root(a), root(b)
        if ra != rb:
            # The longer key (the expansion) names the merged node.
            keep, other = sorted((ra, rb), key=lambda k: (len(k[1]), k[1]), reverse=True)
            parent[other] = keep

    groups: dict[NodeKey, list[MentionRow]] = defaultdict(list)
    for mention in inputs.mentions:
        groups[root((mention.entity_type, mention.normalized_key))].append(mention)
    nodes: list[NewNode] = []
    node_of: dict[UUID, NewNode] = {}
    for (entity_type, key), members in sorted(groups.items()):
        surfaces = Counter(m.surface_text for m in members)
        label = min(surfaces, key=lambda s: (-surfaces[s], -len(s), s))
        aliases = sorted({s for s in surfaces if s.casefold() != label.casefold()})
        node = NewNode(
            id=uuid4(),
            entity_type=entity_type,
            label=label,
            normalized_key=key,
            aliases=aliases[:MAX_ALIASES],
            document_count=len({m.document_id for m in members}),
            mention_ids=[m.id for m in members],
        )
        nodes.append(node)
        for member in members:
            node_of[member.id] = node

    edge_members: dict[tuple[UUID, UUID, str], list[tuple[UUID, UUID]]] = defaultdict(list)
    for relation in inputs.relations:
        source = node_of.get(relation.source_mention_id)
        target = node_of.get(relation.target_mention_id)
        if source is None or target is None or source is target:
            continue
        if relation.relation_type == "compared_with" and source.normalized_key > (
            target.normalized_key
        ):
            source, target = target, source
        edge_members[(source.id, target.id, relation.relation_type)].append(
            (relation.id, relation.document_id)
        )
    edges = [
        NewEdge(
            id=uuid4(),
            source_node_id=source_id,
            target_node_id=target_id,
            relation_type=relation_type,
            document_count=len({document_id for _, document_id in members}),
            relation_mention_ids=[relation_id for relation_id, _ in members],
        )
        for (source_id, target_id, relation_type), members in edge_members.items()
    ]
    return nodes, edges


class KnowledgeGraphBuilder:
    """S10's `GraphBuilder`: rebuilds one workspace's graph in a single transaction."""

    def __init__(self, stores: BuildStoreFactory, extractor_version: str) -> None:
        self._stores = stores
        self._version = extractor_version

    async def build(self, user_id: UUID, workspace_id: UUID, job_id: UUID) -> None:
        """Replace the workspace's nodes and edges with those of its current papers."""
        async with self._stores() as store:
            document_ids = await store.ready_document_ids(user_id, workspace_id)
            inputs = await store.build_inputs(user_id, document_ids, self._version)
            nodes, edges = assemble(inputs)
            await store.replace_graph(
                user_id,
                workspace_id,
                job_id=job_id,
                source_fingerprint=source_fingerprint(document_ids, self._version),
                nodes=nodes,
                edges=edges,
            )
            await store.commit()
