export type HorizontalDirection = "ltr" | "rtl";

export function carouselDirection(element: HTMLElement): HorizontalDirection {
  const computedDirection = typeof window === "undefined"
    ? ""
    : window.getComputedStyle(element).direction;
  const inheritedDirection = element.closest<HTMLElement>("[dir]")?.dir
    || (typeof document === "undefined" ? "" : document.documentElement.dir);
  return (computedDirection || inheritedDirection) === "rtl" ? "rtl" : "ltr";
}

export function carouselStep(element: HTMLElement): number {
  const first = element.children.item(0);
  const second = element.children.item(1);
  if (first instanceof HTMLElement && second instanceof HTMLElement) {
    const measuredStep = Math.abs(
      second.getBoundingClientRect().left - first.getBoundingClientRect().left,
    );
    if (measuredStep > 0) return measuredStep;
  }
  return element.clientWidth;
}

export function carouselOffsetForIndex(element: HTMLElement, index: number): number {
  const distance = Math.max(0, index) * carouselStep(element);
  if (distance === 0) return 0;
  return carouselDirection(element) === "rtl" ? -distance : distance;
}

export function carouselIndexFromOffset(element: HTMLElement, maxIndex: number): number {
  const step = carouselStep(element);
  if (!step) return 0;
  return Math.max(0, Math.min(Math.round(Math.abs(element.scrollLeft) / step), maxIndex));
}

export function carouselDeltaForArrow(element: HTMLElement, key: string): number {
  if (key !== "ArrowLeft" && key !== "ArrowRight") return 0;
  const pointsToNext = carouselDirection(element) === "rtl" ? key === "ArrowLeft" : key === "ArrowRight";
  return pointsToNext ? 1 : -1;
}
