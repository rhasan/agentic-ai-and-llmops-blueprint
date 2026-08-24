import os
import litellm


class Embedder:
    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
    ) -> None:
        # Read config once at construction so the asset builds this a single time.
        self.model = model or os.environ["EMBEDDING_MODEL"]  # fail loudly if missing
        self.api_base = api_base or os.environ.get("EMBEDDING_API_BASE")


    def embed(self, texts: list[str]) -> list[list[float]]:
        response = litellm.embedding(
            model=self.model,
            input=texts,
            api_base=self.api_base,
        )
        # response.data is a list of {"embedding": [...], "index": n}.
        # Sort by index so output order matches input order — don't assume
        # the provider returns them pre-ordered.
        ordered = sorted(response.data, key=lambda d: d["index"])
        return [d["embedding"] for d in ordered]