"""Benchmark v1 (SRS §17.4, D-063): file format and the calibration/test splits."""

import json
from pathlib import Path

from eval.dataset import BENCHMARK, GoldPassage, load_corpora, load_items


def test_benchmark_is_well_formed() -> None:
    items = load_items(BENCHMARK)
    corpora = load_corpora()
    assert len({item.id for item in items}) == len(items)
    for item in items:
        papers = {path.name for path in corpora[item.corpus]}
        assert item.split in ("calibration", "test")
        assert item.drafted_by in ("claude", "human")
        assert item.type in ("single", "multi", "comparison", "unanswerable")
        assert item.answerable == (item.type != "unanswerable")
        if item.answerable:
            assert item.gold, item.id
            for passage in item.gold:
                assert passage.paper in papers and passage.page >= 1 and passage.snippet
        else:
            assert item.paper is None and item.page is None and item.snippet is None
            assert item.gold == ()


def test_test_split_has_the_phase_2_size_and_mix() -> None:
    test = load_items(BENCHMARK, split="test")
    assert len(test) >= 50
    assert all(item.id.startswith("test-") for item in test)
    assert sum(item.type == "unanswerable" for item in test) >= 10
    for item in test:
        if item.type in ("multi", "comparison"):
            assert len({passage.paper for passage in item.gold}) >= 2, item.id


def test_splits_share_no_question() -> None:
    calibration = {item.question.lower() for item in load_items(BENCHMARK, split="calibration")}
    test = {item.question.lower() for item in load_items(BENCHMARK, split="test")}
    assert calibration and test
    assert not calibration & test


def test_items_without_type_get_it_from_answerability(tmp_path: Path) -> None:
    base = {
        "split": "calibration",
        "corpus": "tissue",
        "question": "q?",
        "drafted_by": "claude",
        "verified_by": "",
    }
    rows = [
        {**base, "id": "a", "answerable": True, "paper": "p.pdf", "page": 2, "snippet": "s"},
        {**base, "id": "u", "answerable": False, "paper": None, "page": None, "snippet": None},
        {
            **base,
            "id": "m",
            "split": "test",
            "type": "multi",
            "answerable": True,
            "paper": None,
            "page": None,
            "snippet": None,
            "evidence": [
                {"paper": "a.pdf", "page": 1, "snippet": "x"},
                {"paper": "b.pdf", "page": 3, "snippet": "y"},
            ],
            "verified_by": "reviewer",
        },
    ]
    path = tmp_path / "bench.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    single, unanswerable, multi = load_items(path)

    assert (single.type, single.gold) == ("single", (GoldPassage("p.pdf", 2, "s"),))
    assert (unanswerable.type, unanswerable.gold) == ("unanswerable", ())
    assert multi.gold == (GoldPassage("a.pdf", 1, "x"), GoldPassage("b.pdf", 3, "y"))
    assert multi.verified and not single.verified
    assert [item.id for item in load_items(path, split="test")] == ["m"]
