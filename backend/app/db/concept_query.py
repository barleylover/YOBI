from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.structured_recommendation import RecommendationCriteriaV2

SqlDialect = Literal["sqlite", "oracle"]
SelectedSupportChannel = Literal["COMBINED", "MENU_FEATURE", "CONCEPT_SUPPORT"]

_COMPONENT_PHYSICAL_CATEGORIES = (
    "food_forms",
    "temperatures",
    "textures",
    "cooking_methods",
)


@dataclass(frozen=True)
class ConceptCandidateQuery:
    sql: str
    parameters: dict[str, Any]


def _component_coherence_sql(
    criteria: RecommendationCriteriaV2,
    parameters: dict[str, Any],
) -> tuple[str, str, str]:
    """Return CTEs, joins, and predicates that prevent component feature mixing.

    A compound set must not satisfy form/temperature/cooking constraints by
    taking each condition from a different component. A set whose reviewed
    component concepts span both hot and cold is also not treated as a pure
    temperature match. The rule is based entirely on release-scoped component
    memberships and therefore applies to every menu, not named examples.
    """

    selected_groups = criteria.subjective_groups()
    physical_count = sum(
        1 for category in _COMPONENT_PHYSICAL_CATEGORIES if selected_groups.get(category)
    )
    parameters["selected_physical_category_count"] = physical_count
    parameters["temperature_selected"] = int(bool(selected_groups.get("temperatures")))
    ctes = """,
      component_profile AS (
        SELECT membership.menu_id,COUNT(DISTINCT membership.concept_id) AS component_count
        FROM menu_concept_membership membership
        WHERE membership.knowledge_release_id=:knowledge_release_id
          AND membership.membership_role='COMPONENT'
        GROUP BY membership.menu_id
      ),
      coherent_physical_component AS (
        SELECT membership.menu_id,membership.concept_id
        FROM menu_concept_membership membership
        JOIN concept_preference_support component_support
          ON component_support.knowledge_release_id=membership.knowledge_release_id
         AND component_support.concept_id=membership.concept_id
         AND component_support.support_status='SUPPORTED'
         AND component_support.evidence_chunk_id IS NOT NULL
        JOIN selected
          ON selected.category_code=component_support.category_code
         AND selected.option_code=component_support.option_code
        WHERE membership.knowledge_release_id=:knowledge_release_id
          AND membership.membership_role='COMPONENT'
          AND component_support.category_code IN (
            'food_forms','temperatures','textures','cooking_methods'
          )
        GROUP BY membership.menu_id,membership.concept_id
        HAVING COUNT(DISTINCT component_support.category_code)
          =:selected_physical_category_count
      ),
      coherent_physical_menu AS (
        SELECT DISTINCT menu_id FROM coherent_physical_component
      ),
      component_temperature_profile AS (
        SELECT membership.menu_id,
               COUNT(DISTINCT component_support.option_code) AS temperature_count
        FROM menu_concept_membership membership
        JOIN concept_preference_support component_support
          ON component_support.knowledge_release_id=membership.knowledge_release_id
         AND component_support.concept_id=membership.concept_id
         AND component_support.support_status='SUPPORTED'
         AND component_support.evidence_chunk_id IS NOT NULL
         AND component_support.category_code='temperatures'
        WHERE membership.knowledge_release_id=:knowledge_release_id
          AND membership.membership_role='COMPONENT'
        GROUP BY membership.menu_id
      )"""
    joins = """
          LEFT JOIN component_profile component_profile_row
            ON component_profile_row.menu_id=menu.menu_id
          LEFT JOIN coherent_physical_menu coherent_component_row
            ON coherent_component_row.menu_id=menu.menu_id
          LEFT JOIN component_temperature_profile component_temperature_row
            ON component_temperature_row.menu_id=menu.menu_id
    """
    predicates = """
      AND (
        COALESCE(component_profile_row.component_count,0)<2
        OR :selected_physical_category_count<2
        OR coherent_component_row.menu_id IS NOT NULL
      )
      AND (
        :temperature_selected=0
        OR COALESCE(component_profile_row.component_count,0)<2
        OR COALESCE(component_temperature_row.temperature_count,0)<=1
      )
    """
    return ctes, joins, predicates


