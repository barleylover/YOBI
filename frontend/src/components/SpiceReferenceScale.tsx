import type {
  SpiceReferenceCountry,
  SpiceReferenceGroup,
} from "../types";
import type { RecommendationCopy } from "../lib/recommendationI18n";

interface Props {
  value: 1 | 2 | 3 | 4 | 5;
  country: SpiceReferenceCountry;
  references: SpiceReferenceGroup[];
  copy: RecommendationCopy;
  disabled?: boolean;
  onChange: (level: 1 | 2 | 3 | 4 | 5) => void;
  onCountryChange: (country: SpiceReferenceCountry) => void;
}

export function SpiceReferenceScale({
  value,
  country,
  references,
  copy,
  disabled = false,
  onChange,
  onCountryChange,
}: Props) {
  const active = references.find((reference) => reference.country === country) ?? references[0];
  return (
    <fieldset className="preference-spice">
      <legend>{copy.spiceTitle}</legend>
      <p>{copy.spiceHelp}</p>
      <div className="spice-reference-tabs" role="group" aria-label={copy.spiceTitle}>
        <button
          type="button"
          aria-pressed={country === "KR"}
          className={country === "KR" ? "active" : ""}
          disabled={disabled}
          onClick={() => onCountryChange("KR")}
        >
          {copy.koreanReference}
        </button>
        <button
          type="button"
          aria-pressed={country === "US"}
          className={country === "US" ? "active" : ""}
          disabled={disabled}
          onClick={() => onCountryChange("US")}
        >
          {copy.usReference}
        </button>
      </div>
      <div className="spice-reference-levels">
        {(active?.levels ?? []).map((item) => (
          <label className={value === item.level ? "spice-reference-choice selected" : "spice-reference-choice"} key={item.level}>
            <input
              type="radio"
              name="max-spice-level"
              value={item.level}
              checked={value === item.level}
              disabled={disabled}
              onChange={() => onChange(item.level)}
            />
            <span className="spice-level-number">{item.level}</span>
            <span><strong>{item.label}</strong><small>{item.example}</small>{item.description && <em>{item.description}</em>}</span>
          </label>
        ))}
      </div>
      <strong className="spice-current-value">{copy.maxSpice(value)}</strong>
    </fieldset>
  );
}
