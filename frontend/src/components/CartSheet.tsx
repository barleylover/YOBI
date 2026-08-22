import { useEffect, useState } from "react";
import { actionableError, api } from "../lib/api";
import { useSessionStore } from "../stores/session";
import type { CartPreview } from "../types";
import { BottomSheet } from "./BottomSheet";

interface Props {
  sessionId: string;
  open: boolean;
  language: string;
  locale: string;
  onClose: () => void;
  onCartChange: (cart: CartPreview) => void;
  onContinue?: () => void;
}

function cartCopy(language: string) {
  if (language === "한국어") {
    return {
      title: "장바구니",
      empty: "아직 장바구니에 담긴 메뉴가 없습니다.",
      loading: "장바구니를 불러오는 중입니다…",
      subtotal: "메뉴 금액",
      delivery: "배달비",
      total: "예상 합계",
      minimum: "최소 주문금액",
      add: "추가 필요",
      continue: "주문 계속하기",
      close: "닫기",
      remove: "삭제",
      failed: "장바구니를 불러오지 못했습니다.",
    };
  }
  if (language === "日本語") {
    return {
      title: "カート",
      empty: "カートにはまだメニューがありません。",
      loading: "カートを読み込んでいます…",
      subtotal: "小計",
      delivery: "配送料",
      total: "見積合計",
      minimum: "最低注文金額",
      add: "あと",
      continue: "注文を続ける",
      close: "閉じる",
      remove: "削除",
      failed: "カートを読み込めませんでした。",
    };
  }
  return {
    title: "Your cart",
    empty: "Your cart is empty.",
    loading: "Loading your cart…",
    subtotal: "Subtotal",
    delivery: "Delivery fee",
    total: "Estimated total",
    minimum: "Restaurant minimum",
    add: "Add",
    continue: "Continue your order",
    close: "Close",
    remove: "Remove",
    failed: "We couldn't load your cart.",
  };
}

export function CartSheet({
  sessionId,
  open,
  language,
  locale,
  onClose,
  onCartChange,
  onContinue,
}: Props) {
  const setCartQuantity = useSessionStore((state) => state.setCartQuantity);
  const [cart, setCart] = useState<CartPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const copy = cartCopy(language);
  const won = (value: number) => `₩${value.toLocaleString(locale)}`;

  function sync(next: CartPreview, notifyChange = true) {
    setCart(next);
    setCartQuantity(next.items.reduce((total, item) => total + item.quantity, 0));
    if (notifyChange) onCartChange(next);
  }

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api.getCart(sessionId, controller.signal)
      .then((next) => sync(next, false))
      .catch((cause) => {
        if (cause instanceof Error && cause.message === "REQUEST_ABORTED") return;
        setError(actionableError(cause, copy.failed, language));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // sync deliberately stays local so opening the sheet is the refresh boundary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, sessionId]);

  async function changeQuantity(cartItemId: string, quantity: number) {
    if (quantity < 1 || quantity > 10) return;
    setBusy(true);
    setError("");
    try {
      sync(await api.updateCartItem(sessionId, cartItemId, quantity));
    } catch (cause) {
      setError(actionableError(cause, copy.failed, language));
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(cartItemId: string) {
    setBusy(true);
    setError("");
    try {
      sync(await api.deleteCartItem(sessionId, cartItemId));
    } catch (cause) {
      setError(actionableError(cause, copy.failed, language));
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet open={open} labelledBy="cart-sheet-title" onClose={onClose}>
      <div className="v2-explanation-sheet v2-cart-sheet">
        <header><h2 id="cart-sheet-title">{copy.title}</h2></header>
        <div className="v2-explanation-scroll">
          {loading && <p className="v2-status" role="status">{copy.loading}</p>}
          {error && <p className="v2-error" role="alert">{error}</p>}
          {!loading && cart?.items.length === 0 && <p className="v2-status">{copy.empty}</p>}
          {cart?.items.map((item) => {
            const name = item.display_name || (language === "한국어" ? item.menu_name_ko : item.menu_name);
            return (
              <div className="v2-cart-line" key={item.cart_item_id}>
                <div className="copy">
                  <strong>{name}</strong>
                  <small>{item.options.map((option) => option.display_name || (language === "한국어" ? option.name_ko : option.name_en)).join(" · ")}</small>
                </div>
                <div className="controls">
                  <div className="v2-stepper" aria-label={name}>
                    <button type="button" aria-label={`Decrease ${name}`} onClick={() => void changeQuantity(item.cart_item_id, item.quantity - 1)} disabled={busy || item.quantity <= 1}>−</button>
                    <span>{item.quantity}</span>
                    <button type="button" aria-label={`Increase ${name}`} onClick={() => void changeQuantity(item.cart_item_id, item.quantity + 1)} disabled={busy || item.quantity >= 10}>+</button>
                  </div>
                  <strong>{won(item.line_total)}</strong>
                  <button type="button" className="remove" aria-label={`${copy.remove}: ${name}`} onClick={() => void removeItem(item.cart_item_id)} disabled={busy}>×</button>
                </div>
              </div>
            );
          })}
          {cart && cart.items.length > 0 && (
            <>
              <div className="v2-divider" />
              <div className="v2-price-row"><span>{copy.subtotal}</span><strong>{won(cart.subtotal)}</strong></div>
              <div className="v2-price-row"><span>{copy.delivery}</span><strong>{won(cart.delivery_fee)}</strong></div>
              <div className="v2-price-row total"><span>{copy.total}</span><strong>{won(cart.total_price)}</strong></div>
              {cart.minimum_order_shortfall > 0 && (
                <p className="v2-option-guidance conflict">
                  {copy.minimum}: {won(cart.subtotal)} / {won(cart.minimum_order_amount)} · {copy.add} {won(cart.minimum_order_shortfall)}
                </p>
              )}
            </>
          )}
        </div>
        {cart && cart.items.length > 0 && onContinue && (
          <button type="button" className="v2-card-primary" onClick={onContinue}>{copy.continue}</button>
        )}
        <button type="button" className="v2-text-button" onClick={onClose}>{copy.close}</button>
      </div>
    </BottomSheet>
  );
}
