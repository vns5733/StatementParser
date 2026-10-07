"use client";

import type { Transaction } from "@/types";

/**
 * Marks a row whose category disagrees with the side its money moved.
 *
 * Two distinct cases, deliberately shown differently rather than as one flag:
 *
 *  - Direction_Reclassified is set when the reconciler MOVED the row (a credit on
 *    Investment became Investment_Liquidation). This is informational — the row is
 *    correct now, and the badge exists so a label the parser never produced is not
 *    presented as if it always had been.
 *
 *  - Direction_Mismatch is set when the row could NOT be moved and the user has to
 *    decide. A credit under Groceries is most likely a refund, and the category is
 *    already right for the arithmetic, so re-filing it would stop it netting off
 *    the original spend. That is a question for the user, not a bug.
 */
export default function DirectionBadge({
  row,
  compact = false,
}: {
  row: Transaction;
  compact?: boolean;
}) {
  const reclassified = row.Direction_Reclassified;
  const mismatch = row.Direction_Mismatch;

  if (!reclassified && !mismatch) return null;

  if (reclassified) {
    const title = `Money came IN, so this was re-filed from ${reclassified}. Both are the same activity with the direction reversed.`;
    return (
      <span className={`dir-badge dir-badge-moved${compact ? " dir-badge-compact" : ""}`} title={title}>
        {compact ? "\u21a9" : `${reclassified} \u2192`}
      </span>
    );
  }

  const title =
    row.Direction_Mismatch_Reason ||
    "This row's category disagrees with the side its money moved.";
  return (
    <span
      className={`dir-badge dir-badge-mismatch${compact ? " dir-badge-compact" : ""}`}
      title={title}
    >
      {compact ? "!" : "check side"}
    </span>
  );
}