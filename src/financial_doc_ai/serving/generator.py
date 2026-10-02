"""The generated-answer shape.

`GeneratedAnswer` is the cited-answer contract shared by the retrieval sources:
`graph_retrieval/search.py` returns one as its sub-answer. It once had an
`AnswerGenerator` (LLM over retrieved chunks) for the deterministic orchestrator
path; that path was removed in favour of the agent loop, which synthesizes its
own prose answer in-loop.
"""

from pydantic import BaseModel


class GeneratedAnswer(BaseModel):
    answer: str                 # prose, may contain inline [n] markers
    citations: list[int] = []   # chunk labels used (1-based, into the results list)
    can_answer: bool            # false => abstained; answer is a brief refusal
