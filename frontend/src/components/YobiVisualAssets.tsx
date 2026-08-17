interface AssetProps {
  className?: string;
}

export function YobiLogoMark({ className = "" }: AssetProps) {
  return <img className={className} src="/figma-yobi/logo-mark.png" alt="" aria-hidden="true" />;
}

export function YobiBotAvatar({ className = "" }: AssetProps) {
  return <img className={className} src="/figma-yobi/bot-avatar.svg" alt="" aria-hidden="true" />;
}

export function YobiVerifiedBadge({ className = "" }: AssetProps) {
  return <img className={className} src="/figma-yobi/verified-badge.png" alt="" aria-hidden="true" />;
}

export const YOBI_FOOD_ILLUSTRATION = "/figma-yobi/food-illustration.png";
