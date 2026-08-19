from app.knowledge.passage_ranking import normalized_tokens, rank_wiki_passages


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
