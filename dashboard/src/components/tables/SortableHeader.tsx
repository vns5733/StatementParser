"use client";

import React from "react";

export type SortOrder = "asc" | "desc";

interface SortableHeaderProps {
  /** Column key sent to the API as `sort_by`. Must be in its SORTABLE_COLUMNS. */
  col: string;
  label: string;
  align?: "left" | "right";
  sortBy: string;
  sortOrder: SortOrder;
  onSortChange: (col: string, order: SortOrder) => void;
  /** Base cell padding, so every table's header row lines up with its own body. */
  padding?: string;
}

/**
 * A clickable column header that toggles asc/desc.
 *
 * Extracted from CategoryEditorTable so every table that lists transactions
 * sorts the same way. Sorting is server-side (`sort_by` / `sort_order`), because
 * the tables are paginated: sorting only the rows on screen would show an
 * arbitrary page rather than the true top or bottom of the set.
 */
export default function SortableHeader({
  col,
  label,
  align = "left",
  sortBy,
  sortOrder,
  onSortChange,
  padding = "10px 12px",
}: SortableHeaderProps) {
  const active = sortBy === col;
  // Clicking the active column flips it; clicking a new one starts ascending.
  const nextOrder: SortOrder = active && sortOrder === "asc" ? "desc" : "asc";
  return (
    <th
      style={{
        padding,
        color: active ? "var(--accent-indigo)" : "var(--text-muted)",
        fontWeight: 600,
        textAlign: align,
        cursor: "pointer",
        userSelect: "none",
        whiteSpace: "nowrap",
      }}
      onClick={() => onSortChange(col, nextOrder)}
      title={`Sort by ${label}`}
      aria-sort={active ? (sortOrder === "asc" ? "ascending" : "descending") : "none"}
    >
      {label}{" "}
      <span style={{ fontSize: "0.7rem", opacity: active ? 1 : 0.5 }}>
        {active ? (sortOrder === "asc" ? "▲" : "▼") : "↕"}
      </span>
    </th>
  );
}
