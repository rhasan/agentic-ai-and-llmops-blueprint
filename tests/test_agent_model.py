"""Unit tests for the agent model factory. Pure — no LLM, no network."""

import pytest
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel

from financial_doc_ai.serving.agent_model import build_model, split_model


def test_split_on_first_delimiter_preserves_model_tag():
    # The model's own ':' tag must survive: split only on the provider delimiter.
    assert split_model("ollama/qwen2.5:3b-instruct") == ("ollama", "qwen2.5:3b-instruct")


def test_split_accepts_colon_provider_separator():
    assert split_model("azure:my-deployment") == ("azure", "my-deployment")


def test_split_missing_prefix_raises():
    with pytest.raises(ValueError):
        split_model("bare-model-no-provider")


def test_build_ollama_returns_native_model_at_v1_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_API_BASE", "http://ollama:11434")
    model = build_model("ollama/qwen2.5:3b-instruct")
    assert isinstance(model, OllamaModel)
    assert model.model_name == "qwen2.5:3b-instruct"
    assert str(model.client.base_url) == "http://ollama:11434/v1/"


def test_build_azure_wires_native_provider_from_litellm_env(monkeypatch):
    # Azure gets an explicit native model wired from our litellm-style .env vars
    # (AzureProvider's own AZURE_OPENAI_* names are not what we store).
    monkeypatch.setenv("LLM_API_BASE", "https://my-resource.openai.azure.com/")
    monkeypatch.setenv("AZURE_API_KEY", "sk-test")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-10-21")
    model = build_model("azure/gpt-5.4-mini")
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "gpt-5.4-mini"  # the deployment name


def test_build_other_cloud_passes_through_as_pydanticai_spec():
    # Providers with no explicit branch resolve from their own env; hand a bare string.
    assert build_model("bedrock/anthropic.claude-3") == "bedrock:anthropic.claude-3"


def test_build_defaults_to_agent_model_env(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "bedrock/anthropic.claude-3")
    assert build_model() == "bedrock:anthropic.claude-3"
