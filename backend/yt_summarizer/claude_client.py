"""Claude integration: token counting, cost estimation, and summarization."""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal, get_args

import anthropic

from .config import ModelPricing
from .mentions import CONFIDENCE_LEVELS, Mention
from .transcripts import Transcript

log = logging.getLogger(__name__)


Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORT_LEVELS: tuple[str, ...] = get_args(Effort)


class SummarizerError(Exception):
    """Raised when a Claude API interaction fails in a user-reportable way."""


@dataclass(frozen=True)
class ModelSettings:
    model: str
    effort: str
    max_output_tokens: int  # caps thinking and response together


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    estimated_output_tokens: int
    cost_usd: float | None  # None when the model has no pricing entry


@dataclass(frozen=True)
class Extraction:
    entity_kind: str
    stance_labels: list[str]
    known_entities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerResult:
    text: str
    tokens_input: int
    tokens_output: int
    cost_usd: float | None
    stop_reason: str | None


@dataclass(frozen=True)
class SummaryResult:
    text: str
    tokens_input: int
    tokens_output: int
    cost_usd: float | None
    stop_reason: str | None
    mentions: list[Mention] = field(default_factory=list)
    tokens_thinking: int | None = None  # part of tokens_output; None if not reported
    duration_ms: int | None = None


@contextmanager
def _api_errors(model: str):
    try:
        yield
    except anthropic.AuthenticationError as exc:
        raise SummarizerError(
            "Anthropic authentication failed — set ANTHROPIC_API_KEY in .env"
        ) from exc
    except anthropic.NotFoundError as exc:
        raise SummarizerError(
            f"Unknown model {model!r} — check its id under 'pricing' in config.yaml"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise SummarizerError(
            "Rate limited by the Anthropic API — wait a moment and retry"
        ) from exc
    except anthropic.APIStatusError as exc:
        raise SummarizerError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise SummarizerError("Could not reach the Anthropic API — check your network") from exc
    except TypeError as exc:
        # The SDK raises TypeError when no credentials are configured at all.
        if "authentication" in str(exc).lower():
            raise SummarizerError(
                "No Anthropic credentials found — copy .env.example to .env "
                "and set ANTHROPIC_API_KEY"
            ) from exc
        raise


def _messages(transcript: str) -> list[dict]:
    return [{"role": "user", "content": transcript}]


_ANSWER_SYSTEM = """You answer questions about what a YouTube channel said, using only the numbered sources below.

Rules:
- Use only the sources. If they do not answer the question, say so plainly.
- Cite the sources you used as [n] right after the claim they support.
- Give dates: a speaker's position changes over time, so say when something was said and call out changes of position.
- Answer in Markdown, and keep it tight.

Sources:
"""


def answer_messages(question: str) -> list[dict]:
    return [{"role": "user", "content": question}]


def answer_system(context: str) -> str:
    return _ANSWER_SYSTEM + context


def _extraction_schema(stance_labels: list[str]) -> dict:
    fields = ("entity", "stance", "confidence", "rationale", "quote", "timestamp_seconds")
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "mentions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string"},
                        "stance": {"type": "string", "enum": list(stance_labels)},
                        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                        "rationale": {"type": "string"},
                        "quote": {"type": "string"},
                        "timestamp_seconds": {
                            "anyOf": [{"type": "integer"}, {"type": "null"}]
                        },
                    },
                    "required": list(fields),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "mentions"],
        "additionalProperties": False,
    }


def _extraction_instructions(extraction: Extraction, timestamped: bool) -> str:
    labels = ", ".join(extraction.stance_labels)
    lines = [
        "Answer as JSON matching the required schema.",
        'Put the summary described above in "summary", as Markdown.',
        f'Put one entry in "mentions" for every {extraction.entity_kind} the speaker '
        "takes a position on. Leave the list empty when there are none.",
        f'"entity" is the canonical name of the {extraction.entity_kind}. '
        "Use the same name every time you mean the same thing.",
        f'"stance" is exactly one of: {labels}.',
        '"confidence" is how clearly the speaker states that stance: '
        f"{', '.join(CONFIDENCE_LEVELS)}.",
        '"rationale" is one sentence on why the speaker holds that stance.',
        '"quote" is a short verbatim quote from the transcript supporting it.',
    ]
    if timestamped:
        lines.append(
            '"timestamp_seconds" is the [mm:ss] marker nearest to the quote, in seconds.'
        )
    else:
        lines.append('"timestamp_seconds" is null: the transcript carries no timestamps.')
    if extraction.known_entities:
        known = ", ".join(extraction.known_entities)
        lines.append(
            "Reuse one of these names when the speaker means the same thing: " + known + "."
        )
    return "\n".join(lines)


