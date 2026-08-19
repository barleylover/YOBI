import { ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

interface Props {
  open: boolean;
  labelledBy?: string;
  onClose: () => void;
  children: ReactNode;
}

/** Figma "YOBI App v2" bottom sheet: scrim + rounded sheet with drag handle. */
export function BottomSheet({ open, labelledBy, onClose, children }: Props) {
  const sheetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => {
      sheetRef.current?.querySelector<HTMLElement>("button, [href], [tabindex]")?.focus();
    });
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div className="v2-sheet-root">
      <button type="button" className="v2-sheet-scrim" tabIndex={-1} aria-hidden="true" onClick={onClose} />
      <div ref={sheetRef} className="v2-sheet" role="dialog" aria-modal="true" aria-labelledby={labelledBy}>
        <div className="v2-sheet-handle" aria-hidden="true"><span /></div>
        {children}
      </div>
    </div>,
    document.body,
  );
}
