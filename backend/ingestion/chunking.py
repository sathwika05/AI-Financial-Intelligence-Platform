import logging


logger = logging.getLogger(__name__)


# Built on first use, not at import.
#
# `import langchain_text_splitters` runs that package's __init__, which
# imports its sentence_transformers submodule, which imports torch: about
# 450MB resident before this module has split a single string. main.py
# reaches here unconditionally through vector_routes -> indexing_service,
# so every deployment paid it -- including the portfolio one, which never
# chunks anything, because ingestion is not mounted there. That was the
# difference between importing the app in ~300MB and in 574MB, and a
# 512MB instance was killed mid-import with no traceback to show for it.
#
# Nothing outside this module touches the splitter, so deferring it needs
# no change anywhere else.
_text_splitter = None


def _splitter():
    """The shared splitter, built once."""
    global _text_splitter

    if _text_splitter is None:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        _text_splitter = _build(RecursiveCharacterTextSplitter)

    return _text_splitter


# Split large text/documents into smaller overlapping chunks
# so they can be embedded and retrieved efficiently in RAG pipelines

def _build(RecursiveCharacterTextSplitter):
    return RecursiveCharacterTextSplitter(

        # Maximum size of each chunk (in characters)
        chunk_size=500,

        # Number of overlapping characters between consecutive chunks
        # Helps preserve context across chunks
        chunk_overlap=50,

        # Function used to measure chunk length
        # Here, chunk size is calculated using Python's len()
        length_function=len,
        
        is_separator_regex=True,

        # Order of separators used while splitting text
        # Tries larger logical breaks first before smaller ones
        separators=[
        "\n\n",          # 1st priority: paragraph break — keeps paragraphs together
        "\n",            # 2nd priority: new line — keeps lines together
        r"(?<=\.)\s+",   # 3rd priority: splits AFTER a period followed by whitespace
                         #   (?<=\.) is a lookbehind — matches whitespace that comes after a period
                         #   \s+ matches one or more whitespace chars (space, tab, newline)
                         #   Result: period stays with LEFT chunk where it belongs
                         #   e.g. "...efficiency.  Apple..." → "...efficiency." | "Apple..."
        r"\s+",          # 4th priority: any whitespace (spaces, tabs, double spaces)
                         #   safer than " " which only matches single space
                         #   prevents empty chunks from double spaces
        ""               # 5th priority: last resort — splits character by character
                         #   always works but breaks words, avoid if possible
        ]

        )

def chunk_text(content: str) -> list[str]:
    """
    Split document into overlapping chunks.
    Returns empty list if content is empty or None.
    """
    if not content or not content.strip():
        logger.warning("[CHUNKING] Empty content received")
        return []
    chunks = _splitter().split_text(content)

    # Whitespace only. An earlier version also stripped leading periods, to
    # tidy an artefact of the sentence separator; measured over the whole
    # corpus it never once fired on real prose, and meanwhile it rewrote
    # any chunk that legitimately began with one -- ".75 percent" became
    # "75 percent", which in a filing is a different number.
    chunks = [c.strip() for c in chunks if c.strip()]
    logger.info(f"[CHUNKING] Split into {len(chunks)} chunks")
    return chunks






import hashlib
import re
from dataclasses import dataclass


# A Markdown ATX heading: what Docling emits for a filing's section
# titles. Matched at the start of a line so a "#" inside a sentence is
# left alone.
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


@dataclass(frozen=True)
class SectionChunk:
    """One chunk, and the heading it fell under."""

    content: str
    section: str | None


def chunk_uid(*, document_id: int, chunk_index: int, content: str) -> str:
    """
    A chunk's identity, stable across reindexing.

    The primary key is an autoincrementing integer that changes every time
    a document is reindexed, so nothing could answer "did this document's
    chunks actually change?" -- which is the question a consistency check
    has to ask.

    Position is part of the identity, and so is the document: boilerplate
    repeats across filings, and two documents sharing a sentence must not
    share a chunk identity or one document's reindex would appear to
    change the other's.
    """
    material = f"{document_id}:{chunk_index}:{content}"

    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def chunk_with_sections(content: str) -> list[SectionChunk]:
    """
    Chunk a document, remembering which heading each chunk fell under.

    Docling recovers a filing's headings; until now the chunker threw them
    away, leaving a passage about margins with nothing to say it came from
    Item 7.

    Splitting happens per section rather than over the whole document, so
    a chunk never straddles a section boundary. For a document with no
    headings -- every news article in this corpus -- that degenerates to
    exactly one section and the same chunks chunk_text would produce.
    """
    if not content or not content.strip():
        return []

    chunks: list[SectionChunk] = []

    for section, body in _sections(content):
        for piece in chunk_text(body):
            chunks.append(SectionChunk(content=piece, section=section))

    return chunks


def _sections(content: str) -> list[tuple[str | None, str]]:
    """
    Split text into (heading, body) pairs.

    The heading line itself is dropped from the body: it is metadata now,
    and leaving it in as well spends embedding budget twice on the same
    words.
    """
    sections: list[tuple[str | None, str]] = []

    current: str | None = None
    body: list[str] = []

    for line in content.split("\n"):
        match = _HEADING.match(line)

        if not match:
            body.append(line)
            continue

        if any(part.strip() for part in body):
            sections.append((current, "\n".join(body)))

        current = match.group(2).strip() or None
        body = []

    if any(part.strip() for part in body):
        sections.append((current, "\n".join(body)))

    return sections