def _parse_extraction(raw: str, stance_labels: list[str]) -> tuple[str, list[Mention]]:
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise SummarizerError(f"Claude returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SummarizerError("Claude returned JSON that is not an object")

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise SummarizerError("Claude returned no summary text")

    entries = data.get("mentions") or []
    if not isinstance(entries, list):
        raise SummarizerError("Claude returned a 'mentions' field that is not a list")

    allowed = set(stance_labels)
    mentions: list[Mention] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise SummarizerError("Claude returned a mention that is not an object")
        entity = str(entry.get("entity") or "").strip()
        stance = str(entry.get("stance") or "").strip()
        if not entity:
            continue
        if stance not in allowed:
            raise SummarizerError(
                f"Claude returned the unknown stance {stance!r} for {entity!r}"
            )
        confidence = str(entry.get("confidence") or "").strip()
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "low"
        at = entry.get("timestamp_seconds")
        mentions.append(
            Mention(
                entity=entity,
                stance=stance,
                confidence=confidence,
                rationale=str(entry.get("rationale") or "").strip(),
                quote=str(entry.get("quote") or "").strip(),
                timestamp_seconds=int(at) if isinstance(at, (int, float)) else None,
            )
        )
    return summary.strip(), mentions


class ClaudeSummarizer:
    def __init__(self, pricing: dict[str, ModelPricing]) -> None:
        # Created lazily so missing credentials surface as a SummarizerError on
        # first use (via _api_errors) instead of failing at construction time.
        self._client: anthropic.Anthropic | None = None
        self._pricing = pricing

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def cost(self, model: str, tokens_input: int, tokens_output: int) -> float | None:
        """Price for a token count; None if the model has no pricing entry.

        Also used for the monitor's worst-case budget pre-check
        (cost(model, input_tokens, max_output_tokens)) before spending on a call.
        """
        price = self._pricing.get(model)
        if price is None:
            return None
        return (
            tokens_input / 1_000_000 * price.input_per_mtok
            + tokens_output / 1_000_000 * price.output_per_mtok
        )

    def request_kwargs(
        self,
        settings: ModelSettings,
        prompt: str,
        transcript: Transcript,
        extraction: Extraction | None,
    ) -> dict:
        timestamped = extraction is not None and bool(transcript.segments)
        system = prompt
        output_config: dict = {"effort": settings.effort}
        if extraction is not None:
            system = f"{prompt}\n\n{_extraction_instructions(extraction, timestamped)}"
            output_config["format"] = {
                "type": "json_schema",
                "schema": _extraction_schema(extraction.stance_labels),
            }
        return {
            "model": settings.model,
            "system": system,
            "messages": _messages(transcript.rendered(timestamps=timestamped)),
            "output_config": output_config,
        }

    def estimate(
        self,
        settings: ModelSettings,
        prompt: str,
        transcript: Transcript,
        estimated_output_tokens: int,
        extraction: Extraction | None = None,
    ) -> CostEstimate:
        """Count input tokens server-side (free, exact) and estimate the cost."""
        with _api_errors(settings.model):
            count = self._get_client().messages.count_tokens(
                **self.request_kwargs(settings, prompt, transcript, extraction)
            )
        return CostEstimate(
            input_tokens=count.input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            cost_usd=self.cost(settings.model, count.input_tokens, estimated_output_tokens),
        )

    def summarize(
        self,
        settings: ModelSettings,
        prompt: str,
        transcript: Transcript,
        extraction: Extraction | None = None,
    ) -> SummaryResult:
        """Send the transcript to Claude and return the response with actual usage."""
        started = time.monotonic()
        with _api_errors(settings.model):
            with self._get_client().messages.stream(
                max_tokens=settings.max_output_tokens,
                **self.request_kwargs(settings, prompt, transcript, extraction),
            ) as stream:
                response = stream.get_final_message()
        duration_ms = round((time.monotonic() - started) * 1000)

        if response.stop_reason == "refusal":
            raise SummarizerError("Claude declined to process this transcript (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            if extraction is not None:
                raise SummarizerError(
                    f"Response hit the max output tokens limit ({settings.max_output_tokens}), "
                    "so the extracted JSON is truncated — raise the prompt's max output "
                    "tokens or lower its effort"
                )
            log.warning(
                "Response hit the max output tokens limit (%d) and may be truncated — "
                "consider raising the prompt's max output tokens",
                settings.max_output_tokens,
            )

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise SummarizerError(f"Claude returned no text (stop_reason={response.stop_reason})")

        mentions: list[Mention] = []
        if extraction is not None:
            text, mentions = _parse_extraction(text, extraction.stance_labels)

        usage = response.usage
        details = usage.output_tokens_details
        return SummaryResult(
            text=text,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=self.cost(settings.model, usage.input_tokens, usage.output_tokens),
            stop_reason=response.stop_reason,
            mentions=mentions,
            tokens_thinking=details.thinking_tokens if details else None,
            duration_ms=duration_ms,
        )

    def answer_kwargs(self, settings: ModelSettings, question: str, context: str) -> dict:
        return {
            "model": settings.model,
            "system": answer_system(context),
            "messages": answer_messages(question),
            "output_config": {"effort": settings.effort},
        }

    def estimate_answer(
        self,
        settings: ModelSettings,
        question: str,
        context: str,
        estimated_output_tokens: int,
    ) -> CostEstimate:
        """Count the exact request the answer will send (free)."""
        with _api_errors(settings.model):
            count = self._get_client().messages.count_tokens(
                **self.answer_kwargs(settings, question, context)
            )
        return CostEstimate(
            input_tokens=count.input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            cost_usd=self.cost(settings.model, count.input_tokens, estimated_output_tokens),
        )

    def answer(self, settings: ModelSettings, question: str, context: str) -> AnswerResult:
        """Answer a question from the assembled sources, with [n] citations."""
        with _api_errors(settings.model):
            with self._get_client().messages.stream(
                max_tokens=settings.max_output_tokens,
                **self.answer_kwargs(settings, question, context),
            ) as stream:
                response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise SummarizerError("Claude declined to answer this question (stop_reason=refusal)")

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise SummarizerError(f"Claude returned no text (stop_reason={response.stop_reason})")

        usage = response.usage
        return AnswerResult(
            text=text,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=self.cost(settings.model, usage.input_tokens, usage.output_tokens),
            stop_reason=response.stop_reason,
        )
