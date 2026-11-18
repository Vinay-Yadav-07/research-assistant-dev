"""S6 Guardrail Service: input checks and handling of untrusted text (FR-31).

Document text is data, never instructions; prompts wrap it (and the user's question) in
delimited blocks built by `data_block`. Stored text only has to be storable and printable:
Postgres rejects NUL bytes in text, and lone surrogates cannot be encoded as UTF-8.
"""

import html
import re
from collections.abc import Sequence

from app.core.errors import InvalidInputError

# C0 controls except tab, newline, and carriage return; DEL; C1 controls; lone surrogates.
_UNSAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
# Tag-shaped markup only (a letter or "/" right after "<"), so "p < 0.05" is kept.
_TAG = re.compile(r"</?[A-Za-z][\w:.-]*(?:\s[^<>]*)?/?>")
_SPACES = re.compile(r"\s+")


def clean_untrusted_text(text: str) -> str:
    """`text` without NUL, other control characters, or lone surrogates."""
    return _UNSAFE.sub("", text)


def clean_optional(text: str | None) -> str | None:
    """Like `clean_untrusted_text`; empty results become None."""
    if text is None:
        return None
    cleaned = clean_untrusted_text(text).strip()
    return cleaned or None


def clean_metadata_text(text: str | None) -> str | None:
    """A metadata field as plain text: entities unescaped, HTML/XML tags removed.

    PDF metadata and Crossref titles carry markup such as `<i>`, `<sub>`, or `<mark>`.
    Unescaping first means escaped tags (`&lt;i&gt;`) are removed too.
    """
    if text is None:
        return None
    plain = _TAG.sub("", html.unescape(text))
    return clean_optional(_SPACES.sub(" ", plain))


_OUT_OF_SCOPE_REPLY = (
    "I can only answer research questions about the papers in this workspace, such as "
    "their methods, findings, comparisons, or limitations. Please rephrase your question "
    "about the documents you have uploaded."
)


def check_question(text: str, max_chars: int) -> str:
    """S6 input check: the question cleaned and stripped; empty or oversized is rejected."""
    question = clean_untrusted_text(text).strip()
    if not question:
        raise InvalidInputError("The question is empty.")
    if len(question) > max_chars:
        raise InvalidInputError(
            f"The question is longer than {max_chars} characters.",
            details={"max_chars": max_chars},
        )
    return question


def data_block(label: str, text: str) -> str:
    """`text` wrapped in `<label>` tags for a prompt, marking it as data, not instructions.

    A closing tag inside `text` is defused so the content cannot end the block early.
    """
    closing = f"</{label}>"
    safe = re.sub(re.escape(closing), f"</ {label}>", text, flags=re.IGNORECASE)
    return f"<{label}>\n{safe}\n{closing}"


def out_of_scope_reply() -> str:
    """The polite scoped refusal sent when A1 classifies a question as out of scope."""
    return _OUT_OF_SCOPE_REPLY


# S6 output label of claims that rest on general model knowledge (SRS §2.3).
GENERAL_KNOWLEDGE_LABEL = "General knowledge — not verified against sources"


def _sentence(text: str) -> str:
    """`text` ending in a full stop, unless it already ends a sentence (e.g. a question)."""
    return text if text.endswith((".", "?", "!")) else text + "."


def abstention_reply(
    uncovered: Sequence[str], closest: Sequence[str], notices: Sequence[str] = ()
) -> str:
    """The abstention (FR-11): what the papers do not answer and where they come closest."""
    parts = ["I could not find enough evidence in this workspace's papers to answer this."]
    if uncovered:
        parts.append(_sentence("Not answered by the papers: " + "; ".join(uncovered)))
    if closest:
        parts.append(_sentence("The closest passages are in: " + "; ".join(closest)))
    parts.extend(notices)
    return " ".join(parts)
