import { describe, expect, it } from "vitest";
import {
  demoHotelName,
  demoRoadAddress,
  localizeDemoAddressSummary,
  localizedVeganWarning,
  merchantName,
} from "../src/lib/locale";

describe("demo-facing Japanese localization", () => {
  it("keeps the established English names and addresses unchanged", () => {
    expect(merchantName("피자마루-약수점", "English")).toBe("Pizza Maru - Yaksu Branch");
    expect(demoRoadAddress("서울특별시 중구 을지로 21", "English")).toBe(
      "21 Eulji-ro, Jung-gu, Seoul",
    );
    expect(localizedVeganWarning("POSSIBLE_WITH_CHECKS", "English", "Original warning")).toBe(
      "Original warning",
    );
  });

  it("localizes known merchant, hotel, road address, and vegan guidance in Japanese", () => {
    expect(merchantName("피자마루-약수점", "日本語")).toBe("ピザマル・薬水店");
    expect(merchantName("Pizza Maru - Yaksu Branch", "日本語")).toBe("ピザマル・薬水店");
    expect(merchantName("Myeongdong Jjajang Workshop", "日本語")).toBe("明洞 チャジャン 工房");
    expect(demoHotelName("YOBI Myeongdong Hotel", "日本語")).toBe("YOBI明洞ホテル");
    expect(demoRoadAddress("서울특별시 중구 을지로 21", "日本語")).toBe(
      "ソウル特別市 中区 乙支路21",
    );
    expect(localizeDemoAddressSummary(
      "YOBI Myeongdong Hotel · 21 Eulji-ro, Jung-gu, Seoul",
      "日本語",
    )).toBe("YOBI明洞ホテル · ソウル特別市 中区 乙支路21");
    expect(localizedVeganWarning("POSSIBLE_WITH_CHECKS", "日本語", "English warning")).not.toContain(
      "English warning",
    );
  });
});
