"""Model factory for the agent loop: `AGENT_MODEL` env -> a PydanticAI model.

Model-agnostic by config, mirroring the rest of the app: the same litellm-style
`provider/model` strings in `.env` (e.g. `ollama/qwen2.5:3b-instruct`,
`azure/<deployment>`, `bedrock/<id>`) drive both the one-pass LiteLLM callers
(rewriter, generator) and this loop — one `.env` switch moves everything.

Unlike those callers, the loop runs on PydanticAI's *native* providers (no
LiteLLM in the loop, no proxy). Two providers need explicit wiring because our
`.env` uses litellm-style credential names, not PydanticAI's:
- Ollama — an OpenAI-compatible endpoint at `LLM_API_BASE` + `/v1`.
- Azure — PydanticAI's `AzureProvider` reads `AZURE_OPENAI_*`, but our `.env`
  carries `LLM_API_BASE` / `AZURE_API_KEY` / `AZURE_API_VERSION` (the litellm
  names, shared with the rest of the app + GraphRAG's `_configure_models`), so
  we hand those to the provider directly. One `.env` switch still moves
  everything, no duplicated secrets.
Other cloud providers pass through PydanticAI's own `provider:model` inference.
See docs/specs/agentic-orchestration-approaches.md.
"""

import os
import re

from pydantic_ai.models import Model
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.ollama import OllamaProvider


def split_model(model_spec: str) -> tuple[str, str]:
    """Split "<provider><sep><model>" on the FIRST '/' or ':' delimiter.

    Splitting on the first delimiter keeps the model's own separators intact:
    `ollama/qwen2.5:3b-instruct` -> ("ollama", "qwen2.5:3b-instruct").
    """
    m = re.search(r"[/:]", model_spec)
    if not m:
        raise ValueError(f"model spec missing provider prefix: {model_spec!r}")
    return model_spec[: m.start()], model_spec[m.start() + 1 :]


def build_model(model_spec: str | None = None) -> Model | str:
    """Build a PydanticAI model from a litellm-style `provider/model` spec.

    Defaults to the `AGENT_MODEL` env var. Ollama and Azure return native models
    wired from our litellm-style `.env` vars (see module docstring); every other
    provider passes through as a `provider:model` string for PydanticAI to
    resolve (the token must be a valid PydanticAI provider name, e.g. `google-gla`
    not `gemini`).
    """
    spec = model_spec or os.environ["AGENT_MODEL"]
    provider, name = split_model(spec)
    if provider == "ollama":
        base = os.environ["LLM_API_BASE"].rstrip("/")
        return OllamaModel(name, provider=OllamaProvider(base_url=f"{base}/v1"))
    if provider == "azure":
        return OpenAIChatModel(
            name,  # the Azure deployment name
            provider=AzureProvider(
                azure_endpoint=os.environ["LLM_API_BASE"],
                api_key=os.environ["AZURE_API_KEY"],
                api_version=os.environ["AZURE_API_VERSION"],
            ),
        )
    return f"{provider}:{name}"
