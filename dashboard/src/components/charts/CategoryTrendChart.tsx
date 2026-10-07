"use client";

import React from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { CategoryTrendEntry } from "@/types";
import { formatCurrency, formatCompactCurrency } from "@/lib/formatters";
import { legendLabel, legendValue } from "@/lib/legend";

/** Maps a Recharts series key onto the `direction` filter value. */
function directionOf(series: string): "debits" | "credits" {
  return series === "Total_Credit" ? "credits" : "debits";
}

interface CategoryTrendChartProps {
  data: CategoryTrendEntry[];
  category: string;
  isLoading?: boolean;
  /** Called with "credits" or "debits" when a legend entry is clicked. */
  onSelectDirection?: (direction: "debits" | "credits") => void;
  /** The active direction, so the legend shows which one is applied. */
  activeDirection?: "all" | "debits" | "credits";
}

export default function CategoryTrendChart({
  data,
  category,
  isLoading,
  onSelectDirection,
  activeDirection = "all",
}: CategoryTrendChartProps) {
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const debit = payload.find((p: any) => p.dataKey === "Total_Debit")?.value || 0;
      const credit = payload.find((p: any) => p.dataKey === "Total_Credit")?.value || 0;

      return (
        <div className="glass-panel" style={{ padding: "12px 16px", minWidth: "180px" }}>
          <div style={{ fontWeight: 700, marginBottom: "8px", color: "var(--text-primary)" }}>
            {label}
          </div>
          {debit > 0 && (
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
              <span style={{ color: "var(--rose-outflow)" }}>Debit:</span>
              <span style={{ fontWeight: 600 }}>{formatCurrency(debit)}</span>
            </div>
          )}
          {credit > 0 && (
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
              <span style={{ color: "var(--emerald-inflow)" }}>Credit:</span>
              <span style={{ fontWeight: 600 }}>{formatCurrency(credit)}</span>
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass-panel" style={{ padding: "20px" }}>
      <div style={{ marginBottom: "16px" }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          {category} — Monthly Trend
        </h3>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Monthly inflows and outflows specifically for this category
        </p>
      </div>

      {isLoading ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          Loading trend...
        </div>
      ) : data.length === 0 ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          No trend data recorded for {category}
        </div>
      ) : (
        <div style={{ width: "100%", height: "300px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
              <XAxis dataKey="Year_Month" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={formatCompactCurrency} tickLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ paddingTop: "10px" }}
                onClick={
                  onSelectDirection
                    ? (entry: any) => onSelectDirection(directionOf(legendValue(entry)))
                    : undefined
                }
                formatter={(val) =>
                  legendLabel(
                    String(val),
                    directionOf(String(val)) === "credits"
                      ? "Credit (Inflow)"
                      : "Debit (Outflow)",
                    activeDirection === directionOf(String(val))
                  )
                }
              />
              <Line
                type="monotone"
                dataKey="Total_Debit"
                name="Total_Debit"
                stroke="#f43f5e"
                strokeWidth={2.5}
                dot={{ r: 4, fill: "#f43f5e" }}
                activeDot={{ r: 6 }}
              />
              <Line
                type="monotone"
                dataKey="Total_Credit"
                name="Total_Credit"
                stroke="#10b981"
                strokeWidth={2.5}
                dot={{ r: 4, fill: "#10b981" }}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
