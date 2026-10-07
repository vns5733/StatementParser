import React from "react";

/**
 * One legend label, rendered identically by every chart.
 *
 * The active marker has to be applied inline rather than via a CSS class: the
 * labels already set `color` inline (they must, to override Recharts'
 * `inactiveColor`), and an inline declaration beats any class rule — so a
 * `.legend-item-active { color: ... }` would silently never show.
 */
export function legendLabel(
  /** The payload value, used to test whether this entry is the active one. */
  value: string,
  /** Optional display text; defaults to the value. */
  text?: string,
  isActive = false
) {
  return (
    <span
      style={{
        color: isActive ? "var(--accent-indigo)" : "var(--text-secondary)",
        fontWeight: isActive ? 700 : undefined,
        fontSize: "0.75rem",
      }}
    >
      {text ?? value}
    </span>
  );
}

/**
 * Unwraps a Recharts legend payload entry to its series name.
 *
 * `<Legend onClick>` is invoked as `(entry, index, event)`, so the click handler
 * receives the payload entry rather than a bare string.
 */
export function legendValue(entry: unknown): string {
  const e = entry as { value?: unknown; name?: unknown } | null;
  if (e == null) return "";
  const v = e.value ?? e.name;
  return v == null ? "" : String(v);
}