import os
import time

import litellm


class Embedder:
    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        # Batch size is set to 1 to accommodate strict rate limits on new AWS accounts.
        # If you switch back to a local model like Ollama (which has no rate limits),
        # you can safely increase this to 10-50 for much faster ingestion.
        batch_size: int = 1,
    ) -> None:
        # Read config once at construction so the asset builds this a single time.
        self.model = model or os.environ["EMBEDDING_MODEL"]  # fail loudly if missing
        self.api_base = api_base or os.environ.get("EMBEDDING_API_BASE")
        self.batch_size = batch_size

    def _embed_batch(self, texts: list[str], max_retries: int = 8) -> list[list[float]]:
        """
        Embed a single batch of texts with exponential backoff.
        
        Cloud providers (like AWS Bedrock) often return a HTTP 429 (Too Many Requests)
        if we hit their API too fast. This function catches that error and waits
        increasingly longer before trying again.
        """
        for attempt in range(max_retries):
            try:
                response = litellm.embedding(
                    model=self.model,
                    input=texts,
                    api_base=self.api_base,
                )
                
                # Litellm/Provider might not return the embeddings in the exact order
                # we sent the texts. We sort by the 'index' field to ensure the 
                # returned list exactly matches the input list's order.
                ordered = sorted(response.data, key=lambda d: d["index"])
                return [d["embedding"] for d in ordered]
            
            except litellm.exceptions.RateLimitError:
                # Exponential backoff formula: 3 * (2^attempt)
                # Gives wait times of: 3s, 6s, 12s, 24s, 48s, 60s, 60s, 60s
                wait = min(3 * (2 ** attempt), 60)
                time.sleep(wait)
                
        # Final attempt: if we've exhausted all retries and it still fails,
        # we don't catch the error so it bubbles up and stops the pipeline.
        response = litellm.embedding(
            model=self.model,
            input=texts,
            api_base=self.api_base,
        )
        ordered = sorted(response.data, key=lambda d: d["index"])
        return [d["embedding"] for d in ordered]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Main entrypoint: breaks the large list of chunks into smaller batches
        and throttles the requests to stay under cloud provider rate limits.
        """
        all_embeddings: list[list[float]] = []
        
        # Loop over the texts, grabbing chunks of size `self.batch_size`
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            all_embeddings.extend(self._embed_batch(batch))
            
            # Artificial throttle: Pause for 3 seconds between every batch.
            # This is specifically for new AWS accounts which have very low limits.
            # If using Ollama locally, you can remove this sleep entirely.
            if i + self.batch_size < len(texts):
                time.sleep(3)
                
        return all_embeddings