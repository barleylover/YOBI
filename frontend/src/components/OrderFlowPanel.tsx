import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useSessionStore } from "../stores/session";
import type { CartPreview, DietaryFiltersV2, MenuSummary, OptionGroup, OptionItem } from "../types";
import { useI18n } from "../lib/i18n";
import { asSupportedLanguage, menuName } from "../lib/locale";
import { getRecommendationCopy } from "../lib/recommendationI18n";
import { getRedesignCopy } from "../lib/redesignI18n";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  addressRefId: string;
  dietaryFilters?: DietaryFiltersV2;
  onClose: () => void;
  onOptionChange?: (
    menuId: string,
    optionGroupId: string,
    optionItemIds: string[],
    riskAcknowledged: boolean,
  ) => Promise<void>;
}

type Phase = "options" | "note" | "more" | "browse" | "delivery" | "review";

export function OrderFlowPanel({ sessionId, menu, addressRefId, dietaryFilters, onClose, onOptionChange }: Props) {
  const navigate = useNavigate();
  const setCartQuantity = useSessionStore((state) => state.setCartQuantity);
  const cartQuantity = useSessionStore((state) => state.cartQuantity);
  const addressSummary = useSessionStore((state) => state.addressSummary);
  const { copy, dynamicCopy, journeyCopy, language, locale } = useI18n();
  const recommendationCopy = getRecommendationCopy(language);
  const v2 = getRedesignCopy(asSupportedLanguage(language));
  const [activeMenu, setActiveMenu] = useState(menu);
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [note, setNote] = useState(journeyCopy.mildNote);
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [merchantMenus, setMerchantMenus] = useState<MenuSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const restoreCartOnMount = useRef(cartQuantity > 0);
  const transitionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    setGroups([]);
    setGroupIndex(0);
    setSelections({});
    setPhase("options");
    setCart(null);
    setError("");
    Promise.all([
      api.getOptions(activeMenu.menu_id),
      restoreCartOnMount.current ? api.getCart(sessionId) : Promise.resolve(null),
    ])
      .then(([result, restoredCart]) => {
        if (!active) return;
        setGroups(result);
        if (restoredCart?.items.length) {
          setCart(restoredCart);
          setCartQuantity(restoredCart.items.reduce((total, item) => total + item.quantity, 0));
          setPhase(restoredCart.missing_slots.includes("delivery_preferences") ? "delivery" : "review");
        } else if (result.length === 0) {
          setPhase("note");
        }
        restoreCartOnMount.current = false;
      })
      .catch((cause) => { if (active) setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry); });
    return () => {
      active = false;
      if (transitionTimer.current !== null) {
        clearTimeout(transitionTimer.current);
        transitionTimer.current = null;
      }
    };
  }, [activeMenu.menu_id, journeyCopy.retry, language, sessionId, setCartQuantity]);

  useEffect(() => setActiveMenu(menu), [menu]);

  function syncCart(preview: CartPreview) {
    setCart(preview);
    setCartQuantity(preview.items.reduce((total, item) => total + item.quantity, 0));
  }

  const currentGroup = groups[groupIndex];
  const selectedOptionIds = useMemo(() => Object.values(selections), [selections]);
  const selectedDelta = useMemo(() => groups.reduce((total, group) => {
    const optionId = selections[group.option_group_id];
    const option = group.items.find((item) => item.option_item_id === optionId);
    return total + (option?.price_delta ?? 0);
  }, 0), [groups, selections]);

  function optionConflicts(option: OptionItem) {
    const breaksHalal = Boolean(dietaryFilters?.halal_certified_only && option.halal_certification_preserved === false);
    const breaksVegan = Boolean(dietaryFilters?.vegan && option.vegan_status === "CONFLICT");
    const needsVeganCheck = Boolean(dietaryFilters?.vegan && option.vegan_status === "POSSIBLE_WITH_CHECKS");
    return { breaksHalal, breaksVegan, needsVeganCheck };
  }

  async function selectOption(group: OptionGroup, optionId: string) {
    setBusy(true);
    setError("");
    try {
      await onOptionChange?.(activeMenu.menu_id, group.option_group_id, [optionId], false);
      setSelections((current) => ({ ...current, [group.option_group_id]: optionId }));
      if (transitionTimer.current !== null) clearTimeout(transitionTimer.current);
      transitionTimer.current = setTimeout(() => {
        transitionTimer.current = null;
        if (groupIndex < groups.length - 1) setGroupIndex((value) => value + 1);
        else setPhase("note");
      }, 160);
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  async function applyDefaultsForRest() {
    setBusy(true);
    setError("");
    try {
      const next: Record<string, string> = { ...selections };
      for (let index = groupIndex; index < groups.length; index += 1) {
        const group = groups[index];
        if (next[group.option_group_id]) continue;
        const fallback = group.items.find((option) => {
          if (!option.available) return false;
          const { breaksHalal, breaksVegan } = optionConflicts(option);
          return !breaksHalal && !breaksVegan;
        });
        if (!fallback) continue;
        await onOptionChange?.(activeMenu.menu_id, group.option_group_id, [fallback.option_item_id], false);
        next[group.option_group_id] = fallback.option_item_id;
      }
      setSelections(next);
      setPhase("note");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  async function addToCart() {
    setBusy(true);
    try {
      const restaurantNote = note === journeyCopy.mildNote ? "As mild as possible, please." : note;
      const preview = await api.addCartItem(sessionId, activeMenu.menu_id, selectedOptionIds, restaurantNote);
      syncCart(preview);
      setPhase("more");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  async function browseThisRestaurant() {
    if (!cart) return;
    setBusy(true);
    setError("");
    try {
      const menus = await api.getMerchantMenus(
        sessionId,
        activeMenu.merchant_id,
        cart.items.map((item) => item.menu_id),
      );
      setMerchantMenus(menus);
      setPhase(menus.length ? "browse" : "delivery");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  function chooseAdditionalMenu(nextMenu: MenuSummary) {
    setActiveMenu(nextMenu);
    setMerchantMenus([]);
  }

  async function saveDelivery() {
    setBusy(true);
    try {
      const preview = await api.updateDelivery(sessionId, addressRefId);
      syncCart(preview);
      setPhase("review");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
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
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
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
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
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
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  function changeAddress() {
    navigate(`/profile?edit=1&returnTo=${encodeURIComponent(`/chat/${sessionId}`)}`);
  }

  const won = (value: number) => `₩${value.toLocaleString(locale)}`;

  return (
    <section className="v2-order-flow" aria-label={copy.orderBuilder} data-testid="order-flow">
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
                <h3>{language === "한국어" ? currentGroup.name_ko : currentGroup.name_en}</h3>
                <p>{v2.requiredTapOne}</p>
              </div>
              {currentGroup.items.map((option) => {
                const { breaksHalal, breaksVegan, needsVeganCheck } = optionConflicts(option);
                const selected = selections[currentGroup.option_group_id] === option.option_item_id;
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
                        <strong>{language === "한국어" ? option.name_ko : option.name_en}</strong>
                        {language !== "한국어" && <small>{option.name_ko}</small>}
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
            <textarea className="v2-note-input" value={note} onChange={(event) => setNote(event.target.value)} />
            <div className="v2-translation-preview">
              <small>{journeyCopy.messageRestaurant}</small>
              <strong>최대한 맵지 않게 부탁드립니다.</strong>
              <p>{journeyCopy.backTranslation}: {note}</p>
            </div>
            <button type="button" className="v2-card-primary" onClick={() => void addToCart()} disabled={busy}>
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
              <h3>{copy.moreFrom} · {activeMenu.merchant_name}</h3>
              <p>{copy.swipeMore}</p>
            </div>
            <div className="v2-merchant-menu-list">
              {merchantMenus.map((item) => (
                <button
                  type="button"
                  className="v2-option-row"
                  key={item.menu_id}
                  onClick={() => chooseAdditionalMenu(item)}
                  disabled={busy}
                >
                  <span className="labels">
                    <strong>{menuName(item, language)}</strong>
                    <small>{item.cultural_description || item.description || dynamicCopy.catalogDescription}</small>
                  </span>
                  <span className="price strong">{won(item.price)}</span>
                </button>
              ))}
            </div>
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
                <button type="button" onClick={() => { setGroupIndex(0); setPhase(groups.length ? "options" : "note"); }} disabled={busy}>
                  {v2.editChip}
                </button>
              </div>
              {cart.items.map((item) => (
                <div className="v2-cart-line" key={item.cart_item_id}>
                  <div className="copy">
                    <strong>{language === "한국어" ? item.menu_name_ko : item.menu_name}</strong>
                    <small>{item.options.map((option) => language === "한국어" ? option.name_ko : option.name_en).join(" · ") || journeyCopy.included}</small>
                  </div>
                  <div className="controls">
                    <div className="v2-stepper" aria-label={`${journeyCopy.quantity}: ${item.menu_name}`}>
                      <button type="button" aria-label={journeyCopy.decrease} onClick={() => void changeQuantity(item.cart_item_id, item.quantity - 1)} disabled={busy || item.quantity <= 1}>−</button>
                      <span>{item.quantity}</span>
                      <button type="button" aria-label={journeyCopy.increase} onClick={() => void changeQuantity(item.cart_item_id, item.quantity + 1)} disabled={busy || item.quantity >= 10}>+</button>
                    </div>
                    <strong>{won(item.line_total)}</strong>
                    <button type="button" className="remove" aria-label={`${journeyCopy.remove}: ${item.menu_name}`} onClick={() => void removeItem(item.cart_item_id)} disabled={busy}>×</button>
                  </div>
                </div>
              ))}
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
              <div className="v2-demo-warning">
                <span aria-hidden="true">!</span>
                <p>{v2.demoOrderWarning}</p>
              </div>
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
            <button type="button" className="v2-quick-reply" onClick={() => { setGroupIndex(0); setPhase(groups.length ? "options" : "note"); }} disabled={busy}>
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
