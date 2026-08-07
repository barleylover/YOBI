import { useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronRight, Languages, LockKeyhole, Minus, Plus, ShieldAlert, ShoppingBag, Trash2, Unlock } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import { useSessionStore } from "../stores/session";
import type { CartPreview, MenuSummary, OptionGroup } from "../types";
import { RichCard } from "./RichCard";
import { useI18n } from "../lib/i18n";
import { menuName } from "../lib/locale";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  addressRefId: string;
  dietaryRules: string[];
  onClose: () => void;
}

type Phase = "options" | "note" | "more" | "browse" | "delivery" | "review";

export function OrderFlowPanel({ sessionId, menu, addressRefId, dietaryRules, onClose }: Props) {
  const navigate = useNavigate();
  const setCartQuantity = useSessionStore((state) => state.setCartQuantity);
  const cartQuantity = useSessionStore((state) => state.cartQuantity);
  const { copy, dynamicCopy, journeyCopy, language } = useI18n();
  const [activeMenu, setActiveMenu] = useState(menu);
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [unlockedOptions, setUnlockedOptions] = useState<Set<string>>(() => new Set());
  const [note, setNote] = useState(journeyCopy.mildNote);
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [merchantMenus, setMerchantMenus] = useState<MenuSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const restoreCartOnMount = useRef(cartQuantity > 0);

  useEffect(() => {
    let active = true;
    setGroups([]);
    setGroupIndex(0);
    setSelections({});
    setUnlockedOptions(new Set());
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
        }
        restoreCartOnMount.current = false;
      })
      .catch((cause) => { if (active) setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry); });
    return () => { active = false; };
  }, [activeMenu.menu_id, journeyCopy.retry, language, sessionId, setCartQuantity]);

  useEffect(() => setActiveMenu(menu), [menu]);

  function syncCart(preview: CartPreview) {
    setCart(preview);
    setCartQuantity(preview.items.reduce((total, item) => total + item.quantity, 0));
  }

  const currentGroup = groups[groupIndex];
  const selectedOptionIds = useMemo(() => Object.values(selections), [selections]);

  function selectOption(group: OptionGroup, optionId: string) {
    setSelections((current) => ({ ...current, [group.option_group_id]: optionId }));
    if (groupIndex < groups.length - 1) setTimeout(() => setGroupIndex((value) => value + 1), 160);
    else setTimeout(() => setPhase("note"), 160);
  }

  function unlockOption(optionId: string) {
    setUnlockedOptions((current) => new Set(current).add(optionId));
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

  async function proceedToPayment() {
    setBusy(true);
    try {
      await api.confirmCart(sessionId);
      const checkout = await api.createCheckout(sessionId);
      navigate(`/pay/${checkout.checkout_id}`);
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
      if (preview.items.length === 0) setPhase("options");
    } catch (cause) {
      setError(language === "English" ? actionableError(cause, journeyCopy.retry) : journeyCopy.retry);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="order-flow" aria-label={copy.orderBuilder} data-testid="order-flow">
      <header>
        <div>
          <p className="eyebrow">{copy.orderBuilder}</p>
          <h3>{menuName(activeMenu, language)}</h3>
          <p>{activeMenu.merchant_name}</p>
        </div>
        <button className="text-button" onClick={onClose}>{copy.close}</button>
      </header>

      <div className="mini-progress" aria-label={copy.orderBuilder}>
        {(["options", "delivery", "review"] as const).map((step, index) => (
          <span className={phase === step || (step === "options" && ["note", "more", "browse"].includes(phase)) ? "active" : ""} key={step}>
            {index + 1}<small>{step === "options" ? copy.options : step === "delivery" ? copy.delivery : copy.review}</small>
          </span>
        ))}
      </div>

      {phase === "options" && currentGroup && (
        <div className="decision-panel" data-testid={`option-group-${currentGroup.option_group_id}`}>
          <p className="step-count">{groupIndex + 1} of {groups.length}</p>
          <h4>{language === "한국어" ? currentGroup.name_ko : currentGroup.name_en}</h4>
          <p>{language === "English" ? currentGroup.description : dynamicCopy.catalogDescription}</p>
          <div className="option-list">
            {currentGroup.items.map((option) => {
              const riskApplies = Boolean(option.dietary_conflict)
                && option.conflicting_rules.some((rule) => dietaryRules.includes(rule));
              const isLocked = riskApplies && !unlockedOptions.has(option.option_item_id);
              return <div className={isLocked ? "option-item-shell risk-locked" : "option-item-shell"} key={option.option_item_id}>
                <button
                  className={selections[currentGroup.option_group_id] === option.option_item_id ? "option-button selected" : "option-button"}
                  onClick={() => selectOption(currentGroup, option.option_item_id)}
                  disabled={!option.available || isLocked}
                  aria-describedby={riskApplies ? `risk-${option.option_item_id}` : undefined}
                >
                  <span><strong>{language === "한국어" ? option.name_ko : option.name_en}</strong>{language !== "한국어" && <small>{option.name_ko}</small>}</span>
                  <span>{option.price_delta ? `+₩${option.price_delta.toLocaleString()}` : journeyCopy.included}{isLocked ? <LockKeyhole size={17} /> : <ChevronRight size={17} />}</span>
                </button>
                {riskApplies && <div className="option-risk" id={`risk-${option.option_item_id}`}><ShieldAlert size={16} /><span><strong>{isLocked ? journeyCopy.blocked : journeyCopy.unlocked}</strong><small>{language === "English" ? option.dietary_conflict : dynamicCopy.riskUnknown}</small></span>{isLocked && <button type="button" onClick={() => unlockOption(option.option_item_id)}><Unlock size={14} /> {journeyCopy.unlock}</button>}</div>}
              </div>;
            })}
          </div>
        </div>
      )}

      {phase === "note" && (
        <div className="decision-panel">
          <p className="step-count">{journeyCopy.restaurantNote}</p>
          <h4>{journeyCopy.howSay}</h4>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} />
          <div className="translation-preview">
            <Languages size={18} />
            <div><small>{journeyCopy.messageRestaurant}</small><strong>최대한 맵지 않게 부탁드립니다.</strong><p>{journeyCopy.backTranslation}: {note}</p></div>
          </div>
          <button className="primary-button full" onClick={addToCart} disabled={busy}>
            <ShoppingBag size={18} /> {copy.addCart}
          </button>
        </div>
      )}

      {phase === "more" && cart && (
        <div className="decision-panel more-menu-panel">
          <p className="step-count">{copy.added}</p>
          <h4>{copy.moreQuestion}</h4>
          <p>{copy.moreDescription}</p>
          <div className="button-row">
            <button className="primary-button full" onClick={() => void browseThisRestaurant()} disabled={busy}>{copy.yesMore}</button>
            <button className="secondary-button full" onClick={() => setPhase("delivery")} disabled={busy}>{copy.noDelivery}</button>
          </div>
        </div>
      )}

      {phase === "browse" && (
        <div className="same-merchant-browser">
          <RichCard
            card={{
              type: "menu_recommendations",
              title: `${copy.moreFrom} · ${activeMenu.merchant_name}`,
              subtitle: copy.swipeMore,
              data: { menus: merchantMenus },
            }}
            onChooseMenu={chooseAdditionalMenu}
            onQuickReply={() => undefined}
          />
          <button className="secondary-button full" onClick={() => setPhase("delivery")}>{copy.noMore}</button>
        </div>
      )}

      {phase === "delivery" && (
        <div className="decision-panel">
          <p className="step-count">{copy.handoff}</p>
          <h4>{journeyCopy.handoffQuestion}</h4>
          <div className="delivery-choice selected"><Check size={18} /><span><strong>{journeyCopy.hotelFrontDesk}</strong><small>{journeyCopy.noBellCutlery}</small></span></div>
          <div className="translation-preview"><Languages size={18} /><div><small>{journeyCopy.messageCourier}</small><strong>호텔 프런트에 맡겨 주세요. 일회용 수저와 포크는 필요 없습니다.</strong></div></div>
          <button className="primary-button full" onClick={saveDelivery} disabled={busy}>{copy.confirmDelivery}</button>
        </div>
      )}

      {phase === "review" && cart && (
        <div className="decision-panel cart-review" data-testid="cart-review">
          <p className="step-count">{copy.finalReview}</p>
          <h4>{journeyCopy.reviewTitle}</h4>
          {cart.items.map((item) => (
            <div className="cart-line" key={item.cart_item_id}>
              <div><strong>{language === "한국어" ? item.menu_name_ko : item.menu_name}</strong><small>{item.options.map((option) => language === "한국어" ? option.name_ko : option.name_en).join(", ")}</small></div>
              <div className="cart-line-actions">
                <div className="quantity-stepper" aria-label={`${journeyCopy.quantity}: ${item.menu_name}`}>
                  <button aria-label={journeyCopy.decrease} onClick={() => changeQuantity(item.cart_item_id, item.quantity - 1)} disabled={busy || item.quantity <= 1}><Minus size={14} /></button>
                  <span>{item.quantity}</span>
                  <button aria-label={journeyCopy.increase} onClick={() => changeQuantity(item.cart_item_id, item.quantity + 1)} disabled={busy || item.quantity >= 10}><Plus size={14} /></button>
                </div>
                <strong>₩{item.line_total.toLocaleString()}</strong>
                <button className="remove-cart-item" aria-label={`${journeyCopy.remove}: ${item.menu_name}`} onClick={() => removeItem(item.cart_item_id)} disabled={busy}><Trash2 size={15} /></button>
              </div>
            </div>
          ))}
          <div className="price-row"><span>{journeyCopy.items}</span><span>₩{cart.subtotal.toLocaleString()}</span></div>
          <div className="price-row"><span>{copy.delivery}</span><span>₩{cart.delivery_fee.toLocaleString()}</span></div>
          <div className="price-row total"><span>{journeyCopy.total}</span><strong>₩{cart.total_price.toLocaleString()}</strong></div>
          <section className="checkout-readiness" aria-label={copy.readyCheckout}>
            <h5>{copy.readyCheckout}</h5>
            <div className={!cart.missing_slots.includes("dietary_conflict") ? "readiness-pass" : "readiness-fail"}><Check size={16} /><span><strong>{journeyCopy.dietaryCheck}</strong><small>{cart.missing_slots.includes("dietary_conflict") ? journeyCopy.removeConflict : journeyCopy.noConflict}</small></span></div>
            <div className={!cart.missing_slots.includes("minimum_order_amount") ? "readiness-pass" : "readiness-fail"}><Check size={16} /><span><strong>{journeyCopy.restaurantMinimum}</strong><small>{cart.minimum_order_amount ? `₩${cart.subtotal.toLocaleString()} / ₩${cart.minimum_order_amount.toLocaleString()}${cart.minimum_order_shortfall ? ` · ${journeyCopy.add} ₩${cart.minimum_order_shortfall.toLocaleString()}` : ` · ${journeyCopy.met}`}` : journeyCopy.noMinimum}</small></span></div>
          </section>
          {(language === "English" ? cart.dietary_warnings : cart.dietary_warnings.length ? [dynamicCopy.riskUnknown] : []).map((warning) => <p className="risk-copy" key={warning}>{warning}</p>)}
          <button className="primary-button full large" onClick={proceedToPayment} disabled={busy || !cart.ready_to_checkout}>{copy.proceedPayment} <ChevronRight size={18} /></button>
          {!cart.ready_to_checkout && <p className="checkout-action">{journeyCopy.completeRequirements}</p>}
          <p className="demo-label">{copy.demoPayment}</p>
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
