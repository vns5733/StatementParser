"use client";

import React, { useState } from "react";
import {
  ResponsiveContainer,
  PieChart as RechartsPieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
} from "recharts";
import { CategoryBreakdownEntry, GroupCol } from "@/types";
import { formatCurrency } from "@/lib/formatters";

interface PieChartProps {
  data: CategoryBreakdownEntry[];
  groupBy: GroupCol;
  onChangeGroupBy: (g: GroupCol) => void;
  isLoading?: boolean;
}

const COLORS = [
  "#6366f1", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6",
  "#06b6d4", "#14b8a6", "#f97316", "#eab308", "#84cc16",
  "#0ea5e9", "#a855f7", "#d946ef", "#f43f5e", "#64748b",
  "#3b82f6", "#22c55e", "#e11d48", "#7c3aed", "#0284c7"
];

export default function PieChart({
  data,
  groupBy,
  onChangeGroupBy,
  isLoading,
}: PieChartProps) {
  const [direction, setDirection] = useState<"Debit" | "Credit">("Debit");

  const chartData = data
    .map((item) => ({
      name: item.Category || "Uncategorized",
      value: direction === "Debit" ? item.Total_Debit : item.Total_Credit,
    }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value);

  const total = chartData.reduce((acc, curr) => acc + curr.value, 0);

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const item = payload[0];
      const percent = total > 0 ? ((item.value / total) * 100).toFixed(1) : 0;
      return (
        <div className="glass-panel" style={{ padding: "10px 14px", minWidth: "160px" }}>
          <div style={{ fontWeight: 700, marginBottom: "4px", color: "var(--text-primary)" }}>
            {item.name}
          </div>
          <div style={{ color: item.payload.fill, fontWeight: 600 }}>
            {formatCurrency(item.value)}
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "2px" }}>
            {percent}% of total {direction === "Debit" ? "outflow" : "inflow"}
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass-panel" style={{ padding: "20px", height: "100%" }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        marginBottom: "16px",
        flexWrap: "wrap",
        gap: "8px"
      }}>
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Category Distribution
          </h3>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Share of {direction === "Debit" ? "expenses" : "inflows"} by group
          </p>
        </div>

        {/* Controls */}
        <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
          {/* Direction toggle */}
          <div style={{
            display: "inline-flex",
            background: "rgba(255, 255, 255, 0.05)",
            padding: "2px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)"
          }}>
            <button
              onClick={() => setDirection("Debit")}
              style={{
                padding: "3px 8px",
                fontSize: "0.75rem",
                borderRadius: "var(--radius-sm)",
                border: "none",
                cursor: "pointer",
                background: direction === "Debit" ? "var(--rose-outflow)" : "transparent",
                color: "#fff"
              }}
            >
              Debits
            </button>
            <button
              onClick={() => setDirection("Credit")}
              style={{
                padding: "3px 8px",
                fontSize: "0.75rem",
                borderRadius: "var(--radius-sm)",
                border: "none",
                cursor: "pointer",
                background: direction === "Credit" ? "var(--emerald-inflow)" : "transparent",
                color: "#fff"
              }}
            >
              Credits
            </button>
          </div>

          {/* GroupBy toggle — each level of the hierarchy, or the raw channel */}
          <div style={{
            display: "inline-flex",
            background: "rgba(255, 255, 255, 0.05)",
            padding: "2px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
            flexWrap: "wrap",
            gap: "2px",
          }}>
            {([
              { key: "Category", label: "Top" },
              { key: "Broad_Category", label: "Category" },
              { key: "Sub_Category", label: "Sub" },
              { key: "Transaction_Type", label: "Channel" },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                onClick={() => onChangeGroupBy(opt.key)}
                style={{
                  padding: "3px 8px",
                  fontSize: "0.75rem",
                  borderRadius: "var(--radius-sm)",
                  border: "none",
                  cursor: "pointer",
                  background: groupBy === opt.key ? "var(--accent-indigo)" : "transparent",
                  color: groupBy === opt.key ? "#fff" : "var(--text-muted)",
                  fontWeight: 600,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          Loading breakdown...
        </div>
      ) : chartData.length === 0 ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          No {direction.toLowerCase()} data for selected criteria
        </div>
      ) : (
        <div style={{ width: "100%", height: "300px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <RechartsPieChart>
              <Tooltip content={<CustomTooltip />} />
              <Legend
                layout="vertical"
                align="right"
                verticalAlign="middle"
                wrapperStyle={{ maxHeight: "280px", overflowY: "auto", fontSize: "0.75rem" }}
                formatter={(val) => <span style={{ color: "var(--text-secondary)" }}>{val}</span>}
              />
              <Pie
                data={chartData}
                dataKey="value"
                nameKey="name"
                cx="40%"
                cy="50%"
                innerRadius={65}
                outerRadius={95}
                paddingAngle={2}
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
            </RechartsPieChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
