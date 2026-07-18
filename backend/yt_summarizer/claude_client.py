"""Claude integration: token counting, cost estimation, and summarization."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass

import anthropic

from .config import ModelPricing

log = logging.getLogger(__name__)


class SummarizerError(Exception):
    """Raised when a Claude API interaction fails in a user-reportable way."""


@dataclass(frozen=True)
class CostEstimate:
    input_tokens: int
    estimated_output_tokens: int
    cost_usd: float | None  # None when the model has no pricing entry


@dataclass(frozen=True)
class SummaryResult:
    text: str
    tokens_input: int
    tokens_output: int
    cost_usd: float | None
    stop_reason: str | None


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

    def estimate(self, prompt: str, transcript: str, estimated_output_tokens: int) -> CostEstimate:
        """Count input tokens server-side (free, exact) and estimate the cost."""
        with _api_errors(self._model):
            count = self._get_client().messages.count_tokens(
                model=self._model,
                system=prompt,
                messages=_messages(transcript),
            )
        return CostEstimate(
            input_tokens=count.input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            cost_usd=self._cost(count.input_tokens, estimated_output_tokens),
        )

    def summarize(self, prompt: str, transcript: str) -> SummaryResult:
        """Send the transcript to Claude and return the response with actual usage."""
        with _api_errors(self._model):
            with self._get_client().messages.stream(
                model=self._model,
                max_tokens=self._max_output_tokens,
                system=prompt,
                messages=_messages(transcript),
            ) as stream:
                response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise SummarizerError("Claude declined to process this transcript (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            log.warning(
                "Response hit the max_output_tokens limit (%d) and may be truncated — "
                "consider raising 'max_output_tokens' in config.yaml",
                self._max_output_tokens,
            )

        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if not text:
            raise SummarizerError(f"Claude returned no text (stop_reason={response.stop_reason})")

        usage = response.usage
        return SummaryResult(
            text=text,
            tokens_input=usage.input_tokens,
            tokens_output=usage.output_tokens,
            cost_usd=self._cost(usage.input_tokens, usage.output_tokens),
            stop_reason=response.stop_reason,
        )
