from pathlib import Path

from app.knowledge.authoring import AuthoredDocument, DishFrontMatter
from app.knowledge.wiki_quality import is_wiki_boilerplate


def test_source_boundary_disclaimer_is_recognized_but_food_prose_is_not() -> None:
    assert is_wiki_boilerplate(
        "This is general culinary guidance, not a statement about one merchant's recipe."
    )
    assert not is_wiki_boilerplate(
        "The chicken is fried until the coating is crisp and is commonly served hot."
    )


def test_authored_document_type_remains_importable_for_audit_contract() -> None:
    # A small type-level regression: the quality module consumes authored input,
    # not only compiled chunks whose provenance context has already been reduced.
    document = AuthoredDocument(
        path=Path("test.md"),
        front_matter=DishFrontMatter(
            concept_id="dish_test",
            concept_type="FAMILY",
            name_ko="테스트",
            name_en="Test dish",
            aliases=[],
            language="en",
            parents=[],
            source_type="SYNTHETIC_WIKI",
            source_refs=["test"],
            license_state="SYNTHETIC",
            review_status="REVIEWED_DEMO",
            is_synthetic=True,
            version="test-v1",
            updated_at="2026-08-19",
        ),
        front_matter_payload={},
        body="Test body",
        content_contract="PROSE_PARAGRAPHS_V2",
        paragraphs=[],
        facets={},
    )

    assert document.front_matter.source_type == "SYNTHETIC_WIKI"
