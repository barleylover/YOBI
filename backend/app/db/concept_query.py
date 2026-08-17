from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.structured_recommendation import RecommendationCriteriaV2

SqlDialect = Literal["sqlite", "oracle"]


@dataclass(frozen=True)
class ConceptCandidateQuery:
    sql: str
    parameters: dict[str, Any]


def build_concept_candidate_query(
    *,
    dialect: SqlDialect,
    criteria: RecommendationCriteriaV2,
    knowledge_release_id: str,
    certification_release_id: str,
    service_area_id: str | None,
    excluded_menu_ids: set[str],
    eligibility_as_of: Any,
    candidate_limit: int | None,
) -> ConceptCandidateQuery:
    """Build the shared SQL-first eligibility and concept-support query."""

    selected = [
        (category, option)
        for category, options in criteria.subjective_groups().items()
        for option in options
    ]
    parameters: dict[str, Any] = {
        "knowledge_release_id": knowledge_release_id,
    }
    if selected:
        parameters["selected_category_count"] = len(criteria.subjective_groups())
        if dialect == "sqlite":
            values: list[str] = []
            for index, (category, option) in enumerate(selected):
                values.append(f"(:selected_category_{index},:selected_option_{index})")
                parameters[f"selected_category_{index}"] = category
                parameters[f"selected_option_{index}"] = option
            selected_cte = "selected(category_code,option_code) AS (VALUES " + ",".join(values) + ")"
        else:
            values = []
            for index, (category, option) in enumerate(selected):
                values.append(
                    f"SELECT :selected_category_{index} category_code,"
                    f":selected_option_{index} option_code FROM dual"
                )
                parameters[f"selected_category_{index}"] = category
                parameters[f"selected_option_{index}"] = option
            selected_cte = "selected AS (" + " UNION ALL ".join(values) + ")"
        # Collapse same-category options before scoring.  This is the SQL form of
        # same-category OR: a concept receives the strongest supported selected
        # option once per category, rather than an average over every matching
        # option.  The final HAVING below then implements cross-category AND.
        support_ctes = """,
      selected_support AS (
        SELECT mapping.menu_id,mapping.release_id,mapping.concept_id,
               support.category_code,support.support_strength,
               support.evidence_chunk_id
        FROM menu_concept_map mapping
        JOIN concept_preference_support support
          ON support.knowledge_release_id=mapping.release_id
         AND support.concept_id=mapping.concept_id
         AND support.support_status='SUPPORTED'
         AND support.evidence_chunk_id IS NOT NULL
        JOIN selected
          ON selected.category_code=support.category_code
         AND selected.option_code=support.option_code
        WHERE mapping.release_id=:knowledge_release_id
          AND mapping.mapping_status='MAPPED'
          AND mapping.confidence_band='high'
      ),
      category_support AS (
        SELECT menu_id,release_id,concept_id,category_code,
               MAX(support_strength) AS category_support
        FROM selected_support
        GROUP BY menu_id,release_id,concept_id,category_code
      ),
      concept_evidence AS (
        SELECT menu_id,release_id,concept_id,
               COUNT(DISTINCT evidence_chunk_id) AS reviewed_evidence_count
        FROM selected_support
        GROUP BY menu_id,release_id,concept_id
      )"""
        support_join = """
          JOIN category_support support
            ON support.menu_id=mapping.menu_id
           AND support.release_id=mapping.release_id
           AND support.concept_id=mapping.concept_id
          JOIN concept_evidence support_evidence
            ON support_evidence.menu_id=mapping.menu_id
           AND support_evidence.release_id=mapping.release_id
           AND support_evidence.concept_id=mapping.concept_id
        """
        support_projection = """
          AVG(support.category_support) AS explicit_score,
          MIN(support.category_support) AS min_category_support,
          support_evidence.reviewed_evidence_count AS reviewed_evidence_count
        """
        support_having = (
            "HAVING COUNT(DISTINCT support.category_code)=:selected_category_count"
        )
    else:
        selected_cte = "selected AS (SELECT NULL category_code,NULL option_code WHERE 1=0)"
        if dialect == "oracle":
            selected_cte = "selected AS (SELECT NULL category_code,NULL option_code FROM dual WHERE 1=0)"
        public_visibility = (
            "json_extract(chunk.metadata_json,'$.recommendation_visibility')"
            if dialect == "sqlite"
            else "JSON_VALUE(chunk.metadata_json,'$.recommendation_visibility')"
        )
        # Exact/objective-only requests do not need to multiply every menu row by
        # every knowledge chunk.  Pre-aggregate the small reviewed concept set once,
        # then join it to mapped menus.  This preserves the evidence eligibility
        # boundary while keeping price-only preview and retrieval bounded.
        support_ctes = f""",
      objective_concept AS (
        SELECT closure.release_id,
               closure.descendant_concept_id AS concept_id,
               COUNT(DISTINCT chunk.chunk_id) AS reviewed_evidence_count
        FROM dish_concept_closure closure
        JOIN knowledge_chunk chunk
          ON chunk.release_id=closure.release_id
         AND chunk.concept_id=closure.ancestor_concept_id
        JOIN knowledge_document document
          ON document.release_id=chunk.release_id
         AND document.document_id=chunk.document_id
        WHERE closure.release_id=:knowledge_release_id
          AND closure.inherit_claims=1
          AND document.source_type='SYNTHETIC_WIKI'
          AND document.review_status='REVIEWED_DEMO'
          AND lower(chunk.facet)<>'safety'
          AND (
            {public_visibility}='PUBLIC_RAG'
            OR {public_visibility} IS NULL
          )
        GROUP BY closure.release_id,closure.descendant_concept_id
      )"""
        support_join = """
          JOIN objective_concept objective_support
            ON objective_support.release_id=mapping.release_id
           AND objective_support.concept_id=mapping.concept_id
        """
        support_projection = """
          1.0 AS explicit_score,
          1.0 AS min_category_support,
          objective_support.reviewed_evidence_count AS reviewed_evidence_count
        """
        support_having = ""

    conditions = [
        "menu.availability='AVAILABLE'",
        "menu.price>0",
        "mapping.release_id=:knowledge_release_id",
        "mapping.mapping_status='MAPPED'",
        "mapping.confidence_band='high'",
        "COALESCE(source_detail.liquor,0)=0",
        "COALESCE(source_detail.is_adult,0)=0",
        "COALESCE(source_detail.verified_adult,0)=0",
        "COALESCE(source_detail.soldout,0)=0",
    ]
    if service_area_id:
        parameters["service_area_id"] = service_area_id
        conditions.append("merchant.service_area_id=:service_area_id")
    if excluded_menu_ids:
        excluded_placeholders: list[str] = []
        for index, menu_id in enumerate(sorted(excluded_menu_ids)):
            key = f"excluded_menu_{index}"
            excluded_placeholders.append(f":{key}")
            parameters[key] = menu_id
        conditions.append("menu.menu_id NOT IN (" + ",".join(excluded_placeholders) + ")")

    price_conditions: list[str] = []
    for band in criteria.price_bands:
        price_conditions.append(
            {
                "UNDER_10000": "menu.price<10000",
                "FROM_10000_TO_19999": "menu.price BETWEEN 10000 AND 19999",
                "FROM_20000_TO_29999": "menu.price BETWEEN 20000 AND 29999",
                "OVER_30000": "menu.price>=30000",
            }[band]
        )
    if price_conditions:
        conditions.append("(" + " OR ".join(price_conditions) + ")")

    if criteria.max_spice_level < 5:
        parameters["max_spice_level"] = criteria.max_spice_level
        conditions.extend(
            [
                "menu.spice_status IN ('REVIEWED','VERIFIED')",
                "menu.spice_level<=:max_spice_level",
            ]
        )
    if criteria.dietary_filters.halal_certified_only:
        parameters["certification_release_id"] = certification_release_id
        parameters["eligibility_as_of"] = eligibility_as_of
        conditions.append(
            """EXISTS (
              SELECT 1 FROM merchant_certification certification
              WHERE certification.certification_release_id=:certification_release_id
                AND certification.merchant_id=menu.merchant_id
                AND certification.certification_type='HALAL'
                AND certification.status='ACTIVE'
                AND certification.valid_from<=:eligibility_as_of
                AND (certification.valid_to IS NULL OR certification.valid_to>=:eligibility_as_of)
                AND (
                  certification.scope_type='MERCHANT'
                  OR (certification.scope_type='MENU' AND certification.scope_ref=menu.menu_id)
                )
            )"""
        )
    if criteria.dietary_filters.vegan:
        conditions.extend(
            [
                "menu.dietary_data_status IN ('REVIEWED','VERIFIED')",
                """EXISTS (
                  SELECT 1 FROM menu_dietary_attribute menu_dietary
                  JOIN dietary_attribute dietary
                    ON dietary.attribute_id=menu_dietary.attribute_id
                  WHERE menu_dietary.menu_id=menu.menu_id
                    AND LOWER(dietary.code) IN ('vegan_option','vegan_possible')
                    AND UPPER(menu_dietary.status)='VERIFIED'
                )""",
            ]
        )

    group_by = """
      menu.menu_id,menu.merchant_id,merchant.name_en,merchant.name_ko,
      menu.name_en,menu.name_ko,menu.category,menu.description,
      menu.cultural_description,menu.price,merchant.delivery_fee,
      merchant.eta_min,merchant.eta_max,menu.spice_level,
      menu.serves_min,menu.serves_max,menu.is_synthetic,mapping.concept_id
    """
    if selected:
        group_by += ",support_evidence.reviewed_evidence_count"
    group_by_clause = f"GROUP BY {group_by}" if selected else ""
    limit_clause = ""
    diversity_cte = ""
    final_relation = "qualified"
    diversity_where = ""
    if candidate_limit is not None:
        parameters["candidate_limit"] = candidate_limit
        parameters["per_merchant_limit"] = max(1, math.ceil(candidate_limit * 0.25))
        diversity_cte = """,
      merchant_limited AS (
        SELECT qualified.*,
               ROW_NUMBER() OVER (
                 PARTITION BY merchant_id
                 ORDER BY explicit_score DESC,min_category_support DESC,
                          reviewed_evidence_count DESC,menu_id
               ) AS merchant_candidate_rank
        FROM qualified
      )"""
        final_relation = "merchant_limited"
        diversity_where = "WHERE merchant_candidate_rank<=:per_merchant_limit"
        limit_clause = (
            "LIMIT :candidate_limit"
            if dialect == "sqlite"
            else "FETCH FIRST :candidate_limit ROWS ONLY"
        )
    sql = f"""
      WITH {selected_cte}{support_ctes},
      qualified AS (
        SELECT
          menu.menu_id,menu.merchant_id,
          COALESCE(merchant.name_en,merchant.name_ko) AS merchant_name,
          menu.name_en,menu.name_ko,menu.category,menu.description,
          menu.cultural_description,menu.price,
          COALESCE(merchant.delivery_fee,0) AS delivery_fee,
          COALESCE(merchant.eta_min,0) AS eta_min,
          COALESCE(merchant.eta_max,0) AS eta_max,
          menu.spice_level,menu.serves_min,menu.serves_max,menu.is_synthetic,
          mapping.concept_id,
          {support_projection}
        FROM menu
        JOIN merchant ON merchant.merchant_id=menu.merchant_id
        JOIN menu_concept_map mapping ON mapping.menu_id=menu.menu_id
        LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
        {support_join}
        WHERE {' AND '.join(conditions)}
        {group_by_clause}
        {support_having}
      ){diversity_cte}
      SELECT * FROM {final_relation}
      {diversity_where}
      ORDER BY explicit_score DESC,min_category_support DESC,
               reviewed_evidence_count DESC,merchant_id,menu_id
      {limit_clause}
    """
    return ConceptCandidateQuery(sql=sql, parameters=parameters)


def build_concept_preview_query(candidate_query: ConceptCandidateQuery) -> ConceptCandidateQuery:
    sql = candidate_query.sql
    marker = "SELECT * FROM qualified"
    if marker not in sql:
        marker = "SELECT * FROM merchant_limited"
    before, _separator, _after = sql.partition(marker)
    return ConceptCandidateQuery(
        sql=before + "SELECT COUNT(*) eligible_menu_count,"
        "COUNT(DISTINCT merchant_id) eligible_merchant_count FROM qualified",
        parameters={
            key: value
            for key, value in candidate_query.parameters.items()
            if key not in {"candidate_limit", "per_merchant_limit"}
        },
    )
