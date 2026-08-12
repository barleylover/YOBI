import { useCallback, useEffect, useRef, useState } from "react";
import { Settings2, ShoppingBag } from "lucide-react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { OrderFlowPanel } from "../components/OrderFlowPanel";
import { PreferenceSelector } from "../components/PreferenceSelector";
import { RecommendationResults } from "../components/RecommendationResults";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import {
  getCatalogChangedCopy,
  getRecommendationConflictCopy,
  getRecommendationCopy,
} from "../lib/recommendationI18n";
import { usePreferenceCatalog } from "../lib/usePreferenceCatalog";
import { useSessionStore } from "../stores/session";
import type {
  ConversationEventInput,
  ConversationView,
  MenuSummary,
  RecommendationBatchV2,
  RecommendationMode,
  RecommendationRequestV2,
  StructuredRecommendation,
} from "../types";

function createId(prefix: string) {
  const value = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${value}`;
}

function findMenu(value: unknown, menuId: string): MenuSummary | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const match = findMenu(item, menuId);
      if (match) return match;
    }
    return null;
  }
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  if (item.menu_id === menuId && typeof item.merchant_id === "string" && typeof item.name_en === "string") {
    return item as unknown as MenuSummary;
  }
  for (const nested of Object.values(item)) {
    const match = findMenu(nested, menuId);
    if (match) return match;
  }
  return null;
}

function sameCriteria(left: unknown, right: unknown) {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function ChatPage() {
  const { sessionId = "" } = useParams();
  const navigate = useNavigate();
  const profile = useSessionStore((state) => state.profile);
  const session = useSessionStore((state) => state.session);
  const addressRefId = useSessionStore((state) => state.addressRefId);
  const cartQuantity = useSessionStore((state) => state.cartQuantity);
  const draftCriteria = useSessionStore((state) => state.draftCriteria);
  const committedCriteria = useSessionStore((state) => state.committedCriteria);
  const criteriaVersion = useSessionStore((state) => state.criteriaVersion);
  const recommendationPhase = useSessionStore((state) => state.recommendationPhase);
  const pendingRecommendation = useSessionStore((state) => state.pendingRecommendation);
  const latestRecommendation = useSessionStore((state) => state.latestRecommendation);
  const setDraftCriteria = useSessionStore((state) => state.setDraftCriteria);
  const commitCriteria = useSessionStore((state) => state.commitCriteria);
  const setRecommendationPhase = useSessionStore((state) => state.setRecommendationPhase);
  const setPendingRecommendation = useSessionStore((state) => state.setPendingRecommendation);
  const setLatestRecommendation = useSessionStore((state) => state.setLatestRecommendation);
  const { copy, journeyCopy, language, locale } = useI18n();
  const recommendationCopy = getRecommendationCopy(language);
  const recommendationConflictCopy = getRecommendationConflictCopy(language);
  const catalogChangedCopy = getCatalogChangedCopy(language);
  const { catalog, loading: catalogLoading, stale: catalogStale, error: catalogError, reload: reloadCatalog } = usePreferenceCatalog(locale);
  const [hydrating, setHydrating] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [selectedMenu, setSelectedMenu] = useState<MenuSummary | null>(null);
  const stateVersionRef = useRef(session?.state_version ?? 0);
  const pollCountRef = useRef(0);
  const criteriaRequestKey = `yobi-pending-criteria-request-${sessionId}`;

  const applyBatch = useCallback((batch: RecommendationBatchV2) => {
    stateVersionRef.current = batch.state_version;
    setLatestRecommendation(batch);
    if (batch.status !== "PENDING") {
      setPendingRecommendation(null);
      pollCountRef.current = 0;
    }
    if (batch.status === "PENDING") {
      const current = useSessionStore.getState().pendingRecommendation;
      if (current?.request_id !== batch.request_id) {
        setPendingRecommendation({
          request_id: batch.request_id,
          expected_state_version: batch.state_version,
          criteria_version: batch.criteria_version,
          mode: "INITIAL",
        });
      }
      setRecommendationPhase(batch.phase === "GENERATING" ? "GENERATING" : "RETRIEVING");
    } else if (batch.status === "RECOMMENDED") {
      setRecommendationPhase("RESULTS");
    } else if (batch.status === "SEARCH_FALLBACK") {
      setRecommendationPhase("SEARCH_FALLBACK");
    } else if (batch.status === "NO_MATCH") {
      setRecommendationPhase("NO_RESULTS");
    } else {
      setRecommendationPhase("ERROR");
    }
  }, [setLatestRecommendation, setPendingRecommendation, setRecommendationPhase]);

  const applyConversation = useCallback((conversation: ConversationView) => {
    stateVersionRef.current = conversation.state_version;
    if (conversation.recommendation_criteria && conversation.criteria_version) {
      commitCriteria(conversation.recommendation_criteria, conversation.criteria_version);
    }
    const batch = conversation.active_recommendation ?? conversation.latest_recommendation;
    if (batch) applyBatch(batch);
    const selectedMenuId = conversation.meal_need_state.selected_menu_id;
    if (!selectedMenuId) {
      setSelectedMenu(null);
      return;
    }
    const fromV2 = batch?.recommendations.find((item) => item.menu.menu_id === selectedMenuId)?.menu;
    const fromLegacy = batch ? null : findMenu(conversation.latest_snapshot?.cards, selectedMenuId);
    setSelectedMenu(fromV2 ?? fromLegacy ?? null);
    if (fromV2 || fromLegacy) setRecommendationPhase("ORDERING");
  }, [applyBatch, commitCriteria, setRecommendationPhase]);

  const refreshConversation = useCallback(async () => {
    const conversation = await api.getConversation(sessionId);
    applyConversation(conversation);
    return conversation;
  }, [applyConversation, sessionId]);

  const executeRecommendation = useCallback(async (request: RecommendationRequestV2) => {
    setBusy(true);
    setError("");
    setPendingRecommendation(request);
    try {
      const batch = await api.createRecommendation(sessionId, request);
      applyBatch(batch);
    } catch (cause) {
      try {
        const conversation = await api.getConversation(sessionId);
        const recovered = conversation.active_recommendation ?? conversation.latest_recommendation;
        if (recovered?.request_id === request.request_id) {
          applyConversation(conversation);
          return;
        }
      } catch { /* Keep the stable request id for explicit recovery. */ }
      setRecommendationPhase("ERROR");
      setError(language === "English"
        ? actionableError(cause, recommendationCopy.failedDescription)
        : recommendationCopy.failedDescription);
    } finally {
      setBusy(false);
    }
  }, [applyBatch, applyConversation, language, recommendationCopy.failedDescription, sessionId, setPendingRecommendation, setRecommendationPhase]);

  const recoverRecommendation = useCallback(async (request: RecommendationRequestV2) => {
    setBusy(true);
    setError("");
    try {
      const batch = await api.getRecommendationRequest(sessionId, request.request_id);
      applyBatch(batch);
    } catch (cause) {
      try {
        const conversation = await api.getConversation(sessionId);
        const recovered = conversation.active_recommendation ?? conversation.latest_recommendation;
        if (recovered?.request_id === request.request_id) {
          applyConversation(conversation);
          return;
        }
      } catch { /* Keep the request available for another GET recovery attempt. */ }
      setRecommendationPhase("ERROR");
      setError(language === "English"
        ? actionableError(cause, recommendationCopy.failedDescription)
        : recommendationCopy.failedDescription);
    } finally {
      setBusy(false);
    }
  }, [applyBatch, applyConversation, language, recommendationCopy.failedDescription, sessionId, setRecommendationPhase]);

  useEffect(() => {
    if (!sessionId || session?.session_id !== sessionId) return;
    let active = true;
    setHydrating(true);
    api.getConversation(sessionId)
      .then((conversation) => { if (active) applyConversation(conversation); })
      .catch(() => undefined)
      .finally(() => { if (active) setHydrating(false); });
    return () => { active = false; };
  }, [applyConversation, session?.session_id, sessionId]);

  useEffect(() => {
    if (hydrating || latestRecommendation?.status !== "PENDING" || !pendingRecommendation || busy) return;
    if (pollCountRef.current >= 8) {
      setRecommendationPhase("ERROR");
      setError(recommendationCopy.failedDescription);
      return;
    }
    const timer = window.setTimeout(() => {
      pollCountRef.current += 1;
      void recoverRecommendation(pendingRecommendation);
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [busy, hydrating, latestRecommendation, pendingRecommendation, recommendationCopy.failedDescription, recoverRecommendation, setRecommendationPhase]);

  useEffect(() => {
    if (!catalog) return;
    const optionCodes = new Map(catalog.categories.map((category) => [
      category.code,
      new Set(category.options.map((option) => option.code)),
    ]));
    const categoryKeys = [
      "cuisine_origins",
      "flavors",
      "main_ingredients",
      "food_forms",
      "temperatures",
      "price_bands",
      "textures",
      "cooking_methods",
    ] as const;
    const next = { ...draftCriteria };
    let changed = false;
    for (const category of categoryKeys) {
      const validCodes = optionCodes.get(category) ?? new Set<string>();
      const retained = draftCriteria[category].filter((code) => validCodes.has(code));
      if (retained.length !== draftCriteria[category].length) changed = true;
      next[category] = retained;
    }
    if (changed) {
      setDraftCriteria(next);
      setError(catalogChangedCopy);
    }
  }, [catalog, catalogChangedCopy, draftCriteria, setDraftCriteria]);

  if (!profile || !session || session.session_id !== sessionId || !addressRefId) return <Navigate to="/" replace />;

  async function recordConversationEvent(event: Omit<ConversationEventInput, "idempotency_key" | "expected_state_version">) {
    const result = await api.postConversationEvent(sessionId, {
      ...event,
      expected_state_version: stateVersionRef.current,
      idempotency_key: createId(event.event_type.toLowerCase()),
    });
    stateVersionRef.current = result.state_version;
    return result;
  }

  async function submitCriteria() {
    if (!catalog || busy) return;
    setBusy(true);
    setError("");
    setRecommendationPhase("RETRIEVING");
    const savedRequestId = sessionStorage.getItem(criteriaRequestKey);
    const criteriaRequestId = savedRequestId ?? createId("criteria");
    sessionStorage.setItem(criteriaRequestKey, criteriaRequestId);
    try {
      let committed;
      try {
        committed = await api.putRecommendationCriteria(
          sessionId,
          draftCriteria,
          stateVersionRef.current,
          catalog.catalog_version,
          criteriaRequestId,
        );
      } catch (cause) {
        if (
          cause instanceof Error
          && ["PREFERENCE_CATALOG_CHANGED", "PREFERENCE_CATALOG_VERSION_CONFLICT"].includes(cause.message)
        ) throw cause;
        const conversation = await api.getConversation(sessionId);
        if (!conversation.recommendation_criteria || !sameCriteria(conversation.recommendation_criteria, draftCriteria)) throw cause;
        committed = {
          session_id: sessionId,
          criteria: conversation.recommendation_criteria,
          criteria_version: conversation.criteria_version ?? 0,
          state_version: conversation.state_version,
        };
      }
      sessionStorage.removeItem(criteriaRequestKey);
      stateVersionRef.current = committed.state_version;
      commitCriteria(committed.criteria ?? draftCriteria, committed.criteria_version);
      const request: RecommendationRequestV2 = {
        request_id: createId("recommendation"),
        expected_state_version: committed.state_version,
        criteria_version: committed.criteria_version,
        mode: "INITIAL",
      };
      setBusy(false);
      await executeRecommendation(request);
    } catch (cause) {
      if (
        cause instanceof Error
        && ["PREFERENCE_CATALOG_CHANGED", "PREFERENCE_CATALOG_VERSION_CONFLICT"].includes(cause.message)
      ) {
        sessionStorage.removeItem(criteriaRequestKey);
        setRecommendationPhase("SELECTING");
        setError(catalogChangedCopy);
        reloadCatalog();
        setBusy(false);
        return;
      }
      setRecommendationPhase("ERROR");
      setError(language === "English"
        ? actionableError(cause, recommendationCopy.failedDescription)
        : recommendationCopy.failedDescription);
      setBusy(false);
    }
  }

  async function requestAnother(mode: RecommendationMode) {
    if (!criteriaVersion || busy) return;
    setRecommendationPhase("RETRIEVING");
    await executeRecommendation({
      request_id: createId("recommendation"),
      expected_state_version: stateVersionRef.current,
      criteria_version: criteriaVersion,
      mode,
    });
  }

  async function chooseMenu(recommendation: StructuredRecommendation) {
    const snapshotId = latestRecommendation?.snapshot_id;
    if (!snapshotId) return;
    setBusy(true);
    setError("");
    try {
      const result = await recordConversationEvent({
        event_type: "SELECT_MENU",
        snapshot_id: snapshotId,
        menu_id: recommendation.menu.menu_id,
      });
      setSelectedMenu(result.selected_menu ?? recommendation.menu);
      setRecommendationPhase("ORDERING");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      await refreshConversation().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function updateConversationOptions(
    menuId: string,
    optionGroupId: string,
    optionItemIds: string[],
    riskAcknowledged: boolean,
  ) {
    if (selectedMenu?.menu_id !== menuId) return;
    setBusy(true);
    setError("");
    try {
      await recordConversationEvent({
        event_type: "UPDATE_OPTIONS",
        menu_id: menuId,
        option_group_id: optionGroupId,
        option_item_ids: optionItemIds,
        risk_acknowledged: riskAcknowledged,
      });
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
      await refreshConversation().catch(() => undefined);
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  function editCriteria() {
    if (committedCriteria) setDraftCriteria(committedCriteria);
    setSelectedMenu(null);
    setRecommendationPhase("SELECTING");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function editProfile() {
    navigate(`/profile?edit=1&returnTo=${encodeURIComponent(`/chat/${sessionId}`)}`);
  }

  function openCart() {
    document.querySelector<HTMLElement>("[data-testid='order-flow']")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  const showsLoading = hydrating || recommendationPhase === "RETRIEVING" || recommendationPhase === "GENERATING";
  return (
    <main className="chat-shell structured-recommendation-shell">
      <section className="chat-column">
        <header className="chat-header">
          <div className="brand-mark compact">YO<span>BI</span></div>
          <div><strong>{copy.buddy}</strong><span><i /> {recommendationCopy.selectorEyebrow}</span></div>
          <button type="button" aria-label={recommendationCopy.editProfile} title={recommendationCopy.editProfile} onClick={editProfile}><Settings2 size={18} /></button>
          <button className="cart-button" aria-label={language === "English" ? `${journeyCopy.openCart}, ${cartQuantity} items` : `${journeyCopy.openCart}, ${journeyCopy.quantity} ${cartQuantity}`} onClick={openCart} disabled={!selectedMenu}><ShoppingBag size={19} />{cartQuantity > 0 && <span className="cart-badge">{cartQuantity}</span>}</button>
        </header>

        <div className="structured-recommendation-content" aria-live="polite">
          {catalogLoading && !catalog && <section className="recommendation-progress"><span className="loading-orbit" /><h1>{recommendationCopy.loadingChoices}</h1></section>}
          {catalogError && !catalog && <section className="recommendation-state-card error"><h1>{recommendationCopy.catalogFailed}</h1><button className="primary-button" onClick={reloadCatalog}>{recommendationCopy.retry}</button></section>}
          {catalogStale && catalog && <div className="catalog-stale-notice" role="status"><span>{recommendationCopy.savedCatalog}</span><button type="button" onClick={reloadCatalog}>{recommendationCopy.retry}</button></div>}
          {error && recommendationPhase !== "ERROR" && <p className="form-error" role="alert">{error}</p>}

          {catalog && recommendationPhase === "SELECTING" && (
            <PreferenceSelector
              catalog={catalog}
              criteria={draftCriteria}
              copy={recommendationCopy}
              busy={busy}
              canSubmitUnchanged={Boolean(committedCriteria)}
              conflictMessage={recommendationConflictCopy}
              onChange={setDraftCriteria}
              onComplete={() => void submitCriteria()}
            />
          )}

          {catalog && showsLoading && (
            <section className="recommendation-progress">
              <span className="loading-orbit" />
              <h1>{hydrating ? recommendationCopy.restoring : recommendationPhase === "GENERATING" ? recommendationCopy.generating : recommendationCopy.retrieving}</h1>
              <p>{recommendationCopy.noHiddenRelaxation}</p>
            </section>
          )}

          {catalog && latestRecommendation && (recommendationPhase === "RESULTS" || recommendationPhase === "SEARCH_FALLBACK") && (
            <RecommendationResults
              batch={latestRecommendation}
              catalog={catalog}
              copy={recommendationCopy}
              language={language}
              locale={locale}
              busy={busy}
              onChoose={(item) => void chooseMenu(item)}
              onSimilar={() => void requestAnother("SIMILAR")}
              onEdit={editCriteria}
              onRetry={() => void requestAnother("RETRY")}
            />
          )}

          {recommendationPhase === "NO_RESULTS" && <section className="recommendation-state-card"><h1>{recommendationCopy.noResultsTitle}</h1><p>{recommendationCopy.noResultsDescription}</p><button className="primary-button" onClick={editCriteria}>{recommendationCopy.editCriteria}</button></section>}
          {recommendationPhase === "ERROR" && <section className="recommendation-state-card error"><h1>{recommendationCopy.failedTitle}</h1><p>{error || recommendationCopy.failedDescription}</p><div className="button-row"><button className="primary-button" onClick={() => pendingRecommendation ? void recoverRecommendation(pendingRecommendation) : void requestAnother("RETRY")}>{recommendationCopy.tryAgain}</button><button className="secondary-button" onClick={editCriteria}>{recommendationCopy.editCriteria}</button></div></section>}

          {selectedMenu && recommendationPhase === "ORDERING" && (
            <OrderFlowPanel
              sessionId={sessionId}
              menu={selectedMenu}
              addressRefId={addressRefId}
              dietaryFilters={(committedCriteria ?? draftCriteria).dietary_filters}
              onClose={() => { setSelectedMenu(null); setRecommendationPhase("RESULTS"); }}
              onOptionChange={updateConversationOptions}
            />
          )}
        </div>
        <footer className="experience-notice">{recommendationCopy.experienceNotice}</footer>
      </section>
    </main>
  );
}
