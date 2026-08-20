import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  Profile,
  RecommendationBatchV2,
  RecommendationCriteriaV2,
  RecommendationPhase,
  RecommendationRequestV2,
  Session,
} from "../types";

export function emptyCriteria(profile?: Profile | null): RecommendationCriteriaV2 {
  return {
    schema_version: "3",
    cuisine_origins: [],
    flavors: [],
    main_ingredients: [],
    food_forms: [],
    temperatures: [],
    price_bands: [],
    price_range_krw: { min: 8_000, max: 25_000 },
    textures: [],
    cooking_methods: [],
    dietary_filters: {
      halal_certified_only: false,
      vegan: false,
    },
    max_spice_level: 3,
    spice_preference: "SIMILAR",
    spice_reference_country: (profile?.country_code ?? (profile?.preferred_language === "한국어" ? "KR" : "US")) as RecommendationCriteriaV2["spice_reference_country"],
  };
}

interface SessionState {
  draftLanguage: string;
  draftCountry: string;
  profile: Profile | null;
  session: Session | null;
  addressRefId: string;
  addressSummary: string;
  cartQuantity: number;
  draftCriteria: RecommendationCriteriaV2;
  committedCriteria: RecommendationCriteriaV2 | null;
  criteriaVersion: number;
  recommendationPhase: RecommendationPhase;
  pendingRecommendation: RecommendationRequestV2 | null;
  latestRecommendation: RecommendationBatchV2 | null;
  setLocaleDraft: (language: string, country: string) => void;
  setContext: (profile: Profile, session: Session) => void;
  updateProfile: (profile: Profile) => void;
  setDeliveryAddress: (addressRefId: string, addressSummary: string) => void;
  setCartQuantity: (quantity: number) => void;
  setDraftCriteria: (criteria: RecommendationCriteriaV2) => void;
  commitCriteria: (criteria: RecommendationCriteriaV2, criteriaVersion: number) => void;
  setRecommendationPhase: (phase: RecommendationPhase) => void;
  setPendingRecommendation: (request: RecommendationRequestV2 | null) => void;
  setLatestRecommendation: (result: RecommendationBatchV2 | null) => void;
  resetRecommendation: () => void;
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
      draftCriteria: emptyCriteria(),
      committedCriteria: null,
      criteriaVersion: 0,
      recommendationPhase: "SELECTING",
      pendingRecommendation: null,
      latestRecommendation: null,
      setLocaleDraft: (draftLanguage, draftCountry) => set({ draftLanguage, draftCountry }),
      setContext: (profile, session) => set({
        profile,
        session,
        addressRefId: "",
        addressSummary: "",
        cartQuantity: 0,
        draftCriteria: emptyCriteria(profile),
        committedCriteria: null,
        criteriaVersion: 0,
        recommendationPhase: "SELECTING",
        pendingRecommendation: null,
        latestRecommendation: null,
      }),
      updateProfile: (profile) => set({ profile }),
      setDeliveryAddress: (addressRefId, addressSummary) => set({ addressRefId, addressSummary }),
      setCartQuantity: (cartQuantity) => set({ cartQuantity }),
      setDraftCriteria: (draftCriteria) => set({ draftCriteria }),
      commitCriteria: (committedCriteria, criteriaVersion) => set({
        committedCriteria,
        draftCriteria: committedCriteria,
        criteriaVersion,
      }),
      setRecommendationPhase: (recommendationPhase) => set({ recommendationPhase }),
      setPendingRecommendation: (pendingRecommendation) => set({ pendingRecommendation }),
      setLatestRecommendation: (latestRecommendation) => set({ latestRecommendation }),
      resetRecommendation: () => set((state) => ({
        draftCriteria: state.committedCriteria ?? state.draftCriteria,
        recommendationPhase: "SELECTING",
        pendingRecommendation: null,
      })),
      clear: () => set({
        profile: null,
        session: null,
        addressRefId: "",
        addressSummary: "",
        cartQuantity: 0,
        draftCriteria: emptyCriteria(),
        committedCriteria: null,
        criteriaVersion: 0,
        recommendationPhase: "SELECTING",
        pendingRecommendation: null,
        latestRecommendation: null,
      }),
    }),
    { name: "yobi-demo-session", storage: { getItem: (key) => {
      const value = sessionStorage.getItem(key);
      return value ? JSON.parse(value) : null;
    }, setItem: (key, value) => sessionStorage.setItem(key, JSON.stringify(value)), removeItem: (key) => sessionStorage.removeItem(key) } },
  ),
);
