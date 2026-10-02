"""The answer contract: a list of independently-cited blocks.

The agent emits its answer as discrete blocks rather than free prose, and that
structure is what makes the grounding gate workable. Two reasons:

- **The unit is structural, not inferred.** The previous gate asked an LLM judge to
  decompose finished prose into claims, and that step was the unreliable one — it
  extracted citation text and lead-in sentences as claims, and sometimes invented
  them, which refused ~25% of correct answers. A block is a unit because the model
  *emitted* it as one; nothing has to guess where the seams are.
- **A failure can drop one block instead of the whole answer.** That only works if
  blocks stand alone, hence the self-containment rule below.

Each block carries the `chunk_id`s of the passages supporting it, so grounding can
check a block against *the passages it actually cites* (what
docs/initial-system-description.md asks for) rather than against the union of
everything retrieved. The same ids let a future UI resolve a citation back to its
original text via `ChunkStore`.

See docs/specs/grounding-redesign.md.
"""

from pydantic import BaseModel, Field


class AnswerBlock(BaseModel):
    """One self-contained statement plus the passages that support it."""

    text: str = Field(
        description=(
            "One self-contained statement. It must stand on its own: no 'this', "
            "'it also', or references to another block, since any block may be "
            "dropped. Plain prose — no inline citation markers or filing names."
        )
    )
    chunk_ids: list[str] = Field(
        description=(
            "The chunk_id of every retrieved passage that supports this statement. "
            "Copy them verbatim from the citation of the passages you used. At "
            "least one."
        )
    )


class CitedAnswer(BaseModel):
    """The agent's final answer: ordered blocks, each independently attributable.

    Rendered to the reader as its blocks joined in order, so it reads as prose while
    staying checkable and attributable block by block.
    """

    blocks: list[AnswerBlock]

    def joined(self) -> str:
        """The answer as display text."""
        return "\n\n".join(block.text for block in self.blocks)
