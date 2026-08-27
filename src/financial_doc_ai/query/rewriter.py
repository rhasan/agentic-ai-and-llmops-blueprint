from typing import Literal

from pydantic import BaseModel


class Filters(BaseModel):
    company: list[str] | None = None
    doc_type: list[str] | None = None
    period: list[str] | None = None
    version: str = "current"

class QueryRewrite(BaseModel):
    query_type: Literal["compare", "other"]
    rewritten_query: str
    filters: Filters

import os

import litellm

from financial_doc_ai.prompts.registry import fetch_system_prompt


class QueryRewriter:
    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        system_prompt: str | None = None,   # injected in tests -> no live Phoenix
        prompt_key: str = "query_rewrite",
    ) -> None:
        self.model = model or os.environ["QUERY_REWRITE_MODEL"]
        self.api_base = api_base or os.environ.get("LLM_API_BASE")
        self.system_prompt = (
            system_prompt if system_prompt is not None else fetch_system_prompt(prompt_key)
        )

    def rewrite(self, question: str, session_context: str | None = None) -> QueryRewrite:
        messages = [{"role": "system", "content": self.system_prompt}]
        if session_context:
            messages.append({"role": "user", "content": f"Conversation so far:\n{session_context}"})
        messages.append({"role": "user", "content": question})

        response = litellm.completion(
            model=self.model,
            messages=messages,
            api_base=self.api_base,
            response_format=QueryRewrite,
        )
        return QueryRewrite.model_validate_json(response.choices[0].message.content)
