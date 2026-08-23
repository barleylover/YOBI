import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceBadge } from "../src/components/EvidenceBadge";

describe("EvidenceBadge", () => {
  it("keeps unknown evidence visually and textually distinct from verified", () => {
    const { rerender } = render(<EvidenceBadge status="UNKNOWN" />);
    expect(screen.getByText("Not verified")).toBeInTheDocument();

    rerender(<EvidenceBadge status="VERIFIED" />);
    expect(screen.getByText("Restaurant verified")).toBeInTheDocument();
    expect(screen.queryByText("Not verified")).not.toBeInTheDocument();
  });

  it("labels synthetic risk signals without claiming an allergy guarantee", () => {
    render(<EvidenceBadge status="RISK_SIGNAL" />);
    expect(screen.getByText("Risk signal")).toBeInTheDocument();
  });
});

