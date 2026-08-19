import type { RedesignCopy } from "../lib/redesignI18n";

interface Props {
  v2: RedesignCopy;
  phase: "RETRIEVING" | "GENERATING" | "RESTORING";
  conditionsCount: number;
  eligibleMenus: number | null;
  subtitle?: string;
  onCancel: () => void;
}

export function PreparingScreen({ v2, phase, conditionsCount, eligibleMenus, subtitle, onCancel }: Props) {
  const stageIndex = phase === "GENERATING" ? 1 : 0;
  const stages = [v2.stageChecking, v2.stageReading, v2.stageRanking];
  return (
    <div className="v2-screen subtle v2-preparing">
      <div className="v2-preparing-body">
        <img src="/figma/logo-mark.svg" alt="" width={62} height={62} />
        <div className="v2-preparing-heading">
          <h1>{v2.findingTitle}</h1>
          <p>{subtitle ?? v2.matchingSummary(conditionsCount, eligibleMenus)}</p>
        </div>
        <section className="v2-preparing-card" aria-live="polite">
          {stages.map((stage, index) => {
            const state = index < stageIndex ? "done" : index === stageIndex ? "active" : "pending";
            return (
              <div className={`v2-preparing-stage ${state}`} key={stage}>
                {state === "done" && <span className="stage-icon done" aria-hidden="true" />}
                {state === "active" && <span className="stage-icon spinner" aria-hidden="true" />}
                {state === "pending" && <span className="stage-icon pending" aria-hidden="true" />}
                <p>{stage}</p>
              </div>
            );
          })}
          <div className="v2-preparing-track" aria-hidden="true">
            <span style={{ width: stageIndex === 0 ? "35%" : "72%" }} />
          </div>
          <p className="v2-preparing-caption">{v2.usuallyFewSeconds}</p>
        </section>
        <div className="v2-tip">
          <span aria-hidden="true">i</span>
          <p>{v2.preparingTip}</p>
        </div>
        <button type="button" className="v2-text-button" onClick={onCancel}>
          {v2.cancelAndEdit}
        </button>
      </div>
    </div>
  );
}
