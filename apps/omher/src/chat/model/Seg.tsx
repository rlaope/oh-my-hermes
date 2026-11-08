import "./model.css";

/** Small segmented control. The selected segment is gray (never the brand gradient). */
export function Seg({
  value,
  options,
  onChange,
  label,
  disabled,
  small,
  testId,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
  small?: boolean;
  testId?: string;
}) {
  return (
    <div className={`mseg${small ? " sm" : ""}`} role="radiogroup" aria-label={label} data-testid={testId}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            className={on ? "on" : undefined}
            disabled={disabled}
            onClick={() => !on && onChange(o.value)}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
