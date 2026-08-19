import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreparingScreen } from "../src/components/PreparingScreen";
import { getRedesignCopy } from "../src/lib/redesignI18n";

describe("recommendation preparing screen", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it.each([
    ["English", "YOBI is finding menus for YOU!", "YOBI is making an explanation for YOU!"],
    ["한국어", "YOBI가 당신을 위한 메뉴를 찾고 있어요!", "YOBI가 당신을 위한 설명을 만들고 있어요!"],
    ["日本語", "YOBIがあなたのメニューを探しています！", "YOBIがあなたのために説明を作っています！"],
  ] as const)("switches %s copy exactly after five seconds", (language, finding, explaining) => {
    vi.useFakeTimers();
    render(<PreparingScreen v2={getRedesignCopy(language)} phase="RETRIEVING" onCancel={vi.fn()} />);

    expect(screen.getByRole("heading", { name: finding })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(4_999));
    expect(screen.getByRole("heading", { name: finding })).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1));
    expect(screen.getByRole("heading", { name: explaining })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/matching \d+ conditions|menus\./i);
  });

  it("offers a cancellable edit action", () => {
    const onCancel = vi.fn();
    render(<PreparingScreen v2={getRedesignCopy("English")} phase="GENERATING" onCancel={onCancel} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel and edit conditions" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
