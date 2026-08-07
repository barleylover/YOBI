import { AlertTriangle, CheckCircle2, CircleHelp, GitCompareArrows } from "lucide-react";
import type { EvidenceStatus } from "../types";
import { useI18n } from "../lib/i18n";

export function EvidenceBadge({ status }: { status: EvidenceStatus }) {
  const { journeyCopy } = useI18n();
  const labels: Record<EvidenceStatus, string> = {
    VERIFIED: journeyCopy.verified,
    RISK_SIGNAL: journeyCopy.riskSignal,
    UNKNOWN: journeyCopy.notVerified,
    CONFLICTING: journeyCopy.conflicting,
  };
  const Icon =
    status === "VERIFIED"
      ? CheckCircle2
      : status === "RISK_SIGNAL"
        ? AlertTriangle
        : status === "CONFLICTING"
          ? GitCompareArrows
          : CircleHelp;
  return (
    <span className={`evidence-badge evidence-${status.toLowerCase()}`}>
      <Icon size={15} aria-hidden="true" />
      {labels[status]}
    </span>
  );
}
