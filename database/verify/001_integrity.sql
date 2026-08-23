SELECT 'merchant' AS metric, COUNT(*) AS value FROM merchant
UNION ALL SELECT 'menu', COUNT(*) FROM menu
UNION ALL SELECT 'option_item', COUNT(*) FROM menu_option_item
UNION ALL SELECT 'review', COUNT(*) FROM review_snippet
UNION ALL SELECT 'evidence', COUNT(*) FROM evidence
UNION ALL SELECT 'hotel', COUNT(*) FROM address_place
UNION ALL SELECT 'menu_knowledge', COUNT(*) FROM menu_knowledge
UNION ALL SELECT 'menu_dietary_attribute', COUNT(*) FROM menu_dietary_attribute
UNION ALL SELECT 'menu_allergen', COUNT(*) FROM menu_allergen
-- +YOBI STATEMENT
SELECT COUNT(*) AS negative_price_count FROM menu WHERE price < 0
-- +YOBI STATEMENT
SELECT COUNT(*) AS missing_required_option_count
FROM menu_option_group g
WHERE g.required = 1
  AND NOT EXISTS (
    SELECT 1 FROM menu_option_item i
    WHERE i.option_group_id = g.option_group_id AND i.availability = 'AVAILABLE'
  )
-- +YOBI STATEMENT
SELECT COUNT(*) AS null_menu_vector_count FROM menu WHERE embedding_vector IS NULL
-- +YOBI STATEMENT
SELECT COUNT(*) AS null_review_vector_count FROM review_snippet WHERE embedding_vector IS NULL
-- +YOBI STATEMENT
SELECT COUNT(*) AS null_knowledge_vector_count FROM menu_knowledge WHERE embedding_vector IS NULL
-- +YOBI STATEMENT
SELECT menu_id, VECTOR_DISTANCE(
  embedding_vector,
  (SELECT embedding_vector FROM menu WHERE menu_id = 'menu_001_01'),
  COSINE
) AS distance
FROM menu
WHERE embedding_vector IS NOT NULL
ORDER BY distance
FETCH FIRST 5 ROWS ONLY
