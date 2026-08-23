from app.knowledge.passage_ranking import (
    normalized_tokens,
    rank_component_wiki_passages,
    rank_wiki_passages,
)


def _row(
    chunk_id: str,
    content: str,
    *,
    facet: str = "character",
    depth: int = 0,
    chunk_index: int = 0,
) -> dict[str, object]:
    return {
        "chunk_id": chunk_id,
        "content": content,
        "facet": facet,
        "depth": depth,
        "chunk_index": chunk_index,
    }


def test_preference_relevant_passage_beats_generic_chunk_order() -> None:
    rows = [
        _row("chunk-001", "This dish is widely enjoyed in many settings."),
        _row(
            "chunk-999",
            "The chicken is deep-fried for a crispy exterior and served hot.",
            facet="preparation",
            chunk_index=9,
        ),
    ]

    ranked = rank_wiki_passages(
        rows,
        selected_groups={
            "main_ingredients": ["CHICKEN"],
            "textures": ["CRISPY"],
            "cooking_methods": ["FRIED"],
        },
        limit=1,
    )

    assert [row["chunk_id"] for row in ranked] == ["chunk-999"]


def test_grounding_evidence_chunk_has_priority_and_output_is_deduplicated() -> None:
    rows = [
        _row("chunk-a", "A spicy chilli broth.", chunk_index=0),
        _row("chunk-b", "A spicy chilli broth.", chunk_index=1),
        _row("chunk-c", "A noodle dish with a mild broth.", chunk_index=2),
    ]

    ranked = rank_wiki_passages(
        rows,
        selected_groups={"food_forms": ["NOODLES"]},
        preferred_evidence_ids={"chunk-a"},
        limit=2,
    )

    assert [row["chunk_id"] for row in ranked] == ["chunk-a", "chunk-c"]


def test_token_boundaries_do_not_treat_wheat_as_heat() -> None:
    assert "heat" not in normalized_tokens("wheat breading")
    ranked = rank_wiki_passages(
        [
            _row("wheat", "The recipe may contain wheat breading."),
            _row("heat", "Chilli heat makes the broth spicy."),
        ],
        selected_groups={"flavors": ["SPICY"]},
        limit=1,
    )

    assert [row["chunk_id"] for row in ranked] == ["heat"]


def test_compound_menu_passages_reserve_grounding_for_every_component() -> None:
    rows = [
        {
            **_row("cold-noodles", "Cold buckwheat noodles are served in chilled broth."),
            "member_concept_id": "noodles",
            "membership_role": "COMPONENT",
        },
        {
            **_row("cutlet", "A pork cutlet is breaded and fried."),
            "member_concept_id": "cutlet",
            "membership_role": "COMPONENT",
        },
        {
            **_row("generic", "This is a popular set menu."),
            "member_concept_id": "set",
            "membership_role": "PRIMARY",
        },
    ]

    ranked = rank_component_wiki_passages(
        rows,
        selected_groups={"food_forms": ["NOODLES"]},
        limit=2,
    )

    assert {row["chunk_id"] for row in ranked} == {"cold-noodles", "cutlet"}


def test_single_component_ranking_keeps_the_configured_limit() -> None:
    rows = [
        {
            **_row("primary", "A hot noodle soup."),
            "member_concept_id": "noodles",
            "membership_role": "PRIMARY",
        },
        {
            **_row("component", "Noodles are served in broth."),
            "member_concept_id": "noodles",
            "membership_role": "COMPONENT",
        },
    ]

    ranked = rank_component_wiki_passages(
        rows,
        selected_groups={"food_forms": ["NOODLES"]},
        limit=1,
    )

    assert len(ranked) == 1
