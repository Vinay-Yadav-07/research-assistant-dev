from collections.abc import Sequence
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from app.core.errors import AppError, ExternalServiceError, LLMOutputError
from app.providers.fakes import FakeLLM, FakeLLMNotScriptedError
from app.providers.llm import ChatMessage, parse_structured


class Plan(BaseModel):
    intent: Literal["simple_qa", "comparison"]
    sub_questions: list[str] = Field(max_length=4)


class AllDefaults(BaseModel):
    note: str = ""


MESSAGES = [
    ChatMessage(role="system", content="You analyse questions."),
    ChatMessage(role="user", content="How does porosity affect infiltration?"),
]


async def test_scripted_instance_is_returned_with_model_and_usage() -> None:
    plan = Plan(intent="simple_qa", sub_questions=["q1"])
    llm = FakeLLM(model_name="fake-fast", structured={Plan: [plan]})

    result = await llm.generate_structured(MESSAGES, Plan)

    assert result.output == plan
    assert result.model == "fake-fast"
    assert result.usage.input_tokens == 8
    assert result.usage.output_tokens > 0


@pytest.mark.parametrize(
    "entry",
    [
        {"intent": "comparison", "sub_questions": ["a", "b"]},
        '{"intent": "comparison", "sub_questions": ["a", "b"]}',
    ],
)
async def test_dict_and_json_entries_are_validated_into_the_schema(entry: object) -> None:
    llm = FakeLLM()
    llm.script(Plan, entry)  # type: ignore[arg-type]

    result = await llm.generate_structured(MESSAGES, Plan)

    assert isinstance(result.output, Plan)
    assert result.output.sub_questions == ["a", "b"]


@pytest.mark.parametrize(
    "entry",
    [
        {"intent": "gossip", "sub_questions": []},
        {"intent": "simple_qa", "sub_questions": ["1", "2", "3", "4", "5"]},
        "not json at all",
    ],
)
async def test_invalid_entries_raise_llm_output_error(entry: object) -> None:
    llm = FakeLLM(structured={Plan: [entry]})  # type: ignore[list-item]

    with pytest.raises(LLMOutputError) as caught:
        await llm.generate_structured(MESSAGES, Plan)

    assert caught.value.details["schema"] == "Plan"
    assert caught.value.details["errors"]


async def test_scripted_exception_is_raised() -> None:
    llm = FakeLLM(structured={Plan: [ExternalServiceError("provider down")]})

    with pytest.raises(ExternalServiceError, match="provider down"):
        await llm.generate_structured(MESSAGES, Plan)


async def test_callable_entry_receives_the_messages() -> None:
    def answer(messages: Sequence[ChatMessage]) -> Plan:
        return Plan(intent="simple_qa", sub_questions=[messages[-1].content])

    llm = FakeLLM(structured={Plan: [answer]})

    result = await llm.generate_structured(MESSAGES, Plan)

    assert result.output.sub_questions == ["How does porosity affect infiltration?"]


async def test_unscripted_schema_raises_not_scripted() -> None:
    llm = FakeLLM()

    with pytest.raises(FakeLLMNotScriptedError, match="Plan"):
        await llm.generate_structured(MESSAGES, Plan)


async def test_unscripted_schema_with_all_defaults_still_raises() -> None:
    llm = FakeLLM()

    with pytest.raises(FakeLLMNotScriptedError, match="AllDefaults"):
        await llm.generate_structured(MESSAGES, AllDefaults)


async def test_exhausted_queue_raises_not_scripted() -> None:
    llm = FakeLLM(structured={Plan: [Plan(intent="simple_qa", sub_questions=[])]})
    await llm.generate_structured(MESSAGES, Plan)

    with pytest.raises(FakeLLMNotScriptedError):
        await llm.generate_structured(MESSAGES, Plan)


def test_not_scripted_error_is_not_an_app_error() -> None:
    assert not issubclass(FakeLLMNotScriptedError, AppError)


async def test_queues_are_per_schema_and_in_order() -> None:
    first = Plan(intent="simple_qa", sub_questions=["1"])
    second = Plan(intent="comparison", sub_questions=["2"])
    llm = FakeLLM(structured={Plan: [first, second], AllDefaults: [AllDefaults(note="x")]})

    assert (await llm.generate_structured(MESSAGES, AllDefaults)).output.note == "x"
    assert (await llm.generate_structured(MESSAGES, Plan)).output == first
    assert (await llm.generate_structured(MESSAGES, Plan)).output == second


async def test_calls_are_recorded() -> None:
    llm = FakeLLM(structured={Plan: [Plan(intent="simple_qa", sub_questions=[])]})

    await llm.generate_structured(MESSAGES, Plan, temperature=0.0, max_output_tokens=50)
    await llm.generate_text(MESSAGES)

    assert [call.method for call in llm.calls] == ["structured", "text"]
    assert llm.calls[0].schema is Plan
    assert llm.calls[0].messages == tuple(MESSAGES)
    assert llm.calls[0].temperature == 0.0
    assert llm.calls[0].max_output_tokens == 50
    assert llm.calls[1].schema is None


async def test_unscripted_text_echoes_last_user_message() -> None:
    llm = FakeLLM()

    first = await llm.generate_text(MESSAGES)
    second = await llm.generate_text(MESSAGES)

    assert first.output == "[fake] How does porosity affect infiltration?"
    assert second.output == first.output


async def test_scripted_text_replies_in_order() -> None:
    llm = FakeLLM(text=["one", lambda messages: f"{len(messages)} messages"])
    llm.script_text(ExternalServiceError("down"))

    assert (await llm.generate_text(MESSAGES)).output == "one"
    assert (await llm.generate_text(MESSAGES)).output == "2 messages"
    with pytest.raises(ExternalServiceError):
        await llm.generate_text(MESSAGES)


def test_parse_structured_accepts_a_matching_instance_unchanged() -> None:
    plan = Plan(intent="simple_qa", sub_questions=[])

    assert parse_structured(Plan, plan) is plan


def test_parse_structured_revalidates_a_different_model() -> None:
    class Other(BaseModel):
        intent: str
        sub_questions: list[str]

    parsed = parse_structured(Plan, Other(intent="comparison", sub_questions=["a"]))

    assert parsed == Plan(intent="comparison", sub_questions=["a"])


def test_parse_structured_error_details_do_not_echo_input() -> None:
    with pytest.raises(LLMOutputError) as caught:
        parse_structured(Plan, {"intent": "secret-looking-value", "sub_questions": []})

    assert "secret-looking-value" not in str(caught.value.details)
