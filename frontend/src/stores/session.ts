import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Profile, Session } from "../types";

interface SessionState {
  draftLanguage: string;
  draftCountry: string;
  profile: Profile | null;
  session: Session | null;
  addressRefId: string;
  addressSummary: string;
  cartQuantity: number;
  setLocaleDraft: (language: string, country: string) => void;
  setContext: (profile: Profile, session: Session) => void;
  setDeliveryAddress: (addressRefId: string, addressSummary: string) => void;
  setCartQuantity: (quantity: number) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      draftLanguage: "English",
      draftCountry: "United States",
      profile: null,
      session: null,
      addressRefId: "",
      addressSummary: "",
      cartQuantity: 0,
      setLocaleDraft: (draftLanguage, draftCountry) => set({ draftLanguage, draftCountry }),
      setContext: (profile, session) => set({ profile, session, addressRefId: "", addressSummary: "", cartQuantity: 0 }),
      setDeliveryAddress: (addressRefId, addressSummary) => set({ addressRefId, addressSummary }),
      setCartQuantity: (cartQuantity) => set({ cartQuantity }),
      clear: () => set({ profile: null, session: null, addressRefId: "", addressSummary: "", cartQuantity: 0 }),
    }),
    { name: "yobi-demo-session", storage: { getItem: (key) => {
      const value = sessionStorage.getItem(key);
      return value ? JSON.parse(value) : null;
    }, setItem: (key, value) => sessionStorage.setItem(key, JSON.stringify(value)), removeItem: (key) => sessionStorage.removeItem(key) } },
  ),
);
