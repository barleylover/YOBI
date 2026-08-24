import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreparingScreen } from "../src/components/PreparingScreen";
import { getRedesignCopy } from "../src/lib/redesignI18n";

describe("recommendation preparing screen", () => {
  afterEach(() => {
    cleanup();
  });

  it.each([
    ["English", "YOBI is finding dishes for YOU!", "Writing your recommendations"],
    ["한국어", "YOBI가 당신을 위한 메뉴를 찾고 있어요!", "YOBI가 당신을 위한 설명을 만들고 있어요!"],
    ["日本語", "YOBIがあなたのメニューを探しています！", "YOBIがあなたのために説明を作っています！"],
  ] as const)("keeps the %s headline aligned with the server phase", (language, finding, explaining) => {
    const v2 = getRedesignCopy(language);
    const { rerender } = render(<PreparingScreen v2={v2} phase="RETRIEVING" onCancel={vi.fn()} />);

    expect(screen.getByRole("heading", { name: finding })).toBeInTheDocument();
    expect(screen.getByText(v2.stageChecking).closest(".v2-preparing-stage")).toHaveClass("active");

    rerender(<PreparingScreen v2={v2} phase="GENERATING" onCancel={vi.fn()} />);
    expect(screen.getByRole("heading", { name: explaining })).toBeInTheDocument();
    expect(screen.getByText(v2.stageReading).closest(".v2-preparing-stage")).toHaveClass("active");
    expect(document.body.textContent).not.toMatch(/matching \d+ conditions|menus\./i);
  });

  it("offers a cancellable edit action", () => {
    const onCancel = vi.fn();
    render(<PreparingScreen v2={getRedesignCopy("English")} phase="GENERATING" onCancel={onCancel} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel and edit conditions" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