def _reviewed_public_wiki_condition(dialect: SqlDialect) -> str:
    """Require a menu to have at least one reviewed, public Wiki passage.

    This condition belongs in every recall channel so Wiki-less menus cannot
    consume the bounded top-100 union before the service freezes its shortlist.
    The immutable release compiler materializes the expensive
    passage -> concept closure -> menu join once. Runtime queries therefore do
    one indexed lookup instead of repeatedly parsing chunk metadata JSON.
    """

    del dialect  # The materialized eligibility contract is identical in both databases.
    return """EXISTS (
      SELECT 1 FROM menu_wiki_eligibility wiki_eligible
      WHERE wiki_eligible.knowledge_release_id=:knowledge_release_id
        AND wiki_eligible.menu_id=menu.menu_id
        AND wiki_eligible.reviewed_chunk_count>0
    )"""


def _hard_eligibility_conditions(
    *,
    criteria: RecommendationCriteriaV2,
    certification_release_id: str,
    service_area_id: str | None,
    excluded_menu_ids: set[str],
    included_menu_ids: Sequence[str] | None,
    eligibility_as_of: Any,
    synthetic_enrichment_release_id: str | None,
    parameters: dict[str, Any],
) -> list[str]:
    conditions = [
        "menu.availability='AVAILABLE'",
        "menu.price>0",
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
    if included_menu_ids is not None:
        unique_ids = list(dict.fromkeys(included_menu_ids))
        if not unique_ids:
            conditions.append("1=0")
        else:
            included_placeholders: list[str] = []
            for index, menu_id in enumerate(unique_ids):
                key = f"included_menu_{index}"
                included_placeholders.append(f":{key}")
                parameters[key] = menu_id
            conditions.append("menu.menu_id IN (" + ",".join(included_placeholders) + ")")

    if criteria.schema_version == "3":
        if not synthetic_enrichment_release_id or criteria.price_range_krw is None:
            conditions.append("1=0")
            return conditions
        parameters["synthetic_enrichment_release_id"] = synthetic_enrichment_release_id
        parameters["price_min_krw"] = criteria.price_range_krw.min
        parameters["price_max_krw"] = criteria.price_range_krw.max
        parameters["spice_reference_country"] = criteria.spice_reference_country
        conditions.extend(
            [
                "menu.price BETWEEN :price_min_krw AND :price_max_krw",
                """EXISTS (
                  SELECT 1 FROM synthetic_menu_profile synthetic_menu
                  JOIN synthetic_country_profile synthetic_country
                    ON synthetic_country.release_id=synthetic_menu.release_id
                   AND synthetic_country.country_code=:spice_reference_country
                  WHERE synthetic_menu.release_id=:synthetic_enrichment_release_id
                    AND synthetic_menu.menu_id=menu.menu_id
                    AND (
                      (:spice_preference='LESS'
                        AND synthetic_menu.spice_level<synthetic_country.spice_baseline)
                      OR (:spice_preference='SIMILAR'
                        AND synthetic_menu.spice_level=synthetic_country.spice_baseline)
                      OR (:spice_preference='MORE'
                        AND synthetic_menu.spice_level>synthetic_country.spice_baseline)
                    )
                )""",
            ]
        )
        parameters["spice_preference"] = criteria.spice_preference
        if criteria.dietary_filters.halal_certified_only:
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM synthetic_menu_profile synthetic_halal
                  WHERE synthetic_halal.release_id=:synthetic_enrichment_release_id
                    AND synthetic_halal.menu_id=menu.menu_id
                    AND synthetic_halal.halal_fit=1
                )"""
            )
        if criteria.dietary_filters.vegan:
            conditions.append(
                """EXISTS (
                  SELECT 1 FROM synthetic_menu_profile synthetic_vegan
                  WHERE synthetic_vegan.release_id=:synthetic_enrichment_release_id
                    AND synthetic_vegan.menu_id=menu.menu_id
                    AND synthetic_vegan.vegan_fit=1
                )"""
            )
        return conditions

    price_conditions = [
        {
            "UNDER_10000": "menu.price<10000",
            "FROM_10000_TO_19999": "menu.price BETWEEN 10000 AND 19999",
            "FROM_20000_TO_29999": "menu.price BETWEEN 20000 AND 29999",
            "OVER_30000": "menu.price>=30000",
        }[band]
        for band in criteria.price_bands
    ]
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
    return conditions


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
    included_menu_ids: Sequence[str] | None = None,
    support_channel: SelectedSupportChannel = "COMBINED",
    synthetic_enrichment_release_id: str | None = None,
) -> ConceptCandidateQuery:
    """Build one grounded candidate channel or the final combined grounding query.

    ``MENU_FEATURE`` is allowed to use section/option ``REVIEW_REQUIRED`` rows
    only to recall a candidate. ``COMBINED`` deliberately removes those weak
    rows again, so the final population still requires menu-direct or reviewed
    concept evidence for every selected category.
    """

    selected = [
        (category, option)
        for category, options in criteria.subjective_groups().items()
        for option in options
    ]
    parameters: dict[str, Any] = {"knowledge_release_id": knowledge_release_id}
    if selected:
        parameters.update(
            {
                "include_menu_feature": int(support_channel in {"COMBINED", "MENU_FEATURE"}),
                "include_concept_support": int(support_channel in {"COMBINED", "CONCEPT_SUPPORT"}),
                "allow_auxiliary_feature": int(support_channel == "MENU_FEATURE"),
            }
        )
        parameters["selected_category_count"] = len(criteria.subjective_groups())
        if dialect == "sqlite":
            values: list[str] = []
            for index, (category, option) in enumerate(selected):
                values.append(f"(:selected_category_{index},:selected_option_{index})")
                parameters[f"selected_category_{index}"] = category
                parameters[f"selected_option_{index}"] = option
            selected_cte = (
                "selected(category_code,option_code) AS (VALUES " + ",".join(values) + ")"
            )
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
        # Collapse same-category options before scoring. Direct menu support and
        # reviewed concept support are unioned, while a direct contradiction
        # blocks inheritance for that exact selected value.
        support_ctes = """,
      menu_feature_support AS (
        SELECT feature.menu_id,NULL AS concept_id,feature.category_code,
               feature.option_code,feature.support_strength,
               feature.feature_id AS evidence_id,
               CASE WHEN feature.support_status='SUPPORTED'
                          AND feature.evidence_scope='MENU_DIRECT'
                    THEN 1 ELSE 0 END AS direct_supported,
               CASE WHEN feature.support_status='SUPPORTED'
                          AND feature.evidence_scope='MENU_DIRECT'
                    THEN 1 ELSE 0 END AS final_grounding_allowed
        FROM menu_preference_feature feature
        JOIN selected
          ON selected.category_code=feature.category_code
         AND selected.option_code=feature.option_code
        WHERE feature.knowledge_release_id=:knowledge_release_id
          AND feature.support_status IN ('SUPPORTED','REVIEW_REQUIRED')
          AND feature.evidence_scope IN (
            'MENU_DIRECT','SECTION_CONTEXT','OPTION_AVAILABILITY'
          )
      ),
      concept_support AS (
        SELECT membership.menu_id,membership.concept_id,support.category_code,
               support.option_code,support.support_strength,
               support.evidence_chunk_id AS evidence_id,0 AS direct_supported,
               1 AS final_grounding_allowed
        FROM menu_concept_membership membership
        JOIN concept_preference_support support
          ON support.knowledge_release_id=membership.knowledge_release_id
         AND support.concept_id=membership.concept_id
         AND support.support_status='SUPPORTED'
         AND support.evidence_chunk_id IS NOT NULL
        JOIN selected
          ON selected.category_code=support.category_code
         AND selected.option_code=support.option_code
        WHERE membership.knowledge_release_id=:knowledge_release_id
          AND NOT EXISTS (
            SELECT 1 FROM menu_preference_feature contradiction
            WHERE contradiction.knowledge_release_id=membership.knowledge_release_id
              AND contradiction.menu_id=membership.menu_id
              AND contradiction.category_code=support.category_code
              AND contradiction.option_code=support.option_code
              AND contradiction.support_status='CONTRADICTED'
              AND contradiction.evidence_scope='MENU_DIRECT'
          )
      ),
      selected_support AS (
        SELECT * FROM menu_feature_support
        WHERE :include_menu_feature=1
          AND (
            :allow_auxiliary_feature=1
            OR final_grounding_allowed=1
          )
        UNION ALL
        SELECT * FROM concept_support WHERE :include_concept_support=1
      ),
      category_support AS (
        SELECT menu_id,category_code,
               MAX(support_strength) AS category_support,
               MAX(direct_supported) AS direct_supported,
               COUNT(DISTINCT evidence_id) AS reviewed_evidence_count
        FROM selected_support
        GROUP BY menu_id,category_code
      ),
      candidate_concept AS (
        SELECT menu_id,concept_id
        FROM (
          SELECT membership.menu_id,membership.concept_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY membership.menu_id
                   ORDER BY CASE membership.membership_role
                     WHEN 'PRIMARY' THEN 1 WHEN 'COMPONENT' THEN 2 ELSE 3 END,
                     membership.concept_id
                 ) AS membership_rank
          FROM menu_concept_membership membership
          WHERE membership.knowledge_release_id=:knowledge_release_id
        )
        WHERE membership_rank=1
      )"""
        support_join = """
          JOIN category_support support
            ON support.menu_id=menu.menu_id
          LEFT JOIN candidate_concept
            ON candidate_concept.menu_id=menu.menu_id
        """
        support_projection = """
          COALESCE(candidate_concept.concept_id,menu.menu_id) AS concept_id,
          AVG(support.category_support) AS explicit_score,
          MIN(support.category_support) AS min_category_support,
          SUM(support.reviewed_evidence_count) AS reviewed_evidence_count,
          AVG(support.direct_supported) AS direct_evidence_ratio
        """
        support_having = "HAVING COUNT(DISTINCT support.category_code)=:selected_category_count"
        coherence_ctes, coherence_joins, coherence_predicates = _component_coherence_sql(
            criteria, parameters
        )
        support_ctes += coherence_ctes
        support_join += coherence_joins
    else:
        selected_cte = "selected AS (SELECT NULL category_code,NULL option_code WHERE 1=0)"
        if dialect == "oracle":
            selected_cte = (
                "selected AS (SELECT NULL category_code,NULL option_code FROM dual WHERE 1=0)"
            )
        # Exact/objective-only requests use the release-compiled eligibility
        # relation. No passage metadata JSON is parsed on the request path.
        support_ctes = """,
      candidate_membership AS (
        SELECT menu_id,concept_id
        FROM (
          SELECT membership.menu_id,membership.concept_id,
                 ROW_NUMBER() OVER (
                   PARTITION BY membership.menu_id
                   ORDER BY CASE membership.membership_role
                     WHEN 'PRIMARY' THEN 1 WHEN 'COMPONENT' THEN 2 ELSE 3 END,
                     membership.concept_id
                 ) AS membership_rank
          FROM menu_concept_membership membership
          WHERE membership.knowledge_release_id=:knowledge_release_id
        )
        WHERE membership_rank=1
      ),
      objective_grounding AS (
        SELECT menu_id,reviewed_chunk_count AS reviewed_evidence_count
        FROM menu_wiki_eligibility
        WHERE knowledge_release_id=:knowledge_release_id
          AND reviewed_chunk_count>0
      )"""
        support_join = """
          JOIN candidate_membership membership
            ON membership.menu_id=menu.menu_id
          JOIN objective_grounding objective_support
            ON objective_support.menu_id=menu.menu_id
        """
        support_projection = """
          membership.concept_id AS concept_id,
          1.0 AS explicit_score,
          1.0 AS min_category_support,
          objective_support.reviewed_evidence_count AS reviewed_evidence_count,
          0.0 AS direct_evidence_ratio
        """
        support_having = ""
        coherence_predicates = ""

    conditions = _hard_eligibility_conditions(
        criteria=criteria,
        certification_release_id=certification_release_id,
        service_area_id=service_area_id,
        excluded_menu_ids=excluded_menu_ids,
        included_menu_ids=included_menu_ids,
        eligibility_as_of=eligibility_as_of,
        synthetic_enrichment_release_id=synthetic_enrichment_release_id,
        parameters=parameters,
    )
    conditions.append(_reviewed_public_wiki_condition(dialect))

    group_by = """
      menu.menu_id,menu.merchant_id,merchant.name_en,merchant.name_ko,
      menu.name_en,menu.name_ko,menu.category,menu.description,
      menu.cultural_description,menu.price,merchant.delivery_fee,
      merchant.eta_min,merchant.eta_max,menu.spice_level,
      menu.serves_min,menu.serves_max,menu.is_synthetic
    """
    if selected:
        group_by += ",candidate_concept.concept_id"
    else:
        group_by += ",membership.concept_id,objective_support.reviewed_evidence_count"
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
          {support_projection}
        FROM menu
        JOIN merchant ON merchant.merchant_id=menu.merchant_id
        LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
        {support_join}
        WHERE {" AND ".join(conditions)}
        {coherence_predicates}
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


def build_concept_preview_count_query(
    *,
    dialect: SqlDialect,
    criteria: RecommendationCriteriaV2,
    knowledge_release_id: str,
    certification_release_id: str,
    service_area_id: str | None,
    excluded_menu_ids: set[str],
    eligibility_as_of: Any,
    synthetic_enrichment_release_id: str | None = None,
) -> ConceptCandidateQuery:
    """Count grounded hard-eligible menus without materializing ranking columns."""

    selected = [
        (category, option)
        for category, options in criteria.subjective_groups().items()
        for option in options
    ]
    parameters: dict[str, Any] = {"knowledge_release_id": knowledge_release_id}
    if selected:
        parameters["selected_category_count"] = len(criteria.subjective_groups())
        values: list[str] = []
        for index, (category, option) in enumerate(selected):
            parameters[f"selected_category_{index}"] = category
            parameters[f"selected_option_{index}"] = option
            if dialect == "sqlite":
                values.append(f"(:selected_category_{index},:selected_option_{index})")
            else:
                values.append(
                    f"SELECT :selected_category_{index} category_code,"
                    f":selected_option_{index} option_code FROM dual"
                )
        selected_cte = (
            "selected(category_code,option_code) AS (VALUES " + ",".join(values) + ")"
            if dialect == "sqlite"
            else "selected AS (" + " UNION ALL ".join(values) + ")"
        )
        coherence_ctes, coherence_joins, coherence_predicates = _component_coherence_sql(
            criteria, parameters
        )
        grounding_ctes = f"""
          {selected_cte},
          grounded_support AS (
            SELECT feature.menu_id,feature.category_code
            FROM menu_preference_feature feature
            JOIN selected
              ON selected.category_code=feature.category_code
             AND selected.option_code=feature.option_code
            WHERE feature.knowledge_release_id=:knowledge_release_id
              AND feature.support_status='SUPPORTED'
              AND feature.evidence_scope='MENU_DIRECT'
            UNION ALL
            SELECT membership.menu_id,support.category_code
            FROM concept_preference_support support
            JOIN selected
              ON selected.category_code=support.category_code
             AND selected.option_code=support.option_code
            JOIN menu_concept_membership membership
              ON membership.knowledge_release_id=support.knowledge_release_id
             AND membership.concept_id=support.concept_id
            WHERE support.knowledge_release_id=:knowledge_release_id
              AND support.support_status='SUPPORTED'
              AND support.evidence_chunk_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM menu_preference_feature contradiction
                WHERE contradiction.knowledge_release_id=membership.knowledge_release_id
                  AND contradiction.menu_id=membership.menu_id
                  AND contradiction.category_code=support.category_code
                  AND contradiction.option_code=support.option_code
                  AND contradiction.support_status='CONTRADICTED'
                  AND contradiction.evidence_scope='MENU_DIRECT'
              )
          ),
          grounded_menu AS (
            SELECT menu_id FROM grounded_support
            GROUP BY menu_id
            HAVING COUNT(DISTINCT category_code)=:selected_category_count
          )
          {coherence_ctes}
        """
    else:
        grounding_ctes = """
          grounded_menu AS (
            SELECT menu_id
            FROM menu_wiki_eligibility
            WHERE knowledge_release_id=:knowledge_release_id
              AND reviewed_chunk_count>0
          )
        """
        coherence_joins = ""
        coherence_predicates = ""
    conditions = _hard_eligibility_conditions(
        criteria=criteria,
        certification_release_id=certification_release_id,
        service_area_id=service_area_id,
        excluded_menu_ids=excluded_menu_ids,
        included_menu_ids=None,
        eligibility_as_of=eligibility_as_of,
        synthetic_enrichment_release_id=synthetic_enrichment_release_id,
        parameters=parameters,
    )
    conditions.append(_reviewed_public_wiki_condition(dialect))
    sql = f"""
      WITH {grounding_ctes}
      SELECT COUNT(*) AS eligible_menu_count,
             COUNT(DISTINCT menu.merchant_id) AS eligible_merchant_count
      FROM grounded_menu grounding
      JOIN menu ON menu.menu_id=grounding.menu_id
      JOIN merchant ON merchant.merchant_id=menu.merchant_id
      LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
      {coherence_joins}
      WHERE {" AND ".join(conditions)}
      {coherence_predicates}
    """
    return ConceptCandidateQuery(sql=sql, parameters=parameters)


def build_candidate_recall_channel_query(
    *,
    dialect: SqlDialect,
    criteria: RecommendationCriteriaV2,
    knowledge_release_id: str,
    certification_release_id: str,
    service_area_id: str | None,
    excluded_menu_ids: set[str],
    eligibility_as_of: Any,
    candidate_limit: int,
    support_channel: Literal["MENU_FEATURE", "CONCEPT_SUPPORT"],
    synthetic_enrichment_release_id: str | None = None,
) -> ConceptCandidateQuery:
    """Return one cheap recall channel before combined cross-category grounding."""

    if candidate_limit < 1:
        raise ValueError("GROUNDED_CHANNEL_LIMIT_INVALID")
    selected = [
        (category, option)
        for category, options in criteria.subjective_groups().items()
        for option in options
    ]
    if selected and support_channel not in {"MENU_FEATURE", "CONCEPT_SUPPORT"}:
        raise ValueError("GROUNDED_CHANNEL_INVALID")
    parameters: dict[str, Any] = {
        "knowledge_release_id": knowledge_release_id,
        "candidate_limit": candidate_limit,
        "per_merchant_limit": max(1, math.ceil(candidate_limit * 0.25)),
    }
    if selected:
        values: list[str] = []
        for index, (category, option) in enumerate(selected):
            parameters[f"selected_category_{index}"] = category
            parameters[f"selected_option_{index}"] = option
            if dialect == "sqlite":
                values.append(f"(:selected_category_{index},:selected_option_{index})")
            else:
                values.append(
                    f"SELECT :selected_category_{index} category_code,"
                    f":selected_option_{index} option_code FROM dual"
                )
        selected_cte = (
            "selected(category_code,option_code) AS (VALUES " + ",".join(values) + ")"
            if dialect == "sqlite"
            else "selected AS (" + " UNION ALL ".join(values) + ")"
        )
        if support_channel == "MENU_FEATURE":
            support_source = """
              SELECT feature.menu_id,feature.category_code,
                     feature.support_strength,feature.feature_id AS evidence_id,
                     CASE WHEN feature.support_status='SUPPORTED'
                                AND feature.evidence_scope='MENU_DIRECT'
                          THEN 1 ELSE 0 END AS direct_supported
              FROM menu_preference_feature feature
              JOIN selected
                ON selected.category_code=feature.category_code
               AND selected.option_code=feature.option_code
              WHERE feature.knowledge_release_id=:knowledge_release_id
                AND feature.support_status IN ('SUPPORTED','REVIEW_REQUIRED')
                AND feature.evidence_scope IN (
                  'MENU_DIRECT','SECTION_CONTEXT','OPTION_AVAILABILITY'
                )
            """
        else:
            support_source = """
              SELECT membership.menu_id,support.category_code,
                     support.support_strength,
                     support.evidence_chunk_id AS evidence_id,
                     0 AS direct_supported
              FROM concept_preference_support support
              JOIN selected
                ON selected.category_code=support.category_code
               AND selected.option_code=support.option_code
              JOIN menu_concept_membership membership
                ON membership.knowledge_release_id=support.knowledge_release_id
               AND membership.concept_id=support.concept_id
              WHERE support.knowledge_release_id=:knowledge_release_id
                AND support.support_status='SUPPORTED'
                AND support.evidence_chunk_id IS NOT NULL
                AND NOT EXISTS (
                  SELECT 1 FROM menu_preference_feature contradiction
                  WHERE contradiction.knowledge_release_id=membership.knowledge_release_id
                    AND contradiction.menu_id=membership.menu_id
                    AND contradiction.category_code=support.category_code
                    AND contradiction.option_code=support.option_code
                    AND contradiction.support_status='CONTRADICTED'
                    AND contradiction.evidence_scope='MENU_DIRECT'
                )
            """
        support_ctes = f"""
          {selected_cte},
          channel_support AS ({support_source}),
          category_support AS (
            SELECT menu_id,category_code,
                   MAX(support_strength) AS category_support,
                   MAX(direct_supported) AS direct_supported,
                   COUNT(DISTINCT evidence_id) AS reviewed_evidence_count
            FROM channel_support
            GROUP BY menu_id,category_code
          ),
          grounded AS (
            SELECT menu_id,AVG(category_support) AS explicit_score,
                   MIN(category_support) AS min_category_support,
                   SUM(reviewed_evidence_count) AS reviewed_evidence_count,
                   AVG(direct_supported) AS direct_evidence_ratio,
                   COUNT(*) AS matched_category_count
            FROM category_support
            GROUP BY menu_id
          )
        """
    else:
        if support_channel != "CONCEPT_SUPPORT":
            raise ValueError("OBJECTIVE_MENU_FEATURE_CHANNEL_UNAVAILABLE")
        support_ctes = """
          grounded AS (
            SELECT eligibility.menu_id,1.0 AS explicit_score,
                   1.0 AS min_category_support,
                   eligibility.reviewed_chunk_count AS reviewed_evidence_count,
                   0.0 AS direct_evidence_ratio,
                   1 AS matched_category_count
            FROM menu_wiki_eligibility eligibility
            WHERE eligibility.knowledge_release_id=:knowledge_release_id
              AND eligibility.reviewed_chunk_count>0
          )
        """
    conditions = _hard_eligibility_conditions(
        criteria=criteria,
        certification_release_id=certification_release_id,
        service_area_id=service_area_id,
        excluded_menu_ids=excluded_menu_ids,
        included_menu_ids=None,
        eligibility_as_of=eligibility_as_of,
        synthetic_enrichment_release_id=synthetic_enrichment_release_id,
        parameters=parameters,
    )
    conditions.append(_reviewed_public_wiki_condition(dialect))
    limit_clause = (
        "LIMIT :candidate_limit"
        if dialect == "sqlite"
        else "FETCH FIRST :candidate_limit ROWS ONLY"
    )
    sql = f"""
      WITH {support_ctes},
      qualified AS (
        SELECT grounded.*,menu.merchant_id
        FROM grounded
        JOIN menu ON menu.menu_id=grounded.menu_id
        JOIN merchant ON merchant.merchant_id=menu.merchant_id
        LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
        WHERE {" AND ".join(conditions)}
      ),
      merchant_limited AS (
        SELECT qualified.*,
               ROW_NUMBER() OVER (
                 PARTITION BY merchant_id
                 ORDER BY matched_category_count DESC,explicit_score DESC,
                          min_category_support DESC,
                          direct_evidence_ratio DESC,reviewed_evidence_count DESC,menu_id
               ) AS merchant_candidate_rank
        FROM qualified
      )
      SELECT menu_id,merchant_id FROM merchant_limited
      WHERE merchant_candidate_rank<=:per_merchant_limit
      ORDER BY matched_category_count DESC,explicit_score DESC,
               min_category_support DESC,
               direct_evidence_ratio DESC,reviewed_evidence_count DESC,
               merchant_id,menu_id
      {limit_clause}
    """
    return ConceptCandidateQuery(sql=sql, parameters=parameters)


def build_semantic_candidate_query(
    *,
    dialect: SqlDialect,
    criteria: RecommendationCriteriaV2,
    knowledge_release_id: str,
    certification_release_id: str,
    service_area_id: str | None,
    excluded_menu_ids: set[str],
    eligibility_as_of: Any,
    candidate_limit: int,
    query_vector: Any | None = None,
    semantic_embedding_model: str | None = None,
    semantic_embedding_version: str | None = None,
    semantic_embedding_dimension: int | None = None,
    catalog_release_id: str | None = None,
    synthetic_enrichment_release_id: str | None = None,
) -> ConceptCandidateQuery:
    """Build the independent hard-eligible semantic retrieval channel.

    Oracle ranks persisted Cohere menu vectors in SQL. SQLite returns the same
    hard-eligible population for the deterministic offline mirror scorer.
    Wiki eligibility is applied here before the bounded recall union. Callers
    still re-run the selected-category grounding query over the union, which
    removes semantic-only items lacking per-category direct or reviewed concept
    evidence.
    """

    if candidate_limit < 1:
        raise ValueError("SEMANTIC_CANDIDATE_LIMIT_INVALID")
    parameters: dict[str, Any] = {"knowledge_release_id": knowledge_release_id}
    conditions = _hard_eligibility_conditions(
        criteria=criteria,
        certification_release_id=certification_release_id,
        service_area_id=service_area_id,
        excluded_menu_ids=excluded_menu_ids,
        included_menu_ids=None,
        eligibility_as_of=eligibility_as_of,
        synthetic_enrichment_release_id=synthetic_enrichment_release_id,
        parameters=parameters,
    )
    conditions.append(_reviewed_public_wiki_condition(dialect))
    if dialect == "oracle":
        if query_vector is None:
            raise ValueError("SEMANTIC_QUERY_VECTOR_REQUIRED")
        if not semantic_embedding_model or not semantic_embedding_version:
            raise ValueError("SEMANTIC_EMBEDDING_IDENTITY_REQUIRED")
        if semantic_embedding_dimension is None:
            raise ValueError("SEMANTIC_EMBEDDING_DIMENSION_REQUIRED")
        if not catalog_release_id:
            raise ValueError("SEMANTIC_CATALOG_RELEASE_REQUIRED")
        parameters["query_vector"] = query_vector
        parameters["semantic_embedding_model"] = semantic_embedding_model
        parameters["semantic_embedding_version"] = semantic_embedding_version
        parameters["semantic_embedding_dimension"] = semantic_embedding_dimension
        parameters["semantic_catalog_release_id"] = catalog_release_id
        parameters["candidate_limit"] = candidate_limit
        conditions.extend(("semantic_embedding.embedding_vector IS NOT NULL",))
        semantic_projection = (
            "1-VECTOR_DISTANCE(semantic_embedding.embedding_vector,:query_vector,COSINE) "
            "AS semantic_score"
        )
        semantic_join = """
          JOIN menu_semantic_embedding semantic_embedding
            ON semantic_embedding.menu_id=menu.menu_id
           AND semantic_embedding.catalog_release_id=:semantic_catalog_release_id
           AND semantic_embedding.embedding_model=:semantic_embedding_model
           AND semantic_embedding.embedding_version=:semantic_embedding_version
           AND semantic_embedding.embedding_dimension=:semantic_embedding_dimension
        """
        order_and_limit = """
          ORDER BY semantic_score DESC,menu.merchant_id,menu.menu_id
          FETCH FIRST :candidate_limit ROWS ONLY
        """
    else:
        semantic_projection = "menu.semantic_text"
        semantic_join = ""
        # SQLite has no native VECTOR column. The repository applies the
        # deterministic offline scorer and then keeps exactly candidate_limit.
        order_and_limit = "ORDER BY menu.merchant_id,menu.menu_id"
    sql = f"""
      SELECT menu.menu_id,menu.merchant_id,{semantic_projection}
      FROM menu
      {semantic_join}
      JOIN merchant ON merchant.merchant_id=menu.merchant_id
      LEFT JOIN menu_source_detail source_detail ON source_detail.menu_id=menu.menu_id
      WHERE {" AND ".join(conditions)}
      {order_and_limit}
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
