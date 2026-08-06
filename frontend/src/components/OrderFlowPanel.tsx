import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { Check, ChevronRight, Hotel, ImageUp, Languages, ShoppingBag } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import type { AddressCandidate, CartPreview, MenuSummary, OptionGroup } from "../types";

interface Props {
  sessionId: string;
  menu: MenuSummary;
  onClose: () => void;
}

type Phase = "options" | "note" | "address" | "delivery" | "review";

export function OrderFlowPanel({ sessionId, menu, onClose }: Props) {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("options");
  const [groups, setGroups] = useState<OptionGroup[]>([]);
  const [groupIndex, setGroupIndex] = useState(0);
  const [selections, setSelections] = useState<Record<string, string>>({});
  const [note, setNote] = useState("As mild as possible, please.");
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [addressCandidates, setAddressCandidates] = useState<AddressCandidate[]>([]);
  const [addressRefId, setAddressRefId] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getOptions(menu.menu_id).then(setGroups).catch(() => setError("Could not load menu options."));
  }, [menu.menu_id]);

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
          <h4>Upload your booking screenshot</h4>
          <p>We extract a hotel and address candidate, then ask you to confirm it. The image is not stored.</p>
          <label className="upload-zone">
            <ImageUp size={28} />
            <strong>Choose booking image</strong>
            <span>PNG, JPEG or WebP · up to 8MB</span>
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={fileChanged} />
          </label>
          <button className="secondary-button full" onClick={useDemoBooking} disabled={busy}>Use stable demo booking image</button>
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
              <div><strong>{item.menu_name}</strong><small>Qty {item.quantity} · {item.options.map((option) => option.name_en).join(", ")}</small></div>
              <strong>₩{item.line_total.toLocaleString()}</strong>
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

