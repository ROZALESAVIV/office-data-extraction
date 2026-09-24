"""The only module that talks to the Claude API.

Everything else depends on the `LLMClient` protocol, so the model can be
swapped, and so tests can inject a fake without monkeypatching a library.

Schema constraints learned by trying, not assumed:
- `strict: true` tools reject `minimum`/`maximum` on numbers. Ranges are
  validated here after the response instead.
- Forced `tool_choice` works on Opus 5; it does not on every model, so the
  choice lives in one place.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings

log = logging.getLogger(__name__)

MODEL = "claude-opus-5"

# Sent with the classify call; one page is enough to tell a pleading from a
# photograph and keeps the cheapest step cheap.
CLASSIFY_EFFORT = "low"
EXTRACT_EFFORT = "medium"

# Per-million-token prices, for reporting spend back to the caller.
INPUT_PRICE = 5.0
OUTPUT_PRICE = 25.0

EXTRACT_TOOL_NAME = "record_extracted_fields"
CLASSIFY_TOOL_NAME = "classify_document"
NAVIGATE_TOOL_NAME = "locate_content"

MAX_SNIPPET_CHARS = 300


class LLMError(RuntimeError):
    """The model could not be used for this request."""


class LLMRefusal(LLMError):
    """The model declined the request outright."""


class LLMProtocolError(LLMError):
    """The response did not have the shape the tool schema requires."""


@dataclass
class LLMResult:
    data: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    request_id: str | None = None

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens / 1e6 * INPUT_PRICE
            + self.output_tokens / 1e6 * OUTPUT_PRICE
        )


class LLMClient(Protocol):
    def call_tool(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        tool: dict[str, Any],
        max_tokens: int = 8000,
        effort: str = EXTRACT_EFFORT,
    ) -> LLMResult: ...


# ── prompts ──────────────────────────────────────────────────────────────────

EXTRACT_SYSTEM = """You read Israeli legal and insurance documents and record specific fields.

The documents are in Hebrew. Follow these rules exactly.

VERBATIM QUOTES
- `snippet` must be copied character for character from the document, in Hebrew.
  Never translate it, never paraphrase it, never reorder the words.
- Quote the SHORTEST span that contains the answer. If the answer is a party's
  name inside a longer heading, quote just the name - not the whole heading.
  A different field must get a different quote.
- Keep it under 200 characters.

VALUES
- Record the value exactly as the document states it. Do not add explanations,
  expansions or translations of your own.

PAGES
- `page` is the page number as printed in the page markers provided, 1-indexed.

WHEN A FIELD IS ABSENT
- Return value: null, confidence: 0, page: null, snippet: null.
- Never infer it, never guess it from context, never carry a value over from a
  similar field on another document. A missing answer is a correct answer; an
  invented one is not.

CONFIDENCE
- A number between 0 and 1: your calibrated probability that a lawyer reading
  that page would agree with you. Use below 0.5 when the text is ambiguous, the
  scan is unclear, or you are reading a stamp or handwriting."""

CLASSIFY_SYSTEM = """You identify what kind of document you are looking at.

These are Hebrew documents from an Israeli motor-insurance claim file. You will
be given the first page and a list of known document types.

- Choose the single type that best matches. Use "unknown" if none clearly fits -
  a wrong label sends the document down the wrong extraction path, which is
  worse than no label.
- `confidence` is between 0 and 1.

Two things that mislead this judgement, both seen on real files:

- A pleading bundle often opens with the court's case-opening confirmation
  (אישור פתיחת תיק), and sometimes a blank page, before the pleading itself
  begins. Judge the document by the first page that carries its real heading,
  not by a cover sheet. If any page shows a court caption with plaintiff,
  defendant and "כתב תביעה", the document is a statement of claim.
