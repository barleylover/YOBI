import { asEffectiveLanguage } from "./locale";
import type { FoodRankingSort, MenuSummary } from "../types";

export interface KpopDemoDish {
  dishName: "Gimbap" | "Tteokbokki" | "Hotteok" | "Naengmyeon" | "Eomuk";
  screenLabel: string;
  story: string;
  foodNote: string;
}

export const KPOP_DEMO_DISHES: readonly KpopDemoDish[] = [
  {
    dishName: "Gimbap",
    screenLabel: "Pre-show carb loading",
    story: "Seaweed rice rolls appear in HUNTR/X's pre-show food spread.",
    foodNote: "Seasoned rice and fillings rolled in dried seaweed, sliced into easy-to-share bites.",
  },
  {
    dishName: "Tteokbokki",
    screenLabel: "Pre-show carb loading",
    story: "The team also fuels up with Korea's iconic simmered rice cakes.",
    foodNote: "Chewy rice cakes are commonly served in a glossy, spicy-sweet sauce.",
  },
  {
    dishName: "Hotteok",
    screenLabel: "Sweet street-food break",
    story: "Hotteok adds a warm, sweet note to the film's opening food spread.",
    foodNote: "A pan-fried pancake with a sweet filling, often brown sugar, cinnamon and seeds or nuts.",
  },
  {
    dishName: "Naengmyeon",
    screenLabel: "Cooling noodle pick",
    story: "Naengmyeon is one of the Korean dishes packed into HUNTR/X's pre-show feast.",
    foodNote: "Thin, springy noodles served cold, usually in chilled broth or with a spicy mixed sauce.",
  },
  {
    dishName: "Eomuk",
    screenLabel: "Closest catalog match",
    story: "The film shows eomukguk, or fish-cake soup; YOBI maps it to an available eomuk menu.",
    foodNote: "Eomuk is seasoned fish cake, often skewered or served in a light savory broth.",
  },
] as const;

const SORT_EXPLANATIONS: Record<FoodRankingSort, string> = {
  review_count: "Source review activity where available, with a stable demo signal for missing counts.",
  order_count: "A prepared order-interest signal for this demo—not live order volume.",
  korean_popularity: "A prepared Korea-interest signal for discovery—not a national popularity chart.",
};

const HANGUL = /[\uac00-\ud7a3]/;

export function rankingExplanation(sort: FoodRankingSort) {
  return SORT_EXPLANATIONS[sort];
}

export function englishDiscoveryMenu(menu: MenuSummary, dishName = "") {
  if (menu.localized_title?.trim()) return menu;
  if (menu.name_en?.trim() && !HANGUL.test(menu.name_en)) return menu;
  const title = dishName.trim() || "Available menu";
  return { ...menu, localized_title: title };
}

export function discoveryMenuForLanguage(menu: MenuSummary, dishName: string, language: string) {
  return asEffectiveLanguage(language) === "English"
    ? englishDiscoveryMenu(menu, dishName)
    : menu;
}
