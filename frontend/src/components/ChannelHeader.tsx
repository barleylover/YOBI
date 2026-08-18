import { ArrowLeft } from "lucide-react";

interface ChannelHeaderProps {
  subtitle: string;
  backLabel: string;
  cartLabel: string;
  cartQuantity: number;
  cartDisabled?: boolean;
  onBack: () => void;
  onCart: () => void;
}

export function ChannelHeader({
  subtitle,
  backLabel,
  cartLabel,
  cartQuantity,
  cartDisabled = false,
  onBack,
  onCart,
}: ChannelHeaderProps) {
  return (
    <header className="yv2-channel-header">
      <button className="yv2-icon-button" type="button" aria-label={backLabel} onClick={onBack}>
        <ArrowLeft size={20} strokeWidth={2.25} />
      </button>
      <div className="yv2-channel-identity">
        <div><strong>YOBI</strong><img src="/figma-yobi-v2/recommendation-icon-06.svg" alt="" /></div>
        <span>{subtitle}</span>
      </div>
      <button
        className="yv2-cart-button"
        type="button"
        aria-label={cartLabel}
        onClick={onCart}
        disabled={cartDisabled}
      >
        <span className="yv2-cart-glyph" aria-hidden="true"><i /></span>
        {cartQuantity > 0 && <span className="yv2-cart-count">{cartQuantity}</span>}
      </button>
    </header>
  );
}
