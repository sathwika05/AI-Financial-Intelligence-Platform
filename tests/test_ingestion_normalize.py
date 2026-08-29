"""
Cleaning extracted text before it is chunked.

Everything here is a PDF artefact rather than an editorial one: a word
broken across a line by the typesetter, a page number that is furniture
rather than content, the blank space a page break leaves behind. None of
it means anything to a reader, and all of it survives into a chunk and
then into an embedding unless it is removed first.

Deliberately conservative. A normaliser that removes real content is far
worse than one that leaves a stray page number in, because the loss is
invisible: the chunk still looks fine, it just no longer says what the
filing said.
"""


class TestJoiningBrokenWords:
    def test_a_word_split_across_a_line_is_rejoined(self):
        """
        Typesetters hyphenate at the margin. Left alone, "consen-" and
        "sus" are embedded as two tokens that mean nothing, and the word
        the sentence turned on is not searchable.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("revenue above consen-\nsus for the year")

        assert "consensus" in text

    def test_a_real_hyphenated_term_is_left_alone(self):
        """
        "year-over-year" is one word with a hyphen in it, not a word broken
        across a line. The difference is the line break.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("year-over-year growth was strong")

        assert "year-over-year" in text

    def test_a_hyphen_before_a_capital_is_not_joined(self):
        """
        A line ending in a hyphen followed by a new sentence or a proper
        noun is a real hyphen, not a break: joining it invents a word.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("the Apple-\nSamsung dispute")

        assert "Apple-Samsung" in text or "Apple-\nSamsung" in text
        assert "Applesamsung" not in text


class TestDroppingPageFurniture:
    def test_a_bare_page_number_is_dropped(self):
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("Gross margin expanded.\n\n12\n\nItem 7.")

        assert "\n12\n" not in text
        assert "Gross margin expanded." in text
        assert "Item 7." in text

    def test_a_numbered_page_marker_is_dropped(self):
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("Revenue rose.\n\nPage 12 of 340\n\nItem 7.")

        assert "Page 12 of 340" not in text
        assert "Revenue rose." in text

    def test_a_number_that_is_the_content_is_kept(self):
        """
        A filing is mostly numbers. Only a line that is *nothing but* a
        page marker goes; a figure standing on its own line stays.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("Total revenue\n\n394,328\n\nOperating income")

        assert "394,328" in text


class TestWhitespace:
    def test_runs_of_blank_lines_collapse(self):
        """
        Page breaks leave gaps. The chunker splits on a blank line, so a
        run of them produces empty and near-empty chunks.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("First section.\n\n\n\n\nSecond section.")

        assert "\n\n\n" not in text
        assert "First section." in text
        assert "Second section." in text

    def test_trailing_whitespace_on_a_line_is_removed(self):
        from backend.ingestion.normalize import normalize_document

        assert normalize_document("Revenue rose.   \nMargin fell.") == (
            "Revenue rose.\nMargin fell."
        )

    def test_markdown_headings_survive(self):
        """
        Docling's export marks sections with headings, and the chunker
        splits on them. Normalising them away would undo that.
        """
        from backend.ingestion.normalize import normalize_document

        text = normalize_document("# Item 1. Business\n\nApple designs.")

        assert "# Item 1. Business" in text

    def test_empty_input_stays_empty(self):
        from backend.ingestion.normalize import normalize_document

        assert normalize_document("") == ""
        assert normalize_document("   \n\n  ") == ""
