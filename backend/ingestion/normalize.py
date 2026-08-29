"""
Cleaning extracted text before it is chunked.

Everything removed here is a PDF artefact rather than an editorial one: a
word the typesetter broke across a line, a page number that is furniture
rather than content, the blank space a page break leaves behind. None of
it means anything to a reader, and all of it survives into a chunk and
then into an embedding unless it is taken out first.

Deliberately conservative. A normaliser that removes real content is far
worse than one that leaves a stray page number in, because the loss is
invisible -- the chunk still reads fine, it just no longer says what the
filing said. Every rule below is narrow for that reason, and the ones
that were tempting but lossy (stripping repeated headers and footers by
frequency) are not here at all: in a filing, a line that repeats is as
likely to be a real table cell as a running head.
"""
from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)


# A word broken at the margin: lowercase, hyphen, line break, lowercase.
# Both sides must be lowercase, which is what separates a typesetter's
# break from a real hyphen -- "Apple-\nSamsung" is a compound, and joining
# it would invent a word that is in neither the filing nor any query.
_BROKEN_WORD = re.compile(r"(?<=[a-z])-\n(?=[a-z])")

# A line that is nothing but a page marker. Bounded to four digits and
# refusing any grouping punctuation, so a figure standing alone on its own
# line -- which in a filing is most lines -- is never mistaken for one.
_PAGE_MARKER = re.compile(
    r"""^\s*(?:
        -\s*\d{1,4}\s*-            # - 12 -
        |
        (?:page\s+)?\d{1,4}         # 12   /   Page 12
        (?:\s+of\s+\d{1,4})?        #        ... of 340
    )\s*$""",
    re.IGNORECASE | re.VERBOSE,
)

# Three or more newlines: what a page break leaves behind. The chunker
# splits on a blank line, so a run of them yields empty and near-empty
# chunks that cost an embedding each and retrieve nothing.
_BLANK_RUN = re.compile(r"\n{3,}")


def normalize_document(text: str) -> str:
    """
    Extracted text, with the typesetting taken back out.

    Structure is preserved on purpose -- headings, paragraph breaks and
    line breaks all survive -- because the chunker splits on them. This is
    not the same normalisation used to hash a document for duplicate
    detection, which flattens whitespace entirely and would destroy that.
    """
    if not text or not text.strip():
        return ""

    # Windows line endings first, so every rule after this sees one shape.
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")

    cleaned = _BROKEN_WORD.sub("", cleaned)

    kept: list[str] = []
    dropped = 0

    for line in cleaned.split("\n"):
        line = line.rstrip()

        if _PAGE_MARKER.match(line):
            dropped += 1
            continue

        kept.append(line)

    if dropped:
        logger.debug("[INGEST] Dropped %s page marker line(s)", dropped)

    return _BLANK_RUN.sub("\n\n", "\n".join(kept)).strip()
