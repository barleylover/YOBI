import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { PostAddressNavigation } from "../src/components/PostAddressNavigation";
import { api } from "../src/lib/api";
import { getProductCopy } from "../src/lib/productI18n";
import type { MenuSummary } from "../src/types";

const menu: MenuSummary = {
  menu_id: "menu_discovery_1",
  merchant_id: "merchant_discovery_1",
  merchant_name: "YOBI Discovery Kitchen",
  name_en: "Gimbap discovery",
  name_ko: "김밥 디스커버리",
  category: "Gimbap",
  description: "Prepared demo menu.",
  cultural_description: "Rice and fillings wrapped in seaweed.",
  price: 9000,
  delivery_fee: 2000,
  eta_min: 20,
  eta_max: 30,
  spice_level: 1,
  serves_min: 1,
  serves_max: 1,
  dietary_summary: "",
  evidence_status: "VERIFIED",
  match_reasons: [],
  risk_hints: [],
  evidence_ids: [],
  grounded_claim_ids: [],
  grounded_passage_ids: [],
  is_synthetic: true,
};

describe("post-address discovery navigation", () => {
  beforeAll(() => {
    HTMLElement.prototype.scrollTo = vi.fn();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    document.documentElement.dir = "ltr";
    HTMLElement.prototype.scrollTo = vi.fn();
  });

  it("is collapsed by default and shows at most 20 server-ranked demo entries", async () => {
    const items = Array.from({ length: 23 }, (_, index) => ({
      position: index + 1,
      metric_label: "Demo reviews",
      metric_value: 100 - index,
      menu: { ...menu, menu_id: `menu_discovery_${index + 1}`, name_en: `Menu ${index + 1}` },
    }));
    const rankings = vi.spyOn(api, "getFoodRankings").mockResolvedValue({
      snapshot_id: "ranking_snapshot_1",
      demo_basis: "Deterministic prepared demo ranking.",
      sort: "review_count",
      items,
    });
    const onChoose = vi.fn();

    render(<PostAddressNavigation sessionId="session_1" language="English" locale="en-US" onChoose={onChoose} />);
    expect(screen.queryByRole("button", { name: "Food rankings" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open YOBI discoveries" }));
    fireEvent.click(screen.getByRole("button", { name: "Food rankings" }));

    expect(await screen.findByText("Deterministic prepared demo ranking.")).toBeInTheDocument();
    expect(document.querySelectorAll(".food-ranking-list > li")).toHaveLength(20);
    fireEvent.click(screen.getByRole("tab", { name: "Most ordered" }));
    await waitFor(() => expect(rankings).toHaveBeenLastCalledWith("session_1", "order_count", expect.any(AbortSignal)));
    fireEvent.click(screen.getAllByRole("button", { name: "Choose this menu" })[0]);
    await waitFor(() => expect(onChoose).toHaveBeenCalledWith(expect.objectContaining({ menu_id: "menu_discovery_1" }), "ranking_snapshot_1"));
  });

  it("uses the local K-Demon hero and a non-ranked single-card feature carousel", async () => {
    vi.spyOn(api, "getKpopDemonHuntersFeature").mockResolvedValue({
      snapshot_id: "feature_snapshot_1",
      items: [{ dish_name: "Gimbap", description: "An on-screen K-food feature.", menu }],
    });
    const onChoose = vi.fn();

    render(<PostAddressNavigation sessionId="session_1" language="English" locale="en-US" onChoose={onChoose} />);
    fireEvent.click(screen.getByRole("button", { name: "Open YOBI discoveries" }));
    fireEvent.click(screen.getByRole("button", { name: "K-Demon feature" }));

    const hero = await screen.findByRole("img", { name: /K-food on screen/i });
    expect(hero).toHaveAttribute("src", "/yobi-gimbap-feature-hero.png");
    expect(document.querySelector(".ranking-position")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Choose this menu" }));
    await waitFor(() => expect(onChoose).toHaveBeenCalledWith(menu, "feature_snapshot_1"));
  });

  it("traps keyboard focus in the discovery dialog, closes on Escape, and restores the toggle", async () => {
    vi.spyOn(api, "getFoodRankings").mockResolvedValue({
      snapshot_id: "ranking_snapshot_keyboard",
      demo_basis: "Keyboard demo ranking.",
      sort: "review_count",
      items: [{ position: 1, metric_label: "Demo reviews", metric_value: 9, menu }],
    });

    render(<PostAddressNavigation sessionId="session_1" language="English" locale="en-US" onChoose={vi.fn()} />);
    const toggle = screen.getByRole("button", { name: "Open YOBI discoveries" });
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Food rankings" }));
    const dialog = await screen.findByRole("dialog");
    const close = screen.getByRole("button", { name: "Close" });
    await waitFor(() => expect(close).toHaveFocus());

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(toggle).toHaveFocus());
  });

  it("keeps server metric labels from leaking English into Arabic navigation", async () => {
    const externalMenu = {
      ...menu,
      is_synthetic: false,
      cultural_description: "External catalog detail: crisp seaweed around seasoned rice.",
    };
    vi.spyOn(api, "getFoodRankings").mockResolvedValue({
      snapshot_id: "ranking_snapshot_ar",
      demo_basis: "English server demo basis",
      sort: "review_count",
      items: [{ position: 1, metric_label: "Demo reviews", metric_value: 9, menu: externalMenu }],
    });
    const copy = getProductCopy("العربية").navigation;

    render(<PostAddressNavigation sessionId="session_1" language="العربية" locale="ar" onChoose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: copy.expand }));
    fireEvent.click(screen.getByRole("button", { name: copy.foodRankings }));

    await screen.findByText((_, element) => element?.textContent?.startsWith(`${copy.reviews}:`) ?? false);
    expect(screen.getByText("External catalog detail: crisp seaweed around seasoned rice.")).toBeInTheDocument();
    expect(screen.queryByText(/Demo reviews|English server demo basis/)).not.toBeInTheDocument();
    expect(screen.queryByText(/اصطناعي|synthetic/i)).not.toBeInTheDocument();
  });

  it("shows the server K-Demon food description in Korean instead of generic profile copy", async () => {
    const externalMenu = { ...menu, is_synthetic: false };
    vi.spyOn(api, "getKpopDemonHuntersFeature").mockResolvedValue({
      snapshot_id: "feature_snapshot_ko_external",
      items: [{
        dish_name: "김밥",
        description: "작품 속 김밥은 양념한 밥과 여러 재료를 김으로 감싼 음식입니다.",
        menu: externalMenu,
      }],
    });
    const copy = getProductCopy("한국어").navigation;

    render(<PostAddressNavigation sessionId="session_1" language="한국어" locale="ko-KR" onChoose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: copy.expand }));
    fireEvent.click(screen.getByRole("button", { name: copy.feature }));

    expect(await screen.findByText("작품 속 김밥은 양념한 밥과 여러 재료를 김으로 감싼 음식입니다.")).toBeInTheDocument();
    expect(screen.queryByText(/합성 카탈로그|프로필과 배달 정보에 맞춘/)).not.toBeInTheDocument();
  });

  it("moves the Arabic RTL feature carousel one card with next, previous, and physical arrow keys", async () => {
    document.documentElement.dir = "rtl";
    const secondMenu = { ...menu, menu_id: "menu_discovery_2", name_en: "Tteokbokki", name_ko: "떡볶이" };
    vi.spyOn(api, "getKpopDemonHuntersFeature").mockResolvedValue({
      snapshot_id: "feature_snapshot_ar_rtl",
      items: [
        { dish_name: "Gimbap", description: "Seasoned rice wrapped in seaweed.", menu },
        { dish_name: "Tteokbokki", description: "Chewy rice cakes in a red sauce.", menu: secondMenu },
      ],
    });
    const productCopy = getProductCopy("العربية");
    const scrollTo = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
      this.scrollLeft = Number(options.left ?? 0);
    });
    HTMLElement.prototype.scrollTo = scrollTo as unknown as typeof HTMLElement.prototype.scrollTo;

    render(<PostAddressNavigation sessionId="session_1" language="العربية" locale="ar" onChoose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: productCopy.navigation.expand }));
    fireEvent.click(screen.getByRole("button", { name: productCopy.navigation.feature }));

    const carousel = await screen.findByRole("region", { name: productCopy.navigation.feature });
    Object.defineProperty(carousel, "clientWidth", { configurable: true, value: 390 });
    scrollTo.mockClear();

    fireEvent.click(screen.getByRole("button", { name: productCopy.recommendation.next }));
    expect(scrollTo).toHaveBeenLastCalledWith({ left: -390, behavior: "smooth" });
    expect(await screen.findByText("2 / 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: productCopy.recommendation.previous }));
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, behavior: "smooth" });
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();

    carousel.scrollLeft = -390;
    fireEvent.scroll(carousel);
    expect(await screen.findByText("2 / 2")).toBeInTheDocument();
    carousel.scrollLeft = 0;
    fireEvent.scroll(carousel);
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();

    carousel.focus();
    fireEvent.keyDown(carousel, { key: "ArrowLeft" });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: -390, behavior: "smooth" });
    expect(await screen.findByText("2 / 2")).toBeInTheDocument();
    fireEvent.keyDown(carousel, { key: "ArrowRight" });
    expect(scrollTo).toHaveBeenLastCalledWith({ left: 0, behavior: "smooth" });
    expect(await screen.findByText("1 / 2")).toBeInTheDocument();
  });
});
