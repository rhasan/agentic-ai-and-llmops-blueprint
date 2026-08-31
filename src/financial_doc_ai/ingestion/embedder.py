import os
from collections.abc import Iterator

import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)


def _chunked(seq: list[str], n: int) -> Iterator[list[str]]:
    """Yield successive n-sized batches from seq."""
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


class Embedder:
    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        # Read config once at construction so the asset builds this a single time.
        self.model = model or os.environ["EMBEDDING_MODEL"]  # fail loudly if missing
        self.api_base = api_base or os.environ.get("EMBEDDING_API_BASE")
        # Texts per request. Cloud providers accept many at once; keep it small
        # for tight rate limits, raise it (e.g. 50) for Ollama or ample quota.
        self.batch_size = batch_size or int(os.environ.get("EMBEDDING_BATCH_SIZE", "16"))

    @retry(
        retry=retry_if_exception_type(litellm.exceptions.RateLimitError),
        wait=wait_random_exponential(multiplier=1, max=60),
        stop=stop_after_attempt(8),
        reraise=True,
    )
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed one batch, retrying with jittered backoff on HTTP 429."""
        response = litellm.embedding(model=self.model, input=texts, api_base=self.api_base)
        # The provider may not preserve input order; sort by 'index' to realign.
        ordered = sorted(response.data, key=lambda d: d["index"])
        return [d["embedding"] for d in ordered]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed all texts, batching to cut round-trips and respect rate limits."""
        all_embeddings: list[list[float]] = []
        for batch in _chunked(texts, self.batch_size):
            all_embeddings.extend(self._embed_batch(batch))
        return all_embeddings
