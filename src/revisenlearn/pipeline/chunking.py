"""Chunking (spec §8.3 **[JUDGEMENT]**).

"Group consecutive note blocks under the same heading, capped at roughly 1200
tokens per chunk with a one-block overlap. Chunks that are a single bullet
under 15 words should be merged with their neighbours. Send the
Subject/Topic/Subtopic path as context with every chunk."
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Spec §8.3. Tokens are estimated at four characters each — good enough to
#: keep a chunk inside a model's comfortable window, and it avoids shipping a
#: tokeniser just to decide where to cut.
MAX_CHUNK_TOKENS = 1200
CHARS_PER_TOKEN = 4
SHORT_BULLET_WORDS = 15
HEADINGS = ("heading1", "heading2", "heading3")


@dataclass
class ChunkBlock:
    block_id: int
    note_id: int
    block_type: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def estimated_tokens(self) -> int:
        return max(1, len(self.text) // CHARS_PER_TOKEN)


@dataclass
class Chunk:
    blocks: list[ChunkBlock] = field(default_factory=list)

    @property
    def block_ids(self) -> list[int]:
        return [b.block_id for b in self.blocks]

    @property
    def estimated_tokens(self) -> int:
        return sum(b.estimated_tokens for b in self.blocks)

    def render(self, path: str) -> str:
        """The text sent to the model, with the hierarchy path as context and
        block ids attached so extraction can cite its sources (§11.1)."""
        lines = [f"PATH: {path}", ""]
        for block in self.blocks:
            prefix = {
                "heading1": "# ", "heading2": "## ", "heading3": "### ",
                "bullet_list_item": "- ", "numbered_list_item": "- ",
                "quote": "> ", "code_block": "", "divider": "",
            }.get(block.block_type, "")
            lines.append(f"{prefix}{block.text} [block {block.block_id}]")
        return "\n".join(lines).strip()


def chunk_blocks(blocks: list[ChunkBlock]) -> list[Chunk]:
    """Group blocks into chunks, splitting on headings and the token cap."""
    if not blocks:
        return []

    chunks: list[Chunk] = []
    current: list[ChunkBlock] = []

    def flush() -> None:
        if current:
            chunks.append(Chunk(blocks=list(current)))
            current.clear()

    for block in blocks:
        starts_section = block.block_type in HEADINGS and current
        too_big = (
            current
            and sum(b.estimated_tokens for b in current) + block.estimated_tokens
            > MAX_CHUNK_TOKENS
        )
        if starts_section or too_big:
            previous = current[-1] if current else None
            flush()
            # One-block overlap, so a concept spanning the cut is still visible
            # whole to at least one chunk (§8.3).
            if too_big and previous is not None:
                current.append(previous)
        current.append(block)

    flush()
    return _merge_short_chunks(chunks)


def _merge_short_chunks(chunks: list[Chunk]) -> list[Chunk]:
    """"Chunks that are a single bullet under 15 words should be merged with
    their neighbours" (§8.3)."""
    if len(chunks) <= 1:
        return chunks

    merged: list[Chunk] = []
    for chunk in chunks:
        is_stub = (
            len(chunk.blocks) == 1
            and chunk.blocks[0].words < SHORT_BULLET_WORDS
        )
        if is_stub and merged:
            merged[-1].blocks.extend(chunk.blocks)
        else:
            merged.append(chunk)

    # A stub that led the note has no previous neighbour; fold it forwards.
    if (
        len(merged) > 1
        and len(merged[0].blocks) == 1
        and merged[0].blocks[0].words < SHORT_BULLET_WORDS
    ):
        merged[1].blocks = merged[0].blocks + merged[1].blocks
        merged.pop(0)
    return merged
