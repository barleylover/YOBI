import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Profile, Session } from "../types";

interface SessionState {
  profile: Profile | null;
  session: Session | null;
  setContext: (profile: Profile, session: Session) => void;
  clear: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      profile: null,
      session: null,
      setContext: (profile, session) => set({ profile, session }),
      clear: () => set({ profile: null, session: null }),
    }),
    { name: "yobi-demo-session", storage: { getItem: (key) => {
      const value = sessionStorage.getItem(key);
      return value ? JSON.parse(value) : null;
    }, setItem: (key, value) => sessionStorage.setItem(key, JSON.stringify(value)), removeItem: (key) => sessionStorage.removeItem(key) } },
  ),
);
