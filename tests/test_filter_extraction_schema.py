"""
The filter schema Groq receives decides whether filtering happens at all.

    class DocumentFilters(BaseModel):
        company_names: List[str] = Field(default_factory=list)
        doc_type:      str | None = None
        source:        str | None = None

No docstring, and two of the three fields carry no description, so the
JSON schema sent to the provider is three untitled fields. Groq's small
tier answers in plain text instead of calling the tool and then rejects
its own response:

    400 tool_use_failed
    failed_generation: 'company_names: []\\nsource: None'

extract_filters catches that and returns {}, which means no company
filter, which means a question naming two companies retrieves across the
whole corpus. Observed live on preprod.

Measured on gpt-oss-20b at temperature zero, four queries x three
attempts:

    bare schema (as shipped)     6/12
    docstring + descriptions    12/12

Note this is the opposite of what the same change did for
RankingKeywords, where descriptions made no difference and the fix was to
recover the generation from the rejection. Two schemas, two prompts, two
different answers -- which is why both were measured rather than reasoned
about.
"""
from __future__ import annotations

import pytest

from backend.retrieval.query_filters import DocumentFilters


class TestTheSchemaIsDescribed:
    def test_the_model_carries_a_docstring(self):
        assert DocumentFilters.__doc__, (
            "an undescribed schema halved the tool-call success rate"
        )

    @pytest.mark.parametrize(
        "field", ["company_names", "doc_type", "source"]
    )
    def test_every_field_is_described(self, field):
        description = DocumentFilters.model_fields[field].description

        assert description, f"{field} carries no description"

    def test_the_descriptions_reach_the_json_schema(self):
        schema = DocumentFilters.model_json_schema()

        assert schema.get("description")

        for field in ("company_names", "doc_type", "source"):
            assert schema["properties"][field].get("description"), (
                f"{field} description did not survive into the schema"
            )


class TestTheShapeIsUnchanged:
    """
    Descriptions only. Changing the fields would change what every
    downstream filter expects.
    """

    def test_the_fields_are_the_same_three(self):
        assert set(DocumentFilters.model_fields) == {
            "company_names",
            "doc_type",
            "source",
        }

    def test_company_names_still_defaults_to_empty(self):
        assert DocumentFilters().company_names == []

    def test_the_optional_fields_still_default_to_none(self):
        filters = DocumentFilters()

        assert filters.doc_type is None
        assert filters.source is None

    def test_it_still_drops_none_on_dump(self):
        """
        extract_filters relies on exclude_none to build the filter dict.
        """
        dumped = DocumentFilters(
            company_names=["NVIDIA Corporation"]
        ).model_dump(exclude_none=True)

        assert dumped == {"company_names": ["NVIDIA Corporation"]}
