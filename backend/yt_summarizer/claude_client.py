"""Claude integration: token counting, cost estimation, and summarization."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field

import anthropic

from .config import ModelPricing
from .mentions import CONFIDENCE_LEVELS, Mention
from .transcripts import Transcript

log = logging.getLogger(__name__)


class SummarizerError(Exception):
    """Raised when a Claude API interaction fails in a user-reportable way."""


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
class SummaryResult:
    text: str
    tokens_input: int
    tokens_output: int
    cost_usd: float | None
    stop_reason: str | None
    mentions: list[Mention] = field(default_factory=list)


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
            f"Unknown model {model!r} — check 'model' in config.yaml"
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
    def __init__(
        self,
        model: str,
        max_output_tokens: int,
        pricing: dict[str, ModelPricing],
    ) -> None:
        # Created lazily so missing credentials surface as a SummarizerError on
        # first use (via _api_errors) instead of failing at construction time.
        self._client: anthropic.Anthropic | None = None
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._pricing = pricing

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _cost(self, tokens_input: int, tokens_output: int) -> float | None:
        price = self._pricing.get(self._model)
        if price is None:
            return None
        return (
            tokens_input / 1_000_000 * price.input_per_mtok
            + tokens_output / 1_000_000 * price.output_per_mtok
        )

    def cost(self, tokens_input: int, tokens_output: int) -> float | None:
        """Public price for a token count; None if the model has no pricing entry.

        Used for the monitor's worst-case budget pre-check
        (cost(input_tokens, max_output_tokens)) before spending on a call.
        """
        return self._cost(tokens_input, tokens_output)

    @property
    def max_output_tokens(self) -> int:
        return self._max_output_tokens

    def request_kwargs(
        self, prompt: str, transcript: Transcript, extraction: Extraction | None
    ) -> dict:
        timestamped = extraction is not None and bool(transcript.segments)
        system = prompt
        if extraction is not None:
            system = f"{prompt}\n\n{_extraction_instructions(extraction, timestamped)}"
        kwargs: dict = {
            "model": self._model,
            "system": system,
            "messages": _messages(transcript.rendered(timestamps=timestamped)),
        }
        if extraction is not None:
            kwargs["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": _extraction_schema(extraction.stance_labels),
                }
            }
        return kwargs

    def estimate(
        self,
        prompt: str,
        transcript: Transcript,
        estimated_output_tokens: int,
        extraction: Extraction | None = None,
    ) -> CostEstimate:
        """Count input tokens server-side (free, exact) and estimate the cost."""
        with _api_errors(self._model):
            count = self._get_client().messages.count_tokens(
                **self.request_kwargs(prompt, transcript, extraction)
            )
        return CostEstimate(
            input_tokens=count.input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            cost_usd=self._cost(count.input_tokens, estimated_output_tokens),
        )

    def summarize(
        self,
        prompt: str,
        transcript: Transcript,
        extraction: Extraction | None = None,
    ) -> SummaryResult:
        """Send the transcript to Claude and return the response with actual usage."""
        with _api_errors(self._model):
            with self._get_client().messages.stream(
                max_tokens=self._max_output_tokens,
                **self.request_kwargs(prompt, transcript, extraction),
            ) as stream:
                response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise SummarizerError("Claude declined to process this transcript (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            if extraction is not None:
                raise SummarizerError(
                    f"Response hit the max_output_tokens limit ({self._max_output_tokens}), "
                    "so the extracted JSON is truncated — raise 'max_output_tokens' in "
                    "config.yaml or shorten the prompt"
                )
            log.warning(
                "Response hit the max_output_tokens limit (%d) and may be truncated — "
                "consider raising 'max_output_tokens' in config.yaml",
                self._max_output_tokens,
            )

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise SummarizerError(f"Claude returned no text (stop_reason={response.stop_reason})")

        mentions: list[Mention] = []
        if extraction is not None:
            text, mentions = _parse_extraction(text, extraction.stance_labels)

        usage = response.usage
        return SummaryResult(
            text=text,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=self._cost(usage.input_tokens, usage.output_tokens),
            stop_reason=response.stop_reason,
            mentions=mentions,
        )
