import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Hotel, ImageUp, Languages, Minus, Plus, ShoppingBag, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { AddressCandidate, CartPreview, MenuSummary, OptionGroup } from "../types";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  onClose: () => void;
  onPhaseChange?: (phase: Phase) => void;
}

type Phase = "options" | "note" | "address" | "delivery" | "review";
type AddressMode = "upload" | "hotel" | "manual";

export function OrderFlowPanel({ sessionId, menu, onClose, onPhaseChange }: Props) {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [note, setNote] = useState("As mild as possible, please.");
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [addressCandidates, setAddressCandidates] = useState<AddressCandidate[]>([]);
  const [addressMode, setAddressMode] = useState<AddressMode>("upload");
  const [hotelQuery, setHotelQuery] = useState("YOBI Myeongdong Hotel");
  const [manualAddress, setManualAddress] = useState({
    hotel_name: "",
    road_address: "",
    postal_code: "",
    city: "Seoul",
    delivery_hint: "Please leave it at the hotel front desk.",
  });
  const [addressRefId, setAddressRefId] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getOptions(menu.menu_id).then(setGroups).catch(() => setError("Could not load menu options."));
  }, [menu.menu_id]);

  useEffect(() => {
    onPhaseChange?.(phase);
  }, [onPhaseChange, phase]);

  const currentGroup = groups[groupIndex];
  const selectedOptionIds = useMemo(() => Object.values(selections), [selections]);

  function selectOption(group: OptionGroup, optionId: string) {
    setSelections((current) => ({ ...current, [group.option_group_id]: optionId }));
    if (groupIndex < groups.length - 1) setTimeout(() => setGroupIndex((value) => value + 1), 160);
    else setTimeout(() => setPhase("note"), 160);
  }

  async function addToCart() {
    setBusy(true);
    try {
      const preview = await api.addCartItem(sessionId, menu.menu_id, selectedOptionIds, note);
      setCart(preview);
      setPhase("address");
    } catch {
      setError("The cart could not be updated. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const result = await api.uploadAddress(sessionId, file);
      setAddressCandidates(result.candidates);
      setNotice(result.notice);
    } catch {
      setError("That image could not be read. Use PNG, JPEG, or WebP under 8MB.");
    } finally {
      setBusy(false);
    }
  }

  async function useDemoBooking() {
    const response = await fetch("/demo-booking.png");
    const blob = await response.blob();
    await upload(new File([blob], "yobi-demo-booking.png", { type: "image/png" }));
  }

  async function searchHotel() {
    setBusy(true);
    setError("");
    try {
      const result = await api.resolveAddress(sessionId, hotelQuery);
      setAddressCandidates(result.candidates);
      setNotice(result.notice);
    } catch {
      setError("We could not match that hotel name. Enter the full road address instead.");
    } finally {
      setBusy(false);
    }
  }

  async function saveManualAddress() {
    setBusy(true);
    setError("");
    try {
      const result = await api.confirmManualAddress(sessionId, manualAddress);
      setAddressRefId(result.address_ref_id);
      setPhase("delivery");
    } catch {
      setError("Check the hotel name and road address before continuing.");
    } finally {
      setBusy(false);
    }
  }

  async function chooseAddress(candidate: AddressCandidate) {
    setBusy(true);
    try {
      const result = await api.confirmAddress(sessionId, candidate);
      setAddressRefId(result.address_ref_id);
      setPhase("delivery");
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
    } catch {
      setError("The final cart check failed. Review the required information and retry.");
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
    } catch {
      setError("The cart changed while we were reviewing it. Check the options and retry.");
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
    } catch {
      setError("That item could not be removed. Refresh the cart and retry.");
    } finally {
      setBusy(false);
    }
  }

  function fileChanged(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void upload(file);
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
        {(["options", "address", "review"] as const).map((step, index) => (
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
            {currentGroup.items.map((option) => (
              <button
                key={option.option_item_id}
                className={selections[currentGroup.option_group_id] === option.option_item_id ? "option-button selected" : "option-button"}
                onClick={() => selectOption(currentGroup, option.option_item_id)}
              >
                <span><strong>{option.name_en}</strong><small>{option.name_ko}</small></span>
                <span>{option.price_delta ? `+₩${option.price_delta.toLocaleString()}` : "Included"}<ChevronRight size={17} /></span>
                {option.dietary_conflict && <em>{option.dietary_conflict}</em>}
              </button>
            ))}
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

      {phase === "address" && (
        <div className="decision-panel">
          <p className="step-count">Delivery address</p>
          <h4>Where should we deliver?</h4>
          <p>Choose a booking screenshot, search a hotel name, or enter the road address yourself.</p>
          <div className="address-methods" role="tablist" aria-label="Address entry method">
            <button className={addressMode === "upload" ? "active" : ""} onClick={() => setAddressMode("upload")}>Booking image</button>
            <button className={addressMode === "hotel" ? "active" : ""} onClick={() => setAddressMode("hotel")}>Hotel name</button>
            <button className={addressMode === "manual" ? "active" : ""} onClick={() => setAddressMode("manual")}>Road address</button>
          </div>
          {addressMode === "upload" && (
            <>
              <label className="upload-zone">
                <ImageUp size={28} />
                <strong>Choose booking image</strong>
                <span>PNG, JPEG or WebP · up to 8MB</span>
                <input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} />
              </label>
              <button className="secondary-button full" onClick={useDemoBooking} disabled={busy}>Use stable demo booking image</button>
            </>
          )}
          {addressMode === "hotel" && (
            <div className="address-form">
              <label>Hotel or stay name
                <input value={hotelQuery} onChange={(event) => setHotelQuery(event.target.value)} placeholder="e.g. YOBI Myeongdong Hotel" />
              </label>
              <button className="primary-button full" onClick={searchHotel} disabled={busy || hotelQuery.trim().length < 2}>Find synthetic address</button>
            </div>
          )}
          {addressMode === "manual" && (
            <div className="address-form">
              <label>Hotel or stay name
                <input value={manualAddress.hotel_name} onChange={(event) => setManualAddress((value) => ({ ...value, hotel_name: event.target.value }))} />
              </label>
              <label>Road address
                <input value={manualAddress.road_address} onChange={(event) => setManualAddress((value) => ({ ...value, road_address: event.target.value }))} placeholder="Full Korean road address" />
              </label>
              <div className="address-form-row">
                <label>Postal code
                  <input value={manualAddress.postal_code} onChange={(event) => setManualAddress((value) => ({ ...value, postal_code: event.target.value }))} />
                </label>
                <label>City
                  <input value={manualAddress.city} onChange={(event) => setManualAddress((value) => ({ ...value, city: event.target.value }))} />
                </label>
              </div>
              <button className="primary-button full" onClick={saveManualAddress} disabled={busy || !manualAddress.hotel_name.trim() || manualAddress.road_address.trim().length < 3}>Use this address</button>
            </div>
          )}
          {notice && <p className="notice-copy">{notice}</p>}
          {addressCandidates.map((candidate) => (
            <article className="address-candidate" key={candidate.place_id}>
              <Hotel size={20} />
              <div><strong>{candidate.hotel_name}</strong><p>{candidate.road_address}</p><small>{Math.round(candidate.confidence * 100)}% extraction match · synthetic place</small></div>
              <button className="primary-button" onClick={() => chooseAddress(candidate)}>Confirm</button>
            </article>
          ))}
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
          <p className="risk-copy">Synthetic evidence only. Sauce seafood-free is verified in demo data; cross-contamination is not verified.</p>
          <button className="primary-button full large" onClick={proceedToPayment} disabled={busy}>Proceed to payment <ChevronRight size={18} /></button>
          <p className="demo-label">Demo payment — no real charge</p>
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
