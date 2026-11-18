"""Grouping stored mentions into a workspace graph (SRS §9.1, D-081)."""

from uuid import UUID, uuid4

import pytest

from app.repositories.knowledge_graph import BuildInputs, MentionRow, RelationRow
from app.services.knowledge_graph_build import acronym_links, assemble, is_acronym_of

PAPER_A, PAPER_B = uuid4(), uuid4()


def mention(
    surface: str,
    key: str,
    *,
    type: str = "method",
    paper: UUID = PAPER_A,
    chunk: UUID | None = None,
) -> MentionRow:
    return MentionRow(
        id=uuid4(),
        document_id=paper,
        chunk_id=chunk or uuid4(),
        entity_type=type,
        surface_text=surface,
        normalized_key=key,
    )


def relation(source: MentionRow, target: MentionRow, type: str) -> RelationRow:
    return RelationRow(
        id=uuid4(),
        document_id=source.document_id,
        source_mention_id=source.id,
        target_mention_id=target.id,
        relation_type=type,
    )


@pytest.mark.parametrize(
    ("short", "long", "expected"),
    [
        ("LSTM", "Long Short-Term Memory", True),
        ("CNNs", "convolutional neural networks", True),
        ("RF", "Random Forest", True),
        ("RF", "radio frequency", True),
        ("SVM", "Random Forest", False),
        ("lstm", "Long Short-Term Memory", False),
        ("L", "Long", False),
    ],
)
def test_is_acronym_of(short: str, long: str, expected: bool) -> None:
    assert is_acronym_of(short, long) is expected


def test_nodes_merge_across_papers_by_type_and_key() -> None:
    a = mention("LSTM", "lstm", paper=PAPER_A)
    b = mention("LSTMs", "lstm", paper=PAPER_B)
    c = mention("LSTM", "lstm", paper=PAPER_B)
    other_type = mention("LSTM", "lstm", type="tool")

    nodes, edges = assemble(BuildInputs([a, b, c, other_type], [], {}))

    method = next(n for n in nodes if n.entity_type == "method")
    assert (method.label, method.aliases, method.document_count) == ("LSTM", ["LSTMs"], 2)
    assert set(method.mention_ids) == {a.id, b.id, c.id}
    assert len(nodes) == 2
    assert edges == []


def test_findings_never_merge_across_papers() -> None:
    a = mention("Error fell by 12%.", f"{PAPER_A}:error fell by 12", type="finding")
    b = mention("Error fell by 12%.", f"{PAPER_B}:error fell by 12", type="finding", paper=PAPER_B)

    nodes, _ = assemble(BuildInputs([a, b], [], {}))

    assert len(nodes) == 2


def test_an_acronym_joins_its_expansion_only_when_a_passage_states_both() -> None:
    passage = uuid4()
    long = mention("Long Short-Term Memory", "long short term memory", chunk=passage)
    short = mention("LSTM", "lstm", chunk=passage)
    elsewhere = mention("LSTM", "lstm", paper=PAPER_B)
    text = {passage: "We use Long Short-Term Memory (LSTM) networks."}

    nodes, _ = assemble(BuildInputs([long, short, elsewhere], [], text))

    (node,) = nodes
    assert node.normalized_key == "long short term memory"
    assert node.label == "LSTM"
    assert node.aliases == ["Long Short-Term Memory"]
    assert node.document_count == 2


def test_names_in_one_passage_without_the_acronym_pattern_stay_apart() -> None:
    passage = uuid4()
    long = mention("Random Forest", "random forest", chunk=passage)
    short = mention("RF", "rf", chunk=passage)

    assert acronym_links([long, short], {passage: "Random Forest and RF were both tried."}) == []
    nodes, _ = assemble(BuildInputs([long, short], [], {}))
    assert len(nodes) == 2


def test_edges_group_relation_mentions_and_count_papers() -> None:
    lstm_a, m4_a = mention("LSTM", "lstm"), mention("M4", "m4", type="dataset")
    lstm_b = mention("LSTM", "lstm", paper=PAPER_B)
    m4_b = mention("M4", "m4", type="dataset", paper=PAPER_B)
    relations = [
        relation(lstm_a, m4_a, "evaluated_on"),
        relation(lstm_b, m4_b, "evaluated_on"),
        relation(lstm_b, m4_b, "uses"),
    ]

    nodes, edges = assemble(BuildInputs([lstm_a, m4_a, lstm_b, m4_b], relations, {}))

    assert len(nodes) == 2
    evaluated = next(e for e in edges if e.relation_type == "evaluated_on")
    assert evaluated.document_count == 2
    assert len(evaluated.relation_mention_ids) == 2
    assert {e.relation_type for e in edges} == {"evaluated_on", "uses"}


def test_comparisons_in_both_directions_are_one_edge_and_self_loops_are_dropped() -> None:
    lstm, rf = mention("LSTM", "lstm"), mention("Random Forest", "random forest")
    lstm_2 = mention("LSTM", "lstm", paper=PAPER_B)
    rf_2 = mention("Random Forest", "random forest", paper=PAPER_B)
    relations = [
        relation(lstm, rf, "compared_with"),
        relation(rf_2, lstm_2, "compared_with"),
        relation(lstm, lstm_2, "uses"),
    ]

    nodes, edges = assemble(BuildInputs([lstm, rf, lstm_2, rf_2], relations, {}))

    (edge,) = edges
    by_id = {n.id: n for n in nodes}
    assert (
        by_id[edge.source_node_id].normalized_key,
        by_id[edge.target_node_id].normalized_key,
    ) == (
        "lstm",
        "random forest",
    )
    assert edge.document_count == 2


def test_relations_to_mentions_outside_the_build_are_ignored() -> None:
    lstm = mention("LSTM", "lstm")
    gone = mention("M4", "m4", type="dataset")

    _, edges = assemble(BuildInputs([lstm], [relation(lstm, gone, "evaluated_on")], {}))

    assert edges == []
