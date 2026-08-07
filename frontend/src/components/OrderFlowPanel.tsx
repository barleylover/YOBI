import { useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Languages, LockKeyhole, Minus, Plus, ShieldAlert, ShoppingBag, Trash2, Unlock } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { actionableError, api } from "../lib/api";
import type { CartPreview, MenuSummary, OptionGroup } from "../types";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  addressRefId: string;
  dietaryRules: string[];
  onClose: () => void;
}

type Phase = "options" | "note" | "delivery" | "review";

export function OrderFlowPanel({ sessionId, menu, addressRefId, dietaryRules, onClose }: Props) {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [unlockedOptions, setUnlockedOptions] = useState<Set<string>>(() => new Set());
  const [note, setNote] = useState("As mild as possible, please.");
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setGroups([]);
    setGroupIndex(0);
    setSelections({});
    setUnlockedOptions(new Set());
    setPhase("options");
    setCart(null);
    setError("");
    api.getOptions(menu.menu_id)
      .then((result) => { if (active) setGroups(result); })
      .catch((cause) => { if (active) setError(actionableError(cause, "Could not load menu options. Choose another menu and retry.")); });
    return () => { active = false; };
  }, [menu.menu_id]);

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
      const preview = await api.addCartItem(sessionId, menu.menu_id, selectedOptionIds, note);
      setCart(preview);
      setPhase("delivery");
    } catch (cause) {
      setError(actionableError(cause, "Review the selected options, then add the item again."));
    } finally {
      setBusy(false);
    }
  }

  async function saveDelivery() {
    setBusy(true);
    try {
      const preview = await api.updateDelivery(sessionId, addressRefId);
      setCart(preview);
      setPhase("review");
    } catch (cause) {
      setError(actionableError(cause, "Confirm the delivery handoff details again."));
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
      setError(actionableError(cause, "Review the highlighted checkout requirements and try again."));
    } finally {
      setBusy(false);
    }
  }

  async function changeQuantity(cartItemId: string, quantity: number) {
    if (quantity < 1 || quantity > 10) return;
    setBusy(true);
    setError("");
    try {
      setCart(await api.updateCartItem(sessionId, cartItemId, quantity));
    } catch (cause) {
      setError(actionableError(cause, "The cart changed. Review the options and quantity again."));
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(cartItemId: string) {
    setBusy(true);
    setError("");
    try {
      const preview = await api.deleteCartItem(sessionId, cartItemId);
      setCart(preview);
      if (preview.items.length === 0) setPhase("options");
    } catch (cause) {
      setError(actionableError(cause, "That item could not be removed. Refresh the cart and retry."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="order-flow" aria-label="Build your mock order" data-testid="order-flow">
      <header>
        <div>
          <p className="eyebrow">Order builder</p>
          <h3>{menu.name_en}</h3>
          <p>{menu.merchant_name}</p>
        </div>
        <button className="text-button" onClick={onClose}>Close</button>
      </header>

      <div className="mini-progress" aria-label="Order progress">
        {(["options", "delivery", "review"] as const).map((step, index) => (
          <span className={phase === step || (step === "options" && phase === "note") ? "active" : ""} key={step}>
            {index + 1}<small>{step}</small>
          </span>
        ))}
      </div>

      {phase === "options" && currentGroup && (
        <div className="decision-panel" data-testid={`option-group-${currentGroup.option_group_id}`}>
          <p className="step-count">{groupIndex + 1} of {groups.length}</p>
          <h4>{currentGroup.name_en}</h4>
          <p>{currentGroup.description}</p>
          <div className="option-list">
            {currentGroup.items.map((option) => {
              const riskApplies = Boolean(option.dietary_conflict) && dietaryRules.includes("shellfish_allergy");
              const isLocked = riskApplies && !unlockedOptions.has(option.option_item_id);
              return <div className={isLocked ? "option-item-shell risk-locked" : "option-item-shell"} key={option.option_item_id}>
                <button
                  className={selections[currentGroup.option_group_id] === option.option_item_id ? "option-button selected" : "option-button"}
                  onClick={() => selectOption(currentGroup, option.option_item_id)}
                  disabled={!option.available || isLocked}
                  aria-describedby={riskApplies ? `risk-${option.option_item_id}` : undefined}
                >
                  <span><strong>{option.name_en}</strong><small>{option.name_ko}</small></span>
                  <span>{option.price_delta ? `+₩${option.price_delta.toLocaleString()}` : "Included"}{isLocked ? <LockKeyhole size={17} /> : <ChevronRight size={17} />}</span>
                </button>
                {riskApplies && <div className="option-risk" id={`risk-${option.option_item_id}`}><ShieldAlert size={16} /><span><strong>{isLocked ? "Blocked for your dietary profile" : "Unlocked by you — server checks still apply"}</strong><small>{option.dietary_conflict}</small></span>{isLocked && <button type="button" onClick={() => unlockOption(option.option_item_id)}><Unlock size={14} /> Unlock option</button>}</div>}
              </div>;
            })}
          </div>
        </div>
      )}

      {phase === "note" && (
        <div className="decision-panel">
          <p className="step-count">Restaurant note</p>
          <h4>How should we say it?</h4>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} />
          <div className="translation-preview">
            <Languages size={18} />
            <div><small>Message to restaurant</small><strong>최대한 맵지 않게 부탁드립니다.</strong><p>Back translation: As mild as possible, please.</p></div>
          </div>
          <button className="primary-button full" onClick={addToCart} disabled={busy}>
            <ShoppingBag size={18} /> Add to mock cart
          </button>
        </div>
      )}

      {phase === "delivery" && (
        <div className="decision-panel">
          <p className="step-count">Handoff</p>
          <h4>Leave it at the front desk?</h4>
          <div className="delivery-choice selected"><Check size={18} /><span><strong>Hotel front desk</strong><small>No bell · no disposable cutlery</small></span></div>
          <div className="translation-preview"><Languages size={18} /><div><small>Message to courier</small><strong>호텔 프런트에 맡겨 주세요. 일회용 수저와 포크는 필요 없습니다.</strong></div></div>
          <button className="primary-button full" onClick={saveDelivery} disabled={busy}>Confirm delivery details</button>
        </div>
      )}

      {phase === "review" && cart && (
        <div className="decision-panel cart-review" data-testid="cart-review">
          <p className="step-count">Final review</p>
          <h4>Everything still matches.</h4>
          {cart.items.map((item) => (
            <div className="cart-line" key={item.cart_item_id}>
              <div><strong>{item.menu_name}</strong><small>{item.options.map((option) => option.name_en).join(", ")}</small></div>
              <div className="cart-line-actions">
                <div className="quantity-stepper" aria-label={`Quantity for ${item.menu_name}`}>
                  <button aria-label="Decrease quantity" onClick={() => changeQuantity(item.cart_item_id, item.quantity - 1)} disabled={busy || item.quantity <= 1}><Minus size={14} /></button>
                  <span>{item.quantity}</span>
                  <button aria-label="Increase quantity" onClick={() => changeQuantity(item.cart_item_id, item.quantity + 1)} disabled={busy || item.quantity >= 10}><Plus size={14} /></button>
                </div>
                <strong>₩{item.line_total.toLocaleString()}</strong>
                <button className="remove-cart-item" aria-label={`Remove ${item.menu_name}`} onClick={() => removeItem(item.cart_item_id)} disabled={busy}><Trash2 size={15} /></button>
              </div>
            </div>
          ))}
          <div className="price-row"><span>Items</span><span>₩{cart.subtotal.toLocaleString()}</span></div>
          <div className="price-row"><span>Delivery</span><span>₩{cart.delivery_fee.toLocaleString()}</span></div>
          <div className="price-row total"><span>Total</span><strong>₩{cart.total_price.toLocaleString()}</strong></div>
          <section className="checkout-readiness" aria-label="Checkout readiness">
            <h5>Ready to checkout</h5>
            <div className={!cart.missing_slots.includes("dietary_conflict") ? "readiness-pass" : "readiness-fail"}><Check size={16} /><span><strong>Dietary check</strong><small>{cart.missing_slots.includes("dietary_conflict") ? "Remove the conflicting item or option." : "No known hard conflict in the current cart."}</small></span></div>
            <div className={!cart.missing_slots.includes("minimum_order_amount") ? "readiness-pass" : "readiness-fail"}><Check size={16} /><span><strong>Restaurant minimum</strong><small>{cart.minimum_order_amount ? `₩${cart.subtotal.toLocaleString()} of ₩${cart.minimum_order_amount.toLocaleString()}${cart.minimum_order_shortfall ? ` · add ₩${cart.minimum_order_shortfall.toLocaleString()}` : " · met"}` : "No minimum available."}</small></span></div>
          </section>
          {cart.dietary_warnings.map((warning) => <p className="risk-copy" key={warning}>{warning}</p>)}
          <button className="primary-button full large" onClick={proceedToPayment} disabled={busy || !cart.ready_to_checkout}>Proceed to payment <ChevronRight size={18} /></button>
          {!cart.ready_to_checkout && <p className="checkout-action">Complete the highlighted requirements before payment.</p>}
          <p className="demo-label">Demo payment — no real charge</p>
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
