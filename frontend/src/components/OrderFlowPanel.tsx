import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useSessionStore } from "../stores/session";
import type {
  CartPreview,
  DietaryFiltersV2,
  MenuSummary,
  MerchantMenuPresentation,
  OptionGroup,
  RestaurantNoteTranslation,
} from "../types";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage, menuName, merchantName } from "../lib/locale";
import { getRecommendationCopy } from "../lib/recommendationI18n";
import { getRedesignCopy } from "../lib/redesignI18n";
import {
  optionDietaryConflicts,
  optionGroupHasNoneChoice,
  planDefaultOptionSelections,
  selectedOptionsPriceDelta,
  toggledOptionSelection,
} from "../lib/orderFlow";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  addressRefId: string;
  dietaryFilters?: DietaryFiltersV2;
  cartRevision?: number;
  precomputedOptionsOnly?: boolean;
  onClose: () => void;
  onOptionChange?: (
    menuId: string,
    optionGroupId: string,
    optionItemIds: string[],
    riskAcknowledged: boolean,
  ) => Promise<void>;
}

type Phase = "options" | "note" | "more" | "browse" | "delivery" | "review" | "merchant-conflict";

export function OrderFlowPanel({
  sessionId,
  menu,
  addressRefId,
  dietaryFilters,
  cartRevision = 0,
  precomputedOptionsOnly = false,
  onClose,
  onOptionChange,
}: Props) {
  const navigate = useNavigate();
  const setCartQuantity = useSessionStore((state) => state.setCartQuantity);
  const sourceLanguage = useSessionStore((state) => state.profile?.preferred_language) ?? "English";
  const addressSummary = useSessionStore((state) => state.addressSummary);
  const { copy, dynamicCopy, journeyCopy, language, locale } = useI18n();
  const recommendationCopy = getRecommendationCopy(language);
  const v2 = getRedesignCopy(asSupportedLanguage(language));
  const [activeMenu, setActiveMenu] = useState(menu);
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string[]>>({});
  const [note, setNote] = useState(journeyCopy.mildNote);
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [merchantMenus, setMerchantMenus] = useState<MerchantMenuPresentation[]>([]);
  const [nextMenuCursor, setNextMenuCursor] = useState<string | null>(null);
  const [loadingMoreMenus, setLoadingMoreMenus] = useState(false);
  const [noteTranslation, setNoteTranslation] = useState<RestaurantNoteTranslation | null>(null);
  const [editingCartItemId, setEditingCartItemId] = useState<string | null>(null);
  const [noteTouched, setNoteTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [error, setError] = useState("");
  const transitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadingMoreMenusRef = useRef(false);

  useEffect(() => {
    let active = true;
    setGroups([]);
    setGroupIndex(0);
    setSelections({});
    setPhase("options");
    setCart(null);
    setEditingCartItemId(null);
    setNoteTouched(false);
    setError("");
    setLoadingOptions(true);
    void (async () => {
      try {
        // Cart ownership is cheap and authoritative. Resolve it before option
        // localization so a cross-merchant selection never sits behind a slow
        // model-backed option request or renders an empty order builder.
        const restoredCart = await api.getCart(sessionId).catch(() => null);
        if (!active) return;
        if (restoredCart?.items.length) {
          setCart(restoredCart);
          setCartQuantity(restoredCart.items.reduce((total, item) => total + item.quantity, 0));
          const cartMerchantId = restoredCart.items[0]?.merchant_id;
          const activeItemExists = restoredCart.items.some((item) => item.menu_id === activeMenu.menu_id);
          if (cartMerchantId && cartMerchantId !== activeMenu.merchant_id) {
            setPhase("merchant-conflict");
            return;
          }

          const result = await api.getOptions(
            activeMenu.menu_id,
            sessionId,
            precomputedOptionsOnly,
          );
          if (!active) return;
          setGroups(result);
          if (activeItemExists) {
            setPhase(restoredCart.missing_slots.includes("delivery_preferences") ? "delivery" : "review");
          } else if (result.length === 0) {
            setPhase("note");
          }
        } else {
          const result = await api.getOptions(
            activeMenu.menu_id,
            sessionId,
            precomputedOptionsOnly,
          );
          if (!active) return;
          setGroups(result);
          if (result.length === 0) setPhase("note");
        }
      } catch (cause) {
        if (active) setError(actionableError(cause, journeyCopy.retry, language));
      } finally {
        if (active) setLoadingOptions(false);
      }
    })();
    return () => {
      active = false;
      if (transitionTimer.current !== null) {
        clearTimeout(transitionTimer.current);
        transitionTimer.current = null;
      }
    };
  }, [activeMenu.menu_id, activeMenu.merchant_id, cartRevision, journeyCopy.retry, language, precomputedOptionsOnly, sessionId, setCartQuantity]);

  useEffect(() => setActiveMenu(menu), [menu]);

  function syncCart(preview: CartPreview) {
    setCart(preview);
    setCartQuantity(preview.items.reduce((total, item) => total + item.quantity, 0));
  }

  async function routeAfterNewCartItem(preview: CartPreview) {
    try {
      const otherMenus = await api.getMerchantMenus(
        sessionId,
        activeMenu.merchant_id,
        preview.items.map((item) => item.menu_id),
      );
      setPhase(otherMenus.length > 0 ? "more" : "delivery");
    } catch {
      // If availability cannot be proven, skip the optional upsell instead of showing a dead end.
      setPhase("delivery");
    }
  }

  async function recoverMerchantConflict(cause: unknown) {
    if (!(cause instanceof Error) || !["CART_MULTIPLE_MERCHANTS", "CART_MERCHANT_CONFLICT"].includes(cause.message)) {
      return false;
    }
    const preview = await api.getCart(sessionId).catch(() => null);
    if (preview) syncCart(preview);
    setPhase("merchant-conflict");
    return true;
  }

  async function clearConflictingCart() {
    if (!cart) return;
    setBusy(true);
    setError("");
    try {
      let preview = cart;
      for (const item of [...cart.items]) {
        preview = await api.deleteCartItem(sessionId, item.cart_item_id);
      }
      syncCart(preview);
      setEditingCartItemId(null);
      setLoadingOptions(true);
      const result = await api.getOptions(
        activeMenu.menu_id,
        sessionId,
        precomputedOptionsOnly,
      );
      setGroups(result);
      setPhase(result.length ? "options" : "note");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setLoadingOptions(false);
      setBusy(false);
    }
  }

  function beginOptionEdit() {
    if (!cart) return;
    const line = cart.items.find((item) => item.menu_id === activeMenu.menu_id);
    if (!line) {
      setPhase(groups.length ? "options" : "note");
      return;
    }
    const selectedIds = new Set(line.options.map((option) => option.option_item_id));
    setSelections(Object.fromEntries(groups.map((group) => [
      group.option_group_id,
      group.items.filter((option) => selectedIds.has(option.option_item_id)).map((option) => option.option_item_id),
    ])));
    setEditingCartItemId(line.cart_item_id);
    setNote("");
    setNoteTouched(false);
    setNoteTranslation(null);
    setGroupIndex(0);
    setPhase(groups.length ? "options" : "note");
  }

  const currentGroup = groups[groupIndex];
  const selectedOptionIds = useMemo(() => Object.values(selections).flat(), [selections]);
  const localizedOptionNames = useMemo(() => new Map(groups.flatMap((group) => group.items.map((option) => [
    option.option_item_id,
    option.display_name || (language === "한국어" ? option.name_ko : option.name_en),
  ]))), [groups, language]);
  const selectedDelta = useMemo(
    () => selectedOptionsPriceDelta(groups, selections),
    [groups, selections],
  );

  function advanceFromGroup() {
    if (transitionTimer.current !== null) clearTimeout(transitionTimer.current);
    transitionTimer.current = setTimeout(() => {
      transitionTimer.current = null;
      if (groupIndex < groups.length - 1) setGroupIndex((value) => value + 1);
      else setPhase("note");
    }, 160);
  }

  async function selectOption(group: OptionGroup, optionId: string) {
    setBusy(true);
    setError("");
    try {
      const current = selections[group.option_group_id] ?? [];
      const next = toggledOptionSelection(group, current, optionId);
      await onOptionChange?.(activeMenu.menu_id, group.option_group_id, next, false);
      setSelections((value) => ({ ...value, [group.option_group_id]: next }));
      if (group.max_select === 1) advanceFromGroup();
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  async function selectNone(group: OptionGroup) {
    setBusy(true);
    setError("");
    try {
      await onOptionChange?.(activeMenu.menu_id, group.option_group_id, [], false);
      setSelections((current) => ({ ...current, [group.option_group_id]: [] }));
      advanceFromGroup();
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  function finishMultiSelect(group: OptionGroup) {
    const count = (selections[group.option_group_id] ?? []).length;
    if (count < group.min_select) {
      setError(v2.requiredTapOne);
      return;
    }
    setError("");
    advanceFromGroup();
  }

  async function applyDefaultsForRest() {
    setBusy(true);
    setError("");
    try {
      const plan = planDefaultOptionSelections(
        groups,
        selections,
        groupIndex,
        dietaryFilters,
      );
      if (plan.missingRequiredGroup) {
        setError(v2.requiredTapOne);
        return;
      }
      for (const update of plan.updates) {
        await onOptionChange?.(
          activeMenu.menu_id,
          update.optionGroupId,
          update.optionItemIds,
          false,
        );
      }
      setSelections(plan.selections);
      setPhase("note");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  async function addToCart() {
    if (note.trim() && (noteTranslation?.status !== "SUCCEEDED" || noteTranslation.source_text !== note)) {
      setError(v2.restaurantNoteHelp);
      return;
    }
    setBusy(true);
    try {
      const preview = editingCartItemId
        ? await api.updateCartItem(sessionId, editingCartItemId, {
            option_item_ids: selectedOptionIds,
            ...(noteTouched ? {
              user_note: note,
              ...(noteTranslation?.translation_id ? { note_translation_id: noteTranslation.translation_id } : {}),
            } : {}),
          })
        : await api.addCartItem(
            sessionId,
            activeMenu.menu_id,
            selectedOptionIds,
            note,
            noteTranslation?.translation_id,
          );
      syncCart(preview);
      if (editingCartItemId) {
        setEditingCartItemId(null);
        setPhase(preview.missing_slots.includes("delivery_preferences") ? "delivery" : "review");
      } else {
        await routeAfterNewCartItem(preview);
      }
    } catch (cause) {
      if (!(await recoverMerchantConflict(cause))) {
        setError(actionableError(cause, journeyCopy.retry, language));
      }
    } finally {
      setBusy(false);
    }
  }

  async function addWithoutRestaurantNote() {
    setBusy(true);
    setError("");
    try {
      const preview = editingCartItemId
        ? await api.updateCartItem(sessionId, editingCartItemId, {
            option_item_ids: selectedOptionIds,
            user_note: "",
          })
        : await api.addCartItem(
            sessionId,
            activeMenu.menu_id,
            selectedOptionIds,
            "",
            undefined,
          );
      syncCart(preview);
      if (editingCartItemId) {
        setEditingCartItemId(null);
        setPhase(preview.missing_slots.includes("delivery_preferences") ? "delivery" : "review");
      } else {
        await routeAfterNewCartItem(preview);
      }
    } catch (cause) {
      if (!(await recoverMerchantConflict(cause))) {
        setError(actionableError(cause, journeyCopy.retry, language));
      }
    } finally {
      setBusy(false);
    }
  }

  async function translateNote() {
    if (!note.trim()) {
      setNoteTranslation(null);
      setError("");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setNoteTranslation(await api.translateRestaurantNote(sessionId, note, sourceLanguage));
    } catch (cause) {
      setNoteTranslation(null);
      setError(actionableError(cause, v2.retryTranslation, language));
    } finally {
      setBusy(false);
    }
  }

  async function loadMerchantMenus(cursor: string | null, replace = false) {
    if (!cart || loadingMoreMenusRef.current) return;
    loadingMoreMenusRef.current = true;
    setLoadingMoreMenus(true);
    setError("");
    try {
      const page = await api.getMerchantMenuPresentations(sessionId, activeMenu.merchant_id, {
        cursor,
        limit: 12,
        exclude_menu_ids: cart.items.map((item) => item.menu_id),
      });
      setMerchantMenus((current) => {
        const merged = replace ? page.items : [...current, ...page.items];
        return Array.from(new Map(merged.map((item) => [item.menu.menu_id, item])).values());
      });
      setNextMenuCursor(page.next_cursor ?? null);
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      loadingMoreMenusRef.current = false;
      setLoadingMoreMenus(false);
    }
  }

  async function browseThisRestaurant() {
    if (!cart) return;
    setBusy(true);
    setError("");
    try {
      const page = await api.getMerchantMenuPresentations(sessionId, activeMenu.merchant_id, {
        limit: 12,
        exclude_menu_ids: cart.items.map((item) => item.menu_id),
      });
      setMerchantMenus(page.items);
      setNextMenuCursor(page.next_cursor ?? null);
      setPhase(page.items.length ? "browse" : "delivery");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  function chooseAdditionalMenu(nextMenu: MerchantMenuPresentation) {
    setActiveMenu({ ...nextMenu.menu, localized_title: nextMenu.localized_title } as MenuSummary);
    setMerchantMenus([]);
    setNextMenuCursor(null);
    setNote(journeyCopy.mildNote);
    setNoteTouched(false);
    setNoteTranslation(null);
  }

  async function saveDelivery() {
    setBusy(true);
    try {
      const preview = await api.updateDelivery(sessionId, addressRefId);
      syncCart(preview);
      setPhase("review");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  async function proceedToHandoff() {
    setBusy(true);
    try {
      const confirmed = await api.confirmCart(sessionId);
      syncCart(confirmed);
      navigate("/handoff");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  async function changeQuantity(cartItemId: string, quantity: number) {
    if (quantity < 1 || quantity > 10) return;
    setBusy(true);
    setError("");
    try {
      syncCart(await api.updateCartItem(sessionId, cartItemId, quantity));
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(cartItemId: string) {
    setBusy(true);
    setError("");
    try {
      const preview = await api.deleteCartItem(sessionId, cartItemId);
      syncCart(preview);
      if (preview.items.length === 0) setPhase(groups.length ? "options" : "note");
    } catch (cause) {
      setError(actionableError(cause, journeyCopy.retry, language));
    } finally {
      setBusy(false);
    }
  }

  function changeAddress() {
    navigate(`/profile?edit=1&returnTo=${encodeURIComponent(`/chat/${sessionId}`)}`);
  }

  const won = (value: number) => `₩${value.toLocaleString(locale)}`;
  const minimumOrderLabel = language === "한국어" ? "최소 주문" : language === "日本語" ? "最低注文" : "Minimum order";

  return (
    <section className="v2-order-flow" aria-label={copy.orderBuilder} data-testid="order-flow">
      {loadingOptions && phase === "options" && !currentGroup && (
        <p className="v2-status" role="status">{journeyCopy.loading}</p>
      )}
      {phase === "merchant-conflict" && cart && (
        <article className="v2-order-card" role="alert">
          <div className="v2-order-body">
            <div className="v2-order-heading">
              <h3>{language === "한국어" ? "다른 가게의 메뉴가 장바구니에 있어요" : language === "日本語" ? "別のお店のメニューがカートにあります" : "Your cart has items from another restaurant"}</h3>
              <p>{language === "한국어" ? "한 번에 한 가게만 주문할 수 있습니다. 기존 장바구니를 비운 뒤 이 메뉴를 설정하거나, 장바구니를 유지하세요." : language === "日本語" ? "一度に注文できるのは1店舗です。現在のカートを空にしてこのメニューを設定するか、カートをそのままにしてください。" : "A cart can contain one restaurant at a time. Clear the current cart to configure this menu, or keep your existing order."}</p>
            </div>
            <button type="button" className="v2-card-primary" onClick={() => void clearConflictingCart()} disabled={busy}>
              {language === "한국어" ? "기존 장바구니 비우고 계속" : language === "日本語" ? "現在のカートを空にして続ける" : "Clear cart and continue"}
            </button>
            <button type="button" className="v2-card-secondary" onClick={onClose} disabled={busy}>
              {language === "한국어" ? "기존 장바구니 유지" : language === "日本語" ? "現在のカートを保持" : "Keep current cart"}
            </button>
          </div>
        </article>
      )}

      {phase === "options" && currentGroup && (
        <>
          <article className="v2-order-card" data-testid={`option-group-${currentGroup.option_group_id}`}>
            <div className="v2-card-strip stacked">
              <div className="strip-row">
                <span>{v2.orderSetup(groupIndex + 1, groups.length)}</span>
                <span>+{won(selectedDelta)}</span>
              </div>
              <div className="strip-progress" aria-hidden="true">
                {groups.map((group, index) => (
                  <i key={group.option_group_id} className={index <= groupIndex ? "filled" : ""} />
                ))}
              </div>
            </div>
            <div className="v2-order-body">
              <div className="v2-order-heading">
                <h3>{currentGroup.display_name || (language === "한국어" ? currentGroup.name_ko : currentGroup.name_en)}</h3>
                <p>{currentGroup.min_select === 0 ? v2.optionalTap : v2.requiredTapOne}</p>
              </div>
              {currentGroup.min_select === 0 && !optionGroupHasNoneChoice(currentGroup) && (
                <div className="v2-option-shell">
                  <button
                    type="button"
                    className={(selections[currentGroup.option_group_id] ?? []).length === 0
                      ? "v2-option-row selected"
                      : "v2-option-row"}
                    onClick={() => void selectNone(currentGroup)}
                    disabled={busy}
                  >
                    <span className={(selections[currentGroup.option_group_id] ?? []).length === 0 ? "radio checked" : "radio"} aria-hidden="true" />
                    <span className="labels"><strong>{v2.noneOption}</strong></span>
                  </button>
                </div>
              )}
              {currentGroup.items.map((option) => {
                const { breaksHalal, breaksVegan, needsVeganCheck } = optionDietaryConflicts(
                  option,
                  dietaryFilters,
                );
                const selected = (selections[currentGroup.option_group_id] ?? []).includes(option.option_item_id);
                return (
                  <div key={option.option_item_id} className="v2-option-shell">
                    <button
                      type="button"
                      className={selected ? "v2-option-row selected" : "v2-option-row"}
                      onClick={() => void selectOption(currentGroup, option.option_item_id)}
                      disabled={busy || !option.available || breaksHalal || breaksVegan}
                    >
                      <span className={selected ? "radio checked" : "radio"} aria-hidden="true" />
                      <span className="labels">
                        <strong>{option.display_name || (language === "한국어" ? option.name_ko : option.name_en)}</strong>
                      </span>
                      <span className={option.price_delta ? "price strong" : "price"}>
                        {option.price_delta ? `+${won(option.price_delta)}` : journeyCopy.included}
                      </span>
                    </button>
                    {(breaksHalal || breaksVegan || needsVeganCheck) && (
                      <p className={breaksHalal || breaksVegan ? "v2-option-guidance conflict" : "v2-option-guidance"}>
                        {breaksHalal ? recommendationCopy.halalHelp : option.vegan_warning || recommendationCopy.veganChecks}
                      </p>
                    )}
                  </div>
                );
              })}
              {currentGroup.max_select > 1 && (
                <button
                  type="button"
                  className="v2-card-primary"
                  onClick={() => finishMultiSelect(currentGroup)}
                  disabled={busy || (selections[currentGroup.option_group_id] ?? []).length < currentGroup.min_select}
                >
                  {v2.doneOptions}
                </button>
              )}
            </div>
          </article>
          <div className="v2-inline-replies no-indent">
            <button type="button" className="v2-quick-reply brand" onClick={() => void applyDefaultsForRest()} disabled={busy}>
              {v2.useDefaults}
            </button>
            <button type="button" className="v2-quick-reply" onClick={onClose} disabled={busy}>
              {v2.changeMenu}
            </button>
          </div>
        </>
      )}

      {phase === "note" && (
        <article className="v2-order-card">
          <div className="v2-order-body">
            <div className="v2-order-heading">
              <h3>{journeyCopy.howSay}</h3>
              <p>{journeyCopy.restaurantNote}</p>
            </div>
            <p className="v2-card-help">{v2.restaurantNoteHelp}</p>
            <textarea
              className="v2-note-input"
              value={note}
              onChange={(event) => { setNote(event.target.value); setNoteTouched(true); setNoteTranslation(null); setError(""); }}
            />
            {noteTranslation?.status !== "FAILED" && (
              <button type="button" className="v2-card-secondary" onClick={() => void translateNote()} disabled={busy || !note.trim()}>
                {busy ? v2.translatingNote : v2.translateNote}
              </button>
            )}
            {noteTranslation?.status === "SUCCEEDED" && (
              <div className="v2-translation-preview" aria-live="polite">
                <small>{v2.koreanTranslation}</small>
                <strong>{noteTranslation.korean_text}</strong>
                <p>{v2.backTranslation}: {noteTranslation.back_translation}</p>
              </div>
            )}
            {noteTranslation?.status === "FAILED" && (
              <div className="v2-translation-fallback" role="status">
                <button type="button" className="v2-card-secondary" onClick={() => void translateNote()} disabled={busy}>
                  {v2.retryTranslation}
                </button>
                <button type="button" className="v2-card-secondary" onClick={() => void addWithoutRestaurantNote()} disabled={busy}>
                  {v2.addWithoutNote}
                </button>
              </div>
            )}
            <button
              type="button"
              className="v2-card-primary"
              onClick={() => void addToCart()}
              disabled={busy || Boolean(note.trim() && (noteTranslation?.status !== "SUCCEEDED" || noteTranslation.source_text !== note))}
            >
              {copy.addCart}
            </button>
          </div>
        </article>
      )}

      {phase === "more" && cart && (
        <>
          <article className="v2-order-card">
            <div className="v2-order-body">
              <div className="v2-order-heading">
                <h3>{copy.moreQuestion}</h3>
                <p>{copy.moreDescription}</p>
              </div>
            </div>
          </article>
          <div className="v2-inline-replies no-indent">
            <button type="button" className="v2-quick-reply brand" onClick={() => void browseThisRestaurant()} disabled={busy}>
              {copy.yesMore}
            </button>
            <button type="button" className="v2-quick-reply" onClick={() => setPhase("delivery")} disabled={busy}>
              {copy.noDelivery}
            </button>
          </div>
        </>
      )}

      {phase === "browse" && (
        <article className="v2-order-card">
          <div className="v2-order-body">
            <div className="v2-order-heading">
              <h3>{copy.moreFrom} · {merchantName(activeMenu.merchant_name, language)}</h3>
              <p>{copy.swipeMore}</p>
            </div>
            <div
              className="v2-merchant-menu-carousel"
              onScroll={(event) => {
                const element = event.currentTarget;
                if (nextMenuCursor && element.scrollWidth - element.scrollLeft - element.clientWidth < 180) {
                  void loadMerchantMenus(nextMenuCursor);
                }
              }}
            >
              {merchantMenus.map((item) => (
                <article className="v2-alimtalk-card compact" key={item.menu.menu_id}>
                  <img className="v2-card-hero" src="/figma/menu-hero.png" alt="" />
                  <div className="v2-card-body">
                    <div className="v2-card-title-row">
                      <div>
                        <h4>{item.localized_title || menuName(item.menu, language)}</h4>
                        {item.localized_subtitle && item.localized_subtitle !== item.localized_title && (
                          <small className="v2-card-subtitle">{item.localized_subtitle}</small>
                        )}
                        <p>{merchantName(item.menu.merchant_name, language)}</p>
                        {Boolean(item.menu.minimum_order_amount) && (
                          <small>{minimumOrderLabel} {won(item.menu.minimum_order_amount!)}</small>
                        )}
                      </div>
                      <strong>{won(item.menu.price)}</strong>
                    </div>
                    <p className="v2-card-yobi"><span>{v2.yobiLabel}</span> {item.yobi_short_explanation || dynamicCopy.catalogDescription}</p>
                    {item.source_description && <p className="v2-card-yogiyo"><span>{v2.yogiyoLabel}</span> {item.source_description}</p>}
                    <button type="button" className="v2-card-primary" onClick={() => chooseAdditionalMenu(item)} disabled={busy}>
                      {v2.chooseThisMenu}
                    </button>
                  </div>
                </article>
              ))}
            </div>
            {loadingMoreMenus && <p className="v2-status" role="status">{journeyCopy.loading}</p>}
            <button type="button" className="v2-card-secondary" onClick={() => setPhase("delivery")} disabled={busy}>
              {copy.noMore}
            </button>
          </div>
        </article>
      )}

      {phase === "delivery" && (
        <article className="v2-order-card">
          <div className="v2-order-body">
            <div className="v2-order-heading">
              <h3>{journeyCopy.handoffQuestion}</h3>
              <p>{copy.handoff}</p>
            </div>
            <div className="v2-option-row selected as-static">
              <span className="radio checked" aria-hidden="true" />
              <span className="labels">
                <strong>{journeyCopy.hotelFrontDesk}</strong>
                <small>{journeyCopy.noBellCutlery}</small>
              </span>
            </div>
            <div className="v2-translation-preview">
              <small>{journeyCopy.messageCourier}</small>
              <strong>호텔 프런트에 맡겨 주세요. 일회용 수저와 포크는 필요 없습니다.</strong>
            </div>
            <button type="button" className="v2-card-primary" onClick={() => void saveDelivery()} disabled={busy}>
              {copy.confirmDelivery}
            </button>
          </div>
        </article>
      )}

      {phase === "review" && cart && (
        <>
          <article className="v2-order-card" data-testid="cart-review">
            <div className="v2-card-strip">
              <span>{v2.orderReady}</span>
              <span>{groups.length > 0 ? `${groups.length} / ${groups.length}` : ""}</span>
            </div>
            <div className="v2-order-body">
              <div className="v2-review-label-row">
                <span>{v2.deliverTo}</span>
                <button type="button" onClick={changeAddress} disabled={busy}>{v2.editChip}</button>
              </div>
              <p className="v2-review-address">{addressSummary}</p>
              <div className="v2-divider" />
              <div className="v2-review-label-row">
                <span>{v2.yourMenu}</span>
                <button type="button" onClick={beginOptionEdit} disabled={busy}>
                  {v2.editChip}
                </button>
              </div>
              {cart.items.map((item) => {
                const displayedItemName = item.display_name || (language === "한국어" ? item.menu_name_ko : item.menu_name);
                return (
                  <div className="v2-cart-line" key={item.cart_item_id}>
                    <div className="copy">
                      <strong>{displayedItemName}</strong>
                      <small>{item.options.map((option) => localizedOptionNames.get(option.option_item_id) || option.display_name || (language === "한국어" ? option.name_ko : option.name_en)).join(" · ") || journeyCopy.included}</small>
                    </div>
                    <div className="controls">
                      <div className="v2-stepper" aria-label={`${journeyCopy.quantity}: ${displayedItemName}`}>
                        <button type="button" aria-label={journeyCopy.decrease} onClick={() => void changeQuantity(item.cart_item_id, item.quantity - 1)} disabled={busy || item.quantity <= 1}>−</button>
                        <span>{item.quantity}</span>
                        <button type="button" aria-label={journeyCopy.increase} onClick={() => void changeQuantity(item.cart_item_id, item.quantity + 1)} disabled={busy || item.quantity >= 10}>+</button>
                      </div>
                      <strong>{won(item.line_total)}</strong>
                      <button type="button" className="remove" aria-label={`${journeyCopy.remove}: ${displayedItemName}`} onClick={() => void removeItem(item.cart_item_id)} disabled={busy}>×</button>
                    </div>
                  </div>
                );
              })}
              <div className="v2-divider" />
              <div className="v2-price-row"><span>{v2.subtotal}</span><strong>{won(cart.subtotal)}</strong></div>
              <div className="v2-price-row"><span>{copy.delivery}</span><strong>{won(cart.delivery_fee)}</strong></div>
              <div className="v2-divider" />
              <div className="v2-price-row total">
                <span>{v2.totalEstimated}</span>
                <strong>{won(cart.total_price)}</strong>
              </div>
              {cart.minimum_order_amount != null && cart.missing_slots.includes("minimum_order_amount") && (
                <p className="v2-option-guidance conflict">
                  {journeyCopy.restaurantMinimum}: {won(cart.subtotal)} / {won(cart.minimum_order_amount)}
                  {cart.minimum_order_shortfall ? ` · ${journeyCopy.add} ${won(cart.minimum_order_shortfall)}` : ""}
                </p>
              )}
              <button
                type="button"
                className="v2-card-primary"
                onClick={() => void proceedToHandoff()}
                disabled={busy || !cart.ready_to_checkout}
              >
                {v2.prepareOrder(won(cart.total_price))}
              </button>
            </div>
          </article>
          <div className="v2-inline-replies no-indent">
            <button type="button" className="v2-quick-reply" onClick={changeAddress} disabled={busy}>{v2.changeAddress}</button>
            <button type="button" className="v2-quick-reply" onClick={beginOptionEdit} disabled={busy}>
              {v2.changeOptions}
            </button>
            <button type="button" className="v2-quick-reply" onClick={onClose} disabled={busy}>{v2.startOver}</button>
          </div>
        </>
      )}
      {error && <p className="v2-error" role="alert">{error}</p>}
    </section>
  );
}
