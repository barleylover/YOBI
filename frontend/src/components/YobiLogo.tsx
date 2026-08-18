interface YobiLogoProps {
  compact?: boolean;
  showWordmark?: boolean;
}

const LOGO_MARK = "/figma-yobi-v2/onboarding-icon-01.svg";

export function YobiLogo({ compact = false, showWordmark = true }: YobiLogoProps) {
  return (
    <span className={compact ? "yv2-logo yv2-logo-compact" : "yv2-logo"} aria-label="YOBI">
      <img src={LOGO_MARK} alt="" />
      {showWordmark && <strong aria-hidden="true">YOBI</strong>}
    </span>
  );
}
