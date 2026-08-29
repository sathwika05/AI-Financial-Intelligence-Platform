from langchain_text_splitters import RecursiveCharacterTextSplitter
import logging


logger = logging.getLogger(__name__)


# Split large text/documents into smaller overlapping chunks
# so they can be embedded and retrieved efficiently in RAG pipelines

text_splitter = RecursiveCharacterTextSplitter(

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
    chunks = text_splitter.split_text(content)

    # Whitespace only. An earlier version also stripped leading periods, to
    # tidy an artefact of the sentence separator; measured over the whole
    # corpus it never once fired on real prose, and meanwhile it rewrote
    # any chunk that legitimately began with one -- ".75 percent" became
    # "75 percent", which in a filing is a different number.
    chunks = [c.strip() for c in chunks if c.strip()]
    logger.info(f"[CHUNKING] Split into {len(chunks)} chunks")
    return chunks




