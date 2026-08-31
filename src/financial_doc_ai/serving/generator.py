"""Answer generation: turns retrieved chunks into a cited, prose answer.

Library code called by `Orchestrator.answer` — not an MCP tool. Mirrors
`QueryRewriter`'s shape (async `litellm.acompletion`, structured output via
`response_format`, prompt fetched through the registry with an injection seam
for tests). See docs/specs/generation.md.
"""

import os

import litellm
from pydantic import BaseModel

from financial_doc_ai.prompts.registry import fetch_system_prompt
from financial_doc_ai.retrieval.search import SearchResult


class GeneratedAnswer(BaseModel):
    answer: str                 # prose, may contain inline [n] markers
    citations: list[int] = []   # chunk labels used (1-based, into the results list)
    can_answer: bool            # false => abstained; answer is a brief refusal


def _format_passage(index: int, result: SearchResult) -> str:
    citation = result.citation
    labels = [
        value
        for value in (citation.company, citation.doc_type, citation.period)
        if value is not None
    ]
    prefix = f"[{index}]"
    if labels:
        prefix += f" ({' '.join(labels)})"
    return f"{prefix} {result.text}"


class AnswerGenerator:
    def __init__(
        self,
        model: str | None = None,
        api_base: str | None = None,
        system_prompt: str | None = None,   # injected in tests -> no live Phoenix
        prompt_key: str = "answer_generation",
    ) -> None:
        self.model = model or os.environ["ANSWER_GENERATION_MODEL"]
        self.api_base = api_base or os.environ.get("LLM_API_BASE")
        self.system_prompt = (
            system_prompt if system_prompt is not None else fetch_system_prompt(prompt_key)
        )

    async def generate(self, question: str, results: list[SearchResult]) -> GeneratedAnswer:
        if not results:
            return GeneratedAnswer(
                answer="No passages were retrieved to answer from.",
                citations=[],
                can_answer=False,
            )

        passages = "\n".join(
            _format_passage(i, r) for i, r in enumerate(results, start=1)
        )
        user_content = f"Question: {question}\n\nPassages:\n{passages}"
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Async LLM call: the online path serves many users and this wait is slow
        # (seconds), so the worker must be free to serve other requests meanwhile.
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            api_base=self.api_base,
            response_format=GeneratedAnswer,
            temperature=0.0,
        )
        parsed = GeneratedAnswer.model_validate_json(response.choices[0].message.content)

        # Defensive: the model's structured output isn't schema-validated against
        # `results`, so drop any label outside the range we can actually map back.
        valid = [c for c in parsed.citations if 1 <= c <= len(results)]
        return parsed.model_copy(update={"citations": valid})
