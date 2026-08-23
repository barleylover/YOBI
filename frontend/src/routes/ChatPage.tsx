import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { ChannelMenu } from "../components/ChannelMenu";
import { CartSheet } from "../components/CartSheet";
import { OrderFlowPanel } from "../components/OrderFlowPanel";
import { PreferenceWizard } from "../components/PreferenceWizard";
import { PreparingScreen } from "../components/PreparingScreen";
import { RecommendationResults } from "../components/RecommendationResults";
import { actionableError, api } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage, menuName } from "../lib/locale";
import { getProductCopy } from "../lib/productI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import { findMenuProjection, recommendationCriteriaEqual } from "../lib/recommendationState";
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
  RecommendationPreviewV2,
  RecommendationRequestV2,
  StructuredRecommendation,
} from "../types";

function createId(prefix: string) {
  const value = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${value}`;
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
  const { journeyCopy, language, locale } = useI18n();
  const productCopy = getProductCopy(asSupportedLanguage(language));
  const v2 = getRedesignCopy(asSupportedLanguage(language));
  const recommendationCopy = getRecommendationCopy(language);
  const recommendationConflictCopy = getRecommendationConflictCopy(language);
  const catalogChangedCopy = getCatalogChangedCopy(language);
  const { catalog, loading: catalogLoading, stale: catalogStale, error: catalogError, reload: reloadCatalog } = usePreferenceCatalog(locale);
  const [hydrating, setHydrating] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<RecommendationPreviewV2 | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewMessage, setPreviewMessage] = useState("");
  const [selectedMenu, setSelectedMenu] = useState<MenuSummary | null>(null);
  const [precomputedOptionsOnly, setPrecomputedOptionsOnly] = useState(false);
  const [cartOpen, setCartOpen] = useState(false);
  const [cartRevision, setCartRevision] = useState(0);
  const [wizardStartSection, setWizardStartSection] = useState<"core" | "conditions">("core");
  const [editingCriteria, setEditingCriteria] = useState(false);
  const [pollRevision, setPollRevision] = useState(0);
  const stateVersionRef = useRef(session?.state_version ?? 0);
  const pollCountRef = useRef(0);
  const pollStartedAtRef = useRef(0);
  const recommendationAbortRef = useRef<AbortController | null>(null);
  const cancelledRequestIdsRef = useRef(new Set<string>());
  const cancellationRevisionRef = useRef(0);
  const previewAbortRef = useRef<AbortController | null>(null);
  const previewValidationAbortRef = useRef<AbortController | null>(null);
  const lastPreviewCriteriaRef = useRef("");
  const criteriaReturnPhaseRef = useRef(recommendationPhase);
  const criteriaReturnMenuRef = useRef<MenuSummary | null>(null);
  const criteriaReturnPrecomputedRef = useRef(false);
  const criteriaRequestKey = `yobi-pending-criteria-request-${sessionId}`;

  const applyBatch = useCallback((batch: RecommendationBatchV2) => {
    if (cancelledRequestIdsRef.current.has(batch.request_id)) return;
    stateVersionRef.current = batch.state_version;
    setLatestRecommendation(batch);
    if (batch.status !== "PENDING") {
      setPendingRecommendation(null);
      pollCountRef.current = 0;
      pollStartedAtRef.current = 0;
    }
    if (batch.status === "PENDING") {
      const current = useSessionStore.getState().pendingRecommendation;
      if (current?.request_id !== batch.request_id) {
        pollStartedAtRef.current = Date.now();
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
    if (conversation.recommendation_criteria && conversation.criteria_version) {
      commitCriteria(conversation.recommendation_criteria, conversation.criteria_version);
    }
    const batch = conversation.active_recommendation ?? conversation.latest_recommendation;
    if (batch) applyBatch(batch);
    // Recommendation snapshots are immutable and can predate later menu/option events.
    // The live conversation version is the final concurrency authority after hydration.
    stateVersionRef.current = conversation.state_version;
    const selectedMenuId = conversation.meal_need_state.selected_menu_id;
    if (!selectedMenuId) {
      setSelectedMenu(null);
      setPrecomputedOptionsOnly(false);
      return;
    }
    const fromV2Item = batch?.recommendations.find((item) => item.menu.menu_id === selectedMenuId);
    const fromV2 = fromV2Item
      ? { ...fromV2Item.menu, localized_title: fromV2Item.localized_title }
      : null;
    const fromConversation = conversation.selected_menu?.menu_id === selectedMenuId
      ? conversation.selected_menu
      : null;
    const fromLegacy = batch
      ? null
      : findMenuProjection(conversation.latest_snapshot?.cards, selectedMenuId);
    const restoredMenu = fromV2 ?? fromConversation ?? fromLegacy ?? null;
    setSelectedMenu(restoredMenu);
    if (restoredMenu) {
      setPrecomputedOptionsOnly(Boolean(fromConversation && !fromV2));
      setRecommendationPhase("ORDERING");
    }
  }, [applyBatch, commitCriteria, setRecommendationPhase]);

  const refreshConversation = useCallback(async () => {
    const conversation = await api.getConversation(sessionId);
    applyConversation(conversation);
    return conversation;
  }, [applyConversation, sessionId]);

  const executeRecommendation = useCallback(async (request: RecommendationRequestV2) => {
    cancelledRequestIdsRef.current.delete(request.request_id);
    recommendationAbortRef.current?.abort();
    const controller = new AbortController();
    recommendationAbortRef.current = controller;
    setBusy(true);
    setError("");
    setPendingRecommendation(request);
    try {
      const batch = await api.createRecommendation(sessionId, request, controller.signal);
      applyBatch(batch);
    } catch (cause) {
      if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
      try {
        const conversation = await api.getConversation(sessionId);
        const recovered = conversation.active_recommendation ?? conversation.latest_recommendation;
        if (recovered?.request_id === request.request_id) {
          applyConversation(conversation);
          return;
        }
      } catch { /* Keep the stable request id for explicit recovery. */ }
      setRecommendationPhase("ERROR");
      setError(actionableError(cause, recommendationCopy.failedDescription, language));
    } finally {
      if (recommendationAbortRef.current === controller) {
        recommendationAbortRef.current = null;
        setBusy(false);
      }
    }
  }, [applyBatch, applyConversation, language, recommendationCopy.failedDescription, sessionId, setPendingRecommendation, setRecommendationPhase]);

  const recoverRecommendation = useCallback(async (request: RecommendationRequestV2) => {
    setBusy(true);
    setError("");
    try {
      const batch = await api.getRecommendationRequest(sessionId, request.request_id);
      applyBatch(batch);
    } catch {
      try {
        const conversation = await api.getConversation(sessionId);
        const recovered = conversation.active_recommendation ?? conversation.latest_recommendation;
        if (recovered?.request_id === request.request_id) {
          applyConversation(conversation);
          return;
        }
      } catch { /* Keep the request available for another GET recovery attempt. */ }
      // A single failed poll must not turn a still-running, idempotent request
      // into a visible terminal error. The bounded polling deadline below is
      // the authority for an actually unrecoverable request.
      setRecommendationPhase(latestRecommendation?.phase === "GENERATING" ? "GENERATING" : "RETRIEVING");
    } finally {
      setBusy(false);
      setPollRevision((revision) => revision + 1);
    }
  }, [applyBatch, applyConversation, latestRecommendation?.phase, sessionId, setRecommendationPhase]);

  const checkCriteriaPreview = useCallback(async (
    criteria: typeof draftCriteria,
    blockIfZero = false,
  ) => {
    if (!catalog) return true;
    // A catalog-load preview can be scheduled while a chip click is waiting
    // for its zero-result validation. Keep the two requests independent so
    // the background preview cannot cancel a valid user selection.
    if (!blockIfZero && previewValidationAbortRef.current) return true;
    if (blockIfZero) {
      previewAbortRef.current?.abort();
      previewValidationAbortRef.current?.abort();
    } else {
      previewAbortRef.current?.abort();
    }
    const controller = new AbortController();
    const controllerRef = blockIfZero ? previewValidationAbortRef : previewAbortRef;
    controllerRef.current = controller;
    setPreviewLoading(true);
    setPreviewMessage("");
    try {
      const result = await api.previewRecommendation(
        sessionId,
        criteria,
        catalog.catalog_version,
        controller.signal,
      );
      if (blockIfZero && result.eligible_menu_count === 0) {
        setPreviewMessage(productCopy.recommendation.zeroCombination);
        return false;
      }
      lastPreviewCriteriaRef.current = JSON.stringify(criteria);
      setPreview(result);
      setPreviewMessage(result.eligible_menu_count === 0 ? productCopy.recommendation.zeroCombination : "");
      return true;
    } catch (cause) {
      if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return false;
      setPreviewMessage(productCopy.recommendation.previewUnavailable);
      return true;
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
      if (!previewAbortRef.current && !previewValidationAbortRef.current) {
        setPreviewLoading(false);
      }
    }
  }, [catalog, productCopy.recommendation, sessionId]);

  useEffect(() => () => {
    recommendationAbortRef.current?.abort();
    previewAbortRef.current?.abort();
    previewValidationAbortRef.current?.abort();
  }, []);

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
    if (!catalog || recommendationPhase !== "SELECTING") return;
    const criteriaKey = JSON.stringify(draftCriteria);
    if (criteriaKey === lastPreviewCriteriaRef.current) return;
    const timer = window.setTimeout(() => { void checkCriteriaPreview(draftCriteria); }, 280);
    return () => window.clearTimeout(timer);
  }, [catalog, checkCriteriaPreview, draftCriteria, recommendationPhase]);

  useEffect(() => {
    if (hydrating || latestRecommendation?.status !== "PENDING" || !pendingRecommendation || busy) return;
    if (!pollStartedAtRef.current) pollStartedAtRef.current = Date.now();
    if (Date.now() - pollStartedAtRef.current >= 150_000) {
      setRecommendationPhase("ERROR");
      setError(recommendationCopy.failedDescription);
      return;
    }
    // Recommendation completion is dominated by the provider call. Poll a
    // little more closely so a finished batch is not hidden for up to 2.5 s,
    // then back off to a still-bounded cadence for long-running requests.
    const pollDelayMs = pollCountRef.current < 10 ? 800 : 1_500;
    const timer = window.setTimeout(() => {
      pollCountRef.current += 1;
      void recoverRecommendation(pendingRecommendation);
    }, pollDelayMs);
    return () => window.clearTimeout(timer);
  }, [busy, hydrating, latestRecommendation, pendingRecommendation, pollRevision, recommendationCopy.failedDescription, recoverRecommendation, setRecommendationPhase]);

  useEffect(() => {
    if (!catalog) return;
    const current = useSessionStore.getState().draftCriteria;
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
    const next = { ...current, dietary_filters: { ...current.dietary_filters } };
    let changed = false;
    let visibleSelectionChanged = false;
    for (const category of categoryKeys) {
      const validCodes = optionCodes.get(category) ?? new Set<string>();
      const retained = current[category].filter((code) => validCodes.has(code));
      if (retained.length !== current[category].length) {
        changed = true;
        visibleSelectionChanged = true;
      }
      next[category] = retained;
    }
    if (
      catalog.capabilities?.halal_certified_only?.enabled === false
      && next.dietary_filters.halal_certified_only
    ) {
      next.dietary_filters = { ...next.dietary_filters, halal_certified_only: false };
      changed = true;
      visibleSelectionChanged = true;
    }
    if (catalog.capabilities?.vegan?.enabled === false && next.dietary_filters.vegan) {
      next.dietary_filters = { ...next.dietary_filters, vegan: false };
      changed = true;
      visibleSelectionChanged = true;
    }
    if (next.schema_version === "3") {
      const priceCatalog = catalog.price_range_krw ?? { min: 8_000, max: 25_000, step: 1_000 };
      const selectedPrice = next.price_range_krw ?? { min: priceCatalog.min, max: priceCatalog.max };
      const clampedPrice = {
        min: Math.max(priceCatalog.min, Math.min(selectedPrice.min, priceCatalog.max - priceCatalog.step)),
        max: Math.min(priceCatalog.max, Math.max(selectedPrice.max, priceCatalog.min + priceCatalog.step)),
      };
      if (!next.price_range_krw || next.price_range_krw.min !== clampedPrice.min || next.price_range_krw.max !== clampedPrice.max) {
        next.price_range_krw = clampedPrice;
        changed = true;
      }
      if (!next.spice_preference) {
        next.spice_preference = "SIMILAR";
        changed = true;
      }
      next.price_bands = [];
    } else if (catalog.capabilities?.max_spice_level?.enabled === false && next.max_spice_level !== 5) {
      next.max_spice_level = 5;
      changed = true;
    }
    if (changed) {
      setDraftCriteria(next);
      if (visibleSelectionChanged) setError(catalogChangedCopy);
    }
  }, [catalog, catalogChangedCopy, draftCriteria, setDraftCriteria]);

  const transcriptCriteria = committedCriteria ?? draftCriteria;
  const selectedPreferenceLabels = useMemo(() => {
    if (!catalog) return [];
    const categoryOrder = [
      "cuisine_origins",
      "main_ingredients",
      "food_forms",
      "flavors",
      "textures",
      "cooking_methods",
      "temperatures",
      "price_bands",
    ];
    const categories = [...catalog.categories].sort(
      (left, right) => categoryOrder.indexOf(left.code) - categoryOrder.indexOf(right.code),
    );
    const labels = categories.flatMap((category) => {
      const selected = new Set(transcriptCriteria[category.code]);
      return category.options
        .filter((option) => selected.has(option.code))
        .map((option) => option.label);
    });
    if (transcriptCriteria.schema_version === "3") {
      labels.push({
        LESS: v2.spiceLess,
        SIMILAR: v2.spiceSimilar,
        MORE: v2.spiceMore,
      }[transcriptCriteria.spice_preference ?? "SIMILAR"]);
      if (transcriptCriteria.price_range_krw) {
        labels.push(
          `₩${transcriptCriteria.price_range_krw.min.toLocaleString(locale)}–₩${transcriptCriteria.price_range_krw.max.toLocaleString(locale)}`,
        );
      }
    }
    if (transcriptCriteria.dietary_filters.halal_certified_only) labels.push(recommendationCopy.halal);
    if (transcriptCriteria.dietary_filters.vegan) labels.push(recommendationCopy.vegan);
    const visible = labels.slice(0, 8);
    if (labels.length > visible.length) visible.push(v2.morePreferences(labels.length - visible.length));
    return visible;
  }, [catalog, locale, recommendationCopy.halal, recommendationCopy.vegan, transcriptCriteria, v2]);
  const conversationDate = useMemo(() => new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
  }).format(new Date()), [locale]);

  function applyDraftCriteria(next: typeof draftCriteria) {
    if (!catalog) {
      setDraftCriteria(next);
      return;
    }
    const normalized = {
      ...next,
      dietary_filters: {
        halal_certified_only: catalog.capabilities?.halal_certified_only?.enabled === false
          ? false
          : next.dietary_filters.halal_certified_only,
        vegan: catalog.capabilities?.vegan?.enabled === false ? false : next.dietary_filters.vegan,
      },
      max_spice_level: catalog.capabilities?.max_spice_level?.enabled === false ? 5 as const : next.max_spice_level,
    };
    setDraftCriteria(normalized);
  }

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
    setEditingCriteria(false);
    const cancellationRevision = cancellationRevisionRef.current;
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
        if (
          !conversation.recommendation_criteria
          || !recommendationCriteriaEqual(conversation.recommendation_criteria, draftCriteria)
        ) throw cause;
        committed = {
          session_id: sessionId,
          criteria: conversation.recommendation_criteria,
          criteria_version: conversation.criteria_version ?? 0,
          state_version: conversation.state_version,
        };
      }
      sessionStorage.removeItem(criteriaRequestKey);
      if (cancellationRevision !== cancellationRevisionRef.current) {
        setBusy(false);
        return;
      }
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
      setError(actionableError(cause, recommendationCopy.failedDescription, language));
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
      setPrecomputedOptionsOnly(false);
      setSelectedMenu({
        ...(result.selected_menu ?? recommendation.menu),
        localized_title: recommendation.localized_title,
      });
      setRecommendationPhase("ORDERING");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
      await refreshConversation().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function chooseCollectionMenu(menu: MenuSummary, snapshotId: string) {
    setBusy(true);
    setError("");
    try {
      const result = await recordConversationEvent({
        event_type: "SELECT_MENU",
        snapshot_id: snapshotId,
        menu_id: menu.menu_id,
      });
      setPrecomputedOptionsOnly(true);
      setSelectedMenu(result.selected_menu ?? menu);
      setRecommendationPhase("ORDERING");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
      await refreshConversation().catch(() => undefined);
      throw cause;
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
      setError(actionableError(cause, journeyCopy.retry, language));
      await refreshConversation().catch(() => undefined);
      throw cause;
    } finally {
      setBusy(false);
    }
  }

  function editCriteria() {
    setWizardStartSection("core");
    criteriaReturnPhaseRef.current = recommendationPhase;
    criteriaReturnMenuRef.current = selectedMenu;
    criteriaReturnPrecomputedRef.current = precomputedOptionsOnly;
    setEditingCriteria(true);
    if (committedCriteria) setDraftCriteria(committedCriteria);
    setSelectedMenu(null);
    setPrecomputedOptionsOnly(false);
    setRecommendationPhase("SELECTING");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function cancelCriteriaEdit() {
    if (committedCriteria) setDraftCriteria(committedCriteria);
    setSelectedMenu(criteriaReturnMenuRef.current);
    setPrecomputedOptionsOnly(criteriaReturnPrecomputedRef.current);
    setRecommendationPhase(criteriaReturnPhaseRef.current);
    setEditingCriteria(false);
    setError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function editProfile() {
    navigate(`/profile?edit=1&returnTo=${encodeURIComponent(`/chat/${sessionId}`)}`);
  }

  function openCart() {
    setCartOpen(true);
  }

  function cancelRecommendation() {
    cancellationRevisionRef.current += 1;
    const requestId = pendingRecommendation?.request_id ?? latestRecommendation?.request_id;
    if (requestId) {
      cancelledRequestIdsRef.current.add(requestId);
      void api.cancelRecommendationRequest(sessionId, requestId).catch(() => undefined);
    }
    recommendationAbortRef.current?.abort();
    setPendingRecommendation(null);
    setBusy(false);
    setWizardStartSection("conditions");
    setSelectedMenu(null);
    setRecommendationPhase("SELECTING");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  const showsLoading = hydrating || recommendationPhase === "RETRIEVING" || recommendationPhase === "GENERATING";

  if (catalogLoading && !catalog) {
    return (
      <main className="v2-screen subtle v2-preparing">
        <div className="v2-preparing-body">
          <img src="/figma/logo-mark.svg" alt="" width={62} height={62} />
          <div className="v2-preparing-heading">
            <h1>{recommendationCopy.loadingChoices}</h1>
          </div>
        </div>
      </main>
    );
  }

  if (catalogError && !catalog) {
    return (
      <main className="v2-screen subtle v2-preparing">
        <div className="v2-preparing-body">
          <img src="/figma/logo-mark.svg" alt="" width={62} height={62} />
          <div className="v2-preparing-heading">
            <h1>{recommendationCopy.catalogFailed}</h1>
          </div>
          <button type="button" className="v2-cta compact" style={{ maxWidth: 240 }} onClick={reloadCatalog}>
            {recommendationCopy.retry}
          </button>
        </div>
      </main>
    );
  }

  if (catalog && showsLoading) {
    return (
      <main aria-live="polite">
        <PreparingScreen
          v2={v2}
          phase={recommendationPhase === "GENERATING" ? "GENERATING" : "RETRIEVING"}
          onCancel={cancelRecommendation}
        />
      </main>
    );
  }

  if (catalog && recommendationPhase === "SELECTING") {
    return (
      <main>
        <PreferenceWizard
          catalog={catalog}
          criteria={draftCriteria}
          copy={recommendationCopy}
          v2={v2}
          initialSection={wizardStartSection}
          busy={busy}
          previewLoading={previewLoading}
          preview={preview}
          previewMessage={previewMessage}
          canSubmitUnchanged={Boolean(committedCriteria)}
          conflictMessage={recommendationConflictCopy}
          notice={[catalogStale ? recommendationCopy.savedCatalog : "", error].filter(Boolean).join(" ")}
          onChange={applyDraftCriteria}
          onValidateAdd={(nextCriteria) => checkCriteriaPreview(nextCriteria, true)}
          onComplete={() => void submitCriteria()}
          onBack={editingCriteria ? cancelCriteriaEdit : editProfile}
          onCancel={editingCriteria ? cancelCriteriaEdit : undefined}
        />
      </main>
    );
  }

  const messageTime = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date());
  const showsResultActions = catalog && latestRecommendation
    && (recommendationPhase === "RESULTS" || recommendationPhase === "SEARCH_FALLBACK");
  const showsRecommendationTranscript = Boolean(
    catalog
    && latestRecommendation
    && ["RESULTS", "SEARCH_FALLBACK", "ORDERING"].includes(recommendationPhase),
  );

  return (
    <main className="v2-screen v2-chat">
      <header className="v2-chat-header">
        <button type="button" className="v2-icon-button" aria-label={v2.back} onClick={editCriteria}>
          <img src="/figma/back-chevron.svg" alt="" width={9} height={16} />
        </button>
        <div className="v2-chat-title">
          <p><strong>{productCopy.recommendation.assistantName}</strong><img src="/figma/verified-badge.svg" alt="" width={16} height={16} /></p>
          <span>{v2.alwaysOn}</span>
        </div>
        <button
          type="button"
          className="v2-cart-button"
          aria-label={language === "English" ? `${journeyCopy.openCart}, ${cartQuantity} item${cartQuantity === 1 ? "" : "s"}` : `${journeyCopy.openCart}, ${journeyCopy.quantity} ${cartQuantity}`}
          onClick={openCart}
        >
          <span className="cart-box" aria-hidden="true" />
          {cartQuantity > 0 && <span className="cart-badge">{cartQuantity}</span>}
        </button>
      </header>

      <div className="v2-thread" aria-live="polite">
        {catalogStale && catalog && (
          <div className="v2-banner" role="status">
            <p>{recommendationCopy.savedCatalog} <button type="button" className="v2-inline-clear" onClick={reloadCatalog}>{recommendationCopy.retry}</button></p>
          </div>
        )}
        {error && recommendationPhase !== "ERROR" && <p className="v2-error" role="alert">{error}</p>}

        <div className="v2-date-divider" aria-hidden="true"><span>{conversationDate}</span></div>

        {catalog && recommendationPhase !== "SELECTING" && (
          <>
          <div className="v2-bot-message" data-testid="craving-question-message">
            <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
            <div className="v2-bot-stack">
              <p className="v2-bot-name">{productCopy.recommendation.assistantName}</p>
              <div className="v2-bubble">
                <p>{v2.craveTitle}</p>
              </div>
              <p className="v2-timestamp">{messageTime}</p>
            </div>
          </div>
          <div className="v2-user-message" data-testid="user-preference-message">
            <div className="v2-user-bubble v2-user-preferences" aria-label={recommendationCopy.selectedSummary}>
              {selectedPreferenceLabels.map((label, index) => (
                <span key={`${label}-${index}`}>{label}</span>
              ))}
            </div>
          </div>
          </>
        )}

        {showsRecommendationTranscript && latestRecommendation && catalog && (
          <RecommendationResults
            batch={latestRecommendation}
            catalog={catalog}
            spiceReferenceCountry={(committedCriteria ?? draftCriteria).spice_reference_country}
            copy={recommendationCopy}
            v2={v2}
            language={language}
            locale={locale}
            busy={busy}
            readOnly={recommendationPhase === "ORDERING"}
            timestamp={messageTime}
            onChoose={(item) => void chooseMenu(item)}
          />
        )}

        {recommendationPhase === "NO_RESULTS" && (
          <div className="v2-bot-message">
            <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
            <div className="v2-bot-stack">
              <p className="v2-bot-name">{productCopy.recommendation.assistantName}</p>
              <div className="v2-bubble">
                <p><strong>{latestRecommendation?.failure_code?.includes("EXHAUST") ? productCopy.recommendation.exhaustedTitle : recommendationCopy.noResultsTitle}</strong></p>
                <p className="v2-bubble-sub">{latestRecommendation?.failure_code?.includes("EXHAUST") ? productCopy.recommendation.exhaustedDescription : recommendationCopy.noResultsDescription}</p>
              </div>
            </div>
          </div>
        )}
        {recommendationPhase === "ERROR" && (
          <div className="v2-bot-message">
            <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
            <div className="v2-bot-stack">
              <p className="v2-bot-name">{productCopy.recommendation.assistantName}</p>
              <div className="v2-bubble">
                <p><strong>{recommendationCopy.failedTitle}</strong></p>
                <p className="v2-bubble-sub">{error || recommendationCopy.failedDescription}</p>
              </div>
            </div>
          </div>
        )}

        {selectedMenu && recommendationPhase === "ORDERING" && (
          <>
            <div className="v2-user-message" data-testid="selected-menu-message">
              <div className="v2-user-bubble">{menuName(selectedMenu, language)}</div>
            </div>
            <div className="v2-bot-message">
              <img className="v2-bot-avatar" src="/figma/bot-avatar.svg" alt="" />
              <div className="v2-bot-stack">
                <p className="v2-bot-name">{productCopy.recommendation.assistantName}</p>
                <OrderFlowPanel
                  sessionId={sessionId}
                  menu={selectedMenu}
                  addressRefId={addressRefId}
                  dietaryFilters={(committedCriteria ?? draftCriteria).dietary_filters}
                  cartRevision={cartRevision}
                  precomputedOptionsOnly={precomputedOptionsOnly}
                  onClose={() => { setSelectedMenu(null); setRecommendationPhase("RESULTS"); }}
                  onOptionChange={updateConversationOptions}
                />
              </div>
            </div>
          </>
        )}

      </div>

      <div className="v2-quick-replies">
        {showsResultActions && (
          <>
            <button type="button" className="v2-quick-reply" onClick={() => void requestAnother("SIMILAR")} disabled={busy}>
              {v2.seeOtherMenus}
            </button>
            <button type="button" className="v2-quick-reply" onClick={editCriteria} disabled={busy}>
              {v2.editFilters}
            </button>
          </>
        )}
        {(recommendationPhase === "NO_RESULTS" || recommendationPhase === "ERROR") && (
          <>
            <button type="button" className="v2-quick-reply" onClick={editCriteria} disabled={busy}>
              {recommendationCopy.editCriteria}
            </button>
          </>
        )}
      </div>

      <CartSheet
        sessionId={sessionId}
        open={cartOpen}
        language={language}
        locale={locale}
        onClose={() => setCartOpen(false)}
        onCartChange={() => setCartRevision((value) => value + 1)}
        onContinue={selectedMenu ? () => {
          setCartOpen(false);
          document.querySelector<HTMLElement>("[data-testid='order-flow']")?.scrollIntoView({ behavior: "smooth", block: "start" });
        } : undefined}
      />

      <ChannelMenu
        sessionId={sessionId}
        language={language}
        locale={locale}
        disabled={busy}
        onChoose={chooseCollectionMenu}
        onEditProfile={editCriteria}
      />
    </main>
  );
}
