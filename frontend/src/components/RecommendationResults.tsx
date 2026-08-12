import { CheckCircle2, ChevronDown, GitCompareArrows, Leaf, RotateCcw, Search, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import type { PreferenceCatalog, RecommendationBatchV2, StructuredRecommendation } from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";
import { menuName } from "../lib/locale";

interface Props {
  batch: RecommendationBatchV2;
  catalog: PreferenceCatalog;
  copy: RecommendationCopy;
  language: string;
  locale: string;
  busy?: boolean;
  onChoose: (recommendation: StructuredRecommendation) => void;
  onSimilar: () => void;
  onEdit: () => void;
  onRetry: () => void;
}

export function RecommendationResults({
  batch,
  catalog,
  copy,
  language,
  locale,
  busy = false,
  onChoose,
  onSimilar,
  onEdit,
  onRetry,
}: Props) {
  const [evidenceOpen, setEvidenceOpen] = useState<Set<string>>(() => new Set());
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const valueLabels = useMemo(() => new Map(
    catalog.categories.flatMap((category) => category.options.map((option) => [option.code, option.label] as const)),
  ), [catalog.categories]);
  const isFallback = batch.status === "SEARCH_FALLBACK";

  function toggleEvidence(menuId: string) {
    setEvidenceOpen((current) => {
      const next = new Set(current);
      if (next.has(menuId)) next.delete(menuId); else next.add(menuId);
      return next;
    });
  }

  return (
    <section className="recommendation-results" aria-labelledby="recommendation-results-title">
      <header className={isFallback ? "recommendation-result-heading fallback" : "recommendation-result-heading"}>
        {isFallback ? <Search size={22} /> : <Sparkles size={22} />}
        <div>
          <p className="eyebrow">{isFallback ? copy.searchFallbackTitle : copy.selectorEyebrow}</p>
          <h1 id="recommendation-results-title">{isFallback ? copy.searchFallbackTitle : copy.resultsTitle}</h1>
          <p>{isFallback ? copy.searchFallbackDescription : batch.criteria_summary}</p>
        </div>
      </header>

      {comparisonOpen && batch.recommendations.length > 1 && (
        <section className="recommendation-comparison" aria-label={copy.compare}>
          <header><GitCompareArrows size={18} /><h2>{copy.compare}</h2></header>
          <div>
            {batch.recommendations.map((item) => (
              <article key={item.menu.menu_id}>
                <span>{item.rank}</span>
                <h3>{menuName(item.menu, language)}</h3>
                <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                <p>{item.selection_reason}</p>
                <small>{item.menu.spice_level} / 5</small>
              </article>
            ))}
          </div>
        </section>
      )}

      <div className="structured-menu-list">
        {batch.recommendations.map((item) => {
          const evidenceVisible = evidenceOpen.has(item.menu.menu_id);
          return (
            <article className="structured-menu-card" key={item.menu.menu_id} data-testid={`menu-${item.menu.menu_id}`}>
              <div className="structured-menu-rank"><span>{item.rank}</span></div>
              <div className="structured-menu-content">
                <div className="structured-menu-title-row">
                  <div><h2>{item.title || menuName(item.menu, language)}</h2><p>{menuName(item.menu, language)} · {item.menu.merchant_name}</p></div>
                  <strong>₩{item.menu.price.toLocaleString(locale)}</strong>
                </div>
                <p className="structured-menu-description">{item.description || item.menu.description}</p>
                <section className="match-reason"><h3>{copy.matchedPreferences}</h3><p>{isFallback ? copy.searchFallbackDescription : item.selection_reason}</p></section>
                <div className="structured-menu-facts">
                  <span>{item.menu.eta_min}–{item.menu.eta_max} min</span>
                  <span>{item.menu.spice_level} / 5</span>
                  {item.halal_certified && <span className="halal-status"><CheckCircle2 size={14} /> {copy.halalCertified}</span>}
                  {item.vegan_status === "LIKELY_FIT" && <span className="vegan-status"><Leaf size={14} /> {copy.veganLikely}</span>}
                  {item.vegan_status === "POSSIBLE_WITH_CHECKS" && <span className="vegan-check-status"><Leaf size={14} /> {copy.veganChecks}</span>}
                </div>
                {item.halal_certified && item.halal_scope_label && <p className="certification-scope"><strong>{copy.halalScope}:</strong> {item.halal_scope_label}</p>}
                {item.vegan_warning && <p className="vegan-warning">{item.vegan_warning}</p>}

                <button className="evidence-toggle" type="button" aria-expanded={evidenceVisible} onClick={() => toggleEvidence(item.menu.menu_id)}>
                  {evidenceVisible ? copy.hideEvidence : copy.evidence}<ChevronDown size={16} />
                </button>
                {evidenceVisible && (
                  <div className="structured-evidence">
                    {item.matched_criteria.length > 0 && <ul>{item.matched_criteria.map((match) => {
                      const labels = match.labels?.length
                        ? match.labels
                        : match.selected_value_codes.map((code) => valueLabels.get(code)).filter((label): label is string => Boolean(label));
                      return labels.length ? <li key={match.category_code}>{labels.join(" · ")}</li> : null;
                    })}</ul>}
                    {item.wiki_passages.map((passage, index) => <blockquote key={passage.chunk_id ?? passage.evidence_id ?? index}>{passage.content}</blockquote>)}
                  </div>
                )}

                <button className="primary-button full" type="button" disabled={busy || !batch.snapshot_id} onClick={() => onChoose(item)}>{copy.chooseMenu}</button>
              </div>
            </article>
          );
        })}
      </div>

      <footer className="result-action-bar">
        {batch.recommendations.length > 1 && <button type="button" className="secondary-button" aria-pressed={comparisonOpen} onClick={() => setComparisonOpen((value) => !value)} disabled={busy}><GitCompareArrows size={17} /> {copy.compare}</button>}
        <button type="button" className="secondary-button" onClick={onSimilar} disabled={busy}><RotateCcw size={17} /> {copy.similar}</button>
        <button type="button" className="text-button" onClick={onEdit} disabled={busy}>{copy.editCriteria}</button>
        {isFallback && <button type="button" className="text-button" onClick={onRetry} disabled={busy}>{copy.tryAgain}</button>}
      </footer>
    </section>
  );
}
