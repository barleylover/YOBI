import { AlertTriangle, CheckCircle2, CircleHelp, GitCompareArrows } from "lucide-react";
import type { EvidenceStatus } from "../types";

const labels: Record<EvidenceStatus, string> = {
  VERIFIED: "Restaurant verified",
  RISK_SIGNAL: "Risk signal",
  UNKNOWN: "Not verified",
  CONFLICTING: "Conflicting information",
};

export function EvidenceBadge({ status }: { status: EvidenceStatus }) {
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

