import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CartSheet } from "../src/components/CartSheet";
import { api } from "../src/lib/api";
import { useSessionStore } from "../src/stores/session";
import type { CartPreview } from "../src/types";

const cart: CartPreview = {
  cart_id: "cart-sheet",
  version: 1,
  items: [{
    cart_item_id: "line-1",
    menu_id: "menu-1",
    merchant_id: "merchant-1",
    menu_name: "Gimbap",
    menu_name_ko: "김밥",
    quantity: 1,
    unit_price: 9_000,
    options: [],
    line_total: 9_000,
  }],
  subtotal: 9_000,
  delivery_fee: 2_000,
  total_price: 11_000,
  missing_slots: ["minimum_order_amount"],
  dietary_warnings: [],
  minimum_order_amount: 15_000,
  minimum_order_shortfall: 6_000,
  ready_to_checkout: false,
  confirmed: false,
};

describe("CartSheet", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    useSessionStore.getState().clear();
  });

  it("shows cart lines and lets the visitor change quantity or remove a menu", async () => {
    vi.spyOn(api, "getCart").mockResolvedValue(cart);
    const update = vi.spyOn(api, "updateCartItem").mockResolvedValue({
      ...cart,
      version: 2,
      items: [{ ...cart.items[0], quantity: 2, line_total: 18_000 }],
      subtotal: 18_000,
      total_price: 20_000,
      minimum_order_shortfall: 0,
    });
    const remove = vi.spyOn(api, "deleteCartItem").mockResolvedValue({
      ...cart,
      version: 3,
      items: [],
      subtotal: 0,
      total_price: 0,
    });
    const changed = vi.fn();

    render(
      <CartSheet
        sessionId="session-1"
        open
        language="English"
        locale="en-US"
        onClose={vi.fn()}
        onCartChange={changed}
      />,
    );

    expect(await screen.findByText("Gimbap")).toBeInTheDocument();
    expect(changed).not.toHaveBeenCalled();
    expect(screen.getByText(/Restaurant minimum: ₩9,000 \/ ₩15,000/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Increase Gimbap" }));
    await waitFor(() => expect(update).toHaveBeenCalledWith("session-1", "line-1", 2));
    expect(changed).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Remove: Gimbap" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("session-1", "line-1"));
    expect(await screen.findByText("Your cart is empty.")).toBeInTheDocument();
    expect(changed).toHaveBeenCalledTimes(2);
  });
});
