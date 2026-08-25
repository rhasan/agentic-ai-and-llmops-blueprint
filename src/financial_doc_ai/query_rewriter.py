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

SYSTEM_PROMPT = """You rewrite a financial-analyst's question into a structured retrieval request.

Return:
- query_type: "compare" ONLY when the analyst asks to contrast the SAME topic or metric across multiple companies or multiple time periods (e.g. "compare Apple and Microsoft revenue", "how did revenue change from 2022 to 2024"). Everything else is "other". In particular, checking whether two documents agree or match (reconciliation), or asking about a single document or version, is "other", NOT "compare".
- rewritten_query: a single self-contained question with any follow-up references resolved from the conversation. Keep company and period words in the text. Do NOT introduce a comparison or any intent the question does not already contain.
- filters: extract a filter ONLY when the question explicitly states it. If the question does not state a filter, set it to null. Never infer, guess, or copy a default into a filter.
  - company: list of company names exactly as written.
  - doc_type: list, only if the question names a document type (one of: 10-K, 10-Q, 8-K, contract). Do NOT infer a document type from the topic — e.g. "net sales in 2024" does NOT imply 10-K, so leave doc_type null.
  - period: list of fiscal years the question states, like "2024". If no year is stated, set period to null. Never put "current" or a version word in period.
  - version: "current" unless the question explicitly asks for an older or superseded version."""

class QueryRewriter:
    def __init__(self, model: str | None = None, api_base: str | None = None) -> None:
        self.model = model or os.environ["QUERY_REWRITE_MODEL"]
        self.api_base = api_base or os.environ.get("LLM_API_BASE")

    def rewrite(self, question: str, session_context: str | None = None) -> QueryRewrite:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
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
