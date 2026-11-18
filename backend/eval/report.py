"""Markdown summary of one evaluation run, written next to its JSON report."""

from typing import Any


def markdown_report(config: dict[str, Any], summary: dict[str, Any]) -> str:
    """Tables for the verified items and for all items (D-063: only verified items count)."""
    lines = [
        f"# {config['condition']} on the {config['split']} split",
        "",
        f"- Generation model: `{config['generation_model']}` (prompt {config['prompt_version']})",
        f"- Retrieval: {_retrieval_setup(config)}",
        f"- Ragas judge: {_judge(config)}",
        "",
    ]
    all_items = summary["all"]
    lines += [
        f"Items: {all_items['questions']} ({_counts(all_items['by_type'])}); "
        f"drafted by {_counts(all_items['drafted_by'])}; verified {all_items['verified']}.",
        "",
    ]
    for title, part in (("Verified items", summary["verified"]), ("All items", all_items)):
        lines += [f"## {title}", ""]
        if part is None:
            lines += [
                "No verified items yet: the numbers below cover all items and are provisional.",
                "",
            ]
            continue
        lines += _tables(part)
    return "\n".join(lines).rstrip() + "\n"


def _tables(part: dict[str, Any]) -> list[str]:
    abstention, system, ragas = part["abstention"], part["system"], part["ragas"]
    rows = [
        ("Questions (failed)", f"{part['questions']} ({part['failed']})"),
        (
            "Abstention accuracy (unanswerable)",
            f"{_num(abstention['abstention_accuracy'])} "
            f"({abstention['correct_abstentions']}/{abstention['unanswerable']})",
        ),
        (
            "False abstention rate (answerable)",
            f"{_num(abstention['false_abstention_rate'])} "
            f"({abstention['false_abstentions']}/{abstention['answerable']})",
        ),
    ]
    retrieval = part["retrieval"]
    if retrieval is not None:
        for label in ("page", "snippet"):
            scores = retrieval[label]
            rows.append(
                (
                    f"Retrieval by {label} (R@5 / R@8 / MRR)",
                    f"{_num(scores['R@5'])} / {_num(scores['R@8'])} / {_num(scores['MRR'])}",
                )
            )
    rows += [
        (
            "Ragas faithfulness",
            f"{_num(ragas['faithfulness'])} (n={ragas['faithfulness_scored']})",
        ),
        (
            "Ragas answer relevancy",
            f"{_num(ragas['answer_relevancy'])} (n={ragas['answer_relevancy_scored']})",
        ),
        ("Judge errors", str(ragas["judge_errors"])),
        (
            "Latency ms (mean / p50 / p95)",
            f"{_num(system['latency_ms_mean'], 0)} / {_num(system['latency_ms_p50'], 0)} / "
            f"{_num(system['latency_ms_p95'], 0)}",
        ),
        ("LLM calls per question", _num(system["llm_calls_mean"], 2)),
        (
            "Tokens per question (in / out)",
            f"{_num(system['input_tokens_mean'], 0)} / {_num(system['output_tokens_mean'], 0)}",
        ),
        ("Judge calls (total)", str(system["judge_calls_total"])),
    ]
    return ["| Metric | Value |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows), ""]


def _retrieval_setup(config: dict[str, Any]) -> str:
    if config["retrieval"] is None:
        return "none"
    return f"{config['retrieval']} top {config['top_k']} (`{config['embedding_model']}`)"


def _judge(config: dict[str, Any]) -> str:
    if not config["ragas"]:
        return "off"
    return (
        f"`{config['judge_model']}` "
        f"(answer relevancy strictness {config['answer_relevancy_strictness']})"
    )


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in counts.items())


def _num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "–"
    return f"{value:.{digits}f}"