- The filename is given because this insurer names files consistently, so it is
  real evidence - but it is not decisive. Where the filename and the content
  disagree, say so in `reason` and lower your confidence."""


def extraction_tool(field_keys: list[str]) -> dict[str, Any]:
    """One strict tool whose field_key enum is exactly what we asked for.

    Restricting the enum is what stops the model inventing keys - far more
    reliable than saying so in the prompt.
    """
    return {
        "name": EXTRACT_TOOL_NAME,
        "description": "Record every requested field found in this document.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field_key": {"type": "string", "enum": field_keys},
                            "value": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                            "page": {"type": ["integer", "null"]},
                            "snippet": {"type": ["string", "null"]},
                        },
                        "required": ["field_key", "value", "confidence", "page", "snippet"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["fields"],
            "additionalProperties": False,
        },
    }


NAVIGATE_SYSTEM = """You are looking at sampled pages from one long Hebrew document
from an Israeli motor-insurance claim file.

An Israeli pleading bundle is built the same way every time: sometimes a court
case-opening confirmation (אישור פתיחת תיק), then a few pages of the pleading
itself (כתב תביעה), and then dozens of pages of exhibits (נספחים) - forms,
photographs, reports. The exhibits are copies of documents that are already in
the case file separately, so reading them again finds nothing new.

Your job is to say which pages hold the document's OWN content, as opposed to
attachments.

- `content_first_page` and `content_last_page` are original page numbers in the
  full document, not positions in what you were shown.
- Include a court case-opening confirmation in the range if there is one - it
  carries the case number and the filing date.
- Exclude affidavits, powers of attorney, photographs, invoices and reports.
- If you cannot tell, say so with low confidence and give the widest range you
  are sure about. Cutting off real content is worse than reading a few extra
  pages."""


def navigation_tool() -> dict[str, Any]:
    return {
        "name": NAVIGATE_TOOL_NAME,
        "description": "Say which pages hold the document's own content.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "content_first_page": {"type": "integer"},
                "content_last_page": {"type": "integer"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["content_first_page", "content_last_page", "confidence", "reason"],
            "additionalProperties": False,
        },
    }


def classification_tool(type_keys: list[str]) -> dict[str, Any]:
    return {
        "name": CLASSIFY_TOOL_NAME,
        "description": "Identify the document type.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "type_key": {"type": "string", "enum": [*type_keys, "unknown"]},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["type_key", "confidence", "reason"],
            "additionalProperties": False,
        },
    }


def clamp_confidence(value: Any) -> float:
    """The strict schema cannot express a 0-1 range, so enforce it here."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


class AnthropicLLM:
    """Real client. Retries transport errors; never retries a refusal."""

    def __init__(self, api_key: str | None = None, model: str = MODEL):
        import anthropic

        key = api_key or settings.anthropic_api_key
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not configured")
        self._client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=600.0)
        self._model = model

    def call_tool(
        self,
        *,
        system: str,
        content: list[dict[str, Any]],
        tool: dict[str, Any],
        max_tokens: int = 8000,
        effort: str = EXTRACT_EFFORT,
    ) -> LLMResult:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            # Cached: the instructions are identical on every call, so only the
            # document and the field list are billed at full rate.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": content}],
        )

        if response.stop_reason == "refusal":
            category = getattr(getattr(response, "stop_details", None), "category", None)
            raise LLMRefusal(f"model declined the request (category={category})")

        block = next((b for b in response.content if b.type == "tool_use"), None)
        if block is None:
            raise LLMProtocolError(
                f"no tool_use block in response (stop_reason={response.stop_reason})"
            )

        usage = response.usage
        return LLMResult(
            data=dict(block.input),
            raw=json.loads(response.to_json()),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            request_id=getattr(response, "_request_id", None) or getattr(response, "id", None),
        )


def pdf_block(blob: bytes) -> dict[str, Any]:
    """A PDF for the model to read. It does its own OCR, so scans are fine.

    This goes FIRST in the content list, with the volatile field list after it,
    so the cached prefix stays stable across calls on the same document.
    """
    import base64

    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(blob).decode(),
        },
        "cache_control": {"type": "ephemeral"},
    }


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}
