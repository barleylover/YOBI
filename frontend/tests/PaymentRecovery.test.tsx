import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { api } from "../src/lib/api";
import { PaymentPage } from "../src/routes/PaymentPage";
import { useSessionStore } from "../src/stores/session";
import type { Profile, Session } from "../src/types";

const profile: Profile = {
  profile_id: "profile_payment_recovery",
  preferred_language: "English",
  nationality: "United States",
  religion_selection: "Prefer not to say",
  spice_tolerance: 1,
  dietary_rules: [],
  favorite_foods: [],
  age_band: "25-34",
  allergy_severity: "mild",
  consent_demo_data: true,
  remember_profile: false,
};

const session: Session = {
  session_id: "session_payment_recovery",
  profile_id: profile.profile_id,
  state: "ORDER_BUILDING",
  state_version: 4,
};

describe("PaymentPage stale checkout recovery", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
    useSessionStore.getState().clear();
  });

  it("returns the user to the existing session cart", async () => {
    useSessionStore.setState({ profile, session });
    vi.spyOn(api, "getCheckout").mockResolvedValue({
      checkout_id: "checkout_payment_recovery",
      status: "PENDING",
      amount: 12000,
      payment_method: "international_card",
      payment_url: "/pay/checkout_payment_recovery",
    });
    vi.spyOn(api, "paymentSuccess").mockRejectedValue(new Error("CHECKOUT_STALE"));

    render(
      <MemoryRouter initialEntries={["/pay/checkout_payment_recovery"]}>
        <Routes>
          <Route path="/pay/:checkoutId" element={<PaymentPage />} />
          <Route path="/chat/:sessionId" element={<div>Existing cart route</div>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^Pay / }));
    const recoveryLink = await screen.findByRole("link", { name: "Open cart" });
    expect(recoveryLink).toHaveAttribute("href", `/chat/${session.session_id}`);
    fireEvent.click(recoveryLink);
    expect(await screen.findByText("Existing cart route")).toBeInTheDocument();
  });
});
