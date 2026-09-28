"use client";

import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { TimelineEntry, GroupBy } from "@/types";
import { formatCurrency, formatCompactCurrency } from "@/lib/formatters";

interface TimelineChartProps {
  data: TimelineEntry[];
  groupBy: GroupBy;
  onChangeGroupBy: (g: GroupBy) => void;
  isLoading?: boolean;
}

export default function TimelineChart({
  data,
  groupBy,
  onChangeGroupBy,
  isLoading,
}: TimelineChartProps) {
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const credit = payload.find((p: any) => p.dataKey === "Total_Credit")?.value || 0;
      const debit = payload.find((p: any) => p.dataKey === "Total_Debit")?.value || 0;
      const net = credit - debit;

      return (
        <div className="glass-panel" style={{ padding: "12px 16px", minWidth: "200px" }}>
          <div style={{ fontWeight: 700, marginBottom: "8px", color: "var(--text-primary)" }}>
            {label}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
            <span style={{ color: "var(--emerald-inflow)" }}>Credit:</span>
            <span style={{ fontWeight: 600 }}>{formatCurrency(credit)}</span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
            <span style={{ color: "var(--rose-outflow)" }}>Debit:</span>
            <span style={{ fontWeight: 600 }}>{formatCurrency(debit)}</span>
          </div>
          <div style={{
            borderTop: "1px solid var(--border-subtle)",
            marginTop: "6px",
            paddingTop: "6px",
            display: "flex",
            justifyContent: "space-between"
          }}>
            <span style={{ color: "var(--text-muted)" }}>Net:</span>
            <span style={{ fontWeight: 700, color: net >= 0 ? "var(--emerald-inflow)" : "var(--rose-outflow)" }}>
              {formatCurrency(net)}
            </span>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: "16px",
        flexWrap: "wrap",
        gap: "12px"
      }}>
        <div>
          <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
            Cash Flow Timeline (Credit vs. Debit)
          </h3>
          <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Inflows and outflows grouped over time
          </p>
        </div>

        {/* Grouping switch */}
        <div style={{
          display: "inline-flex",
          background: "rgba(255, 255, 255, 0.05)",
          padding: "3px",
          borderRadius: "var(--radius-md)",
          border: "1px solid var(--border-subtle)"
        }}>
          <button
            className="btn"
            onClick={() => onChangeGroupBy("month")}
            style={{
              padding: "4px 12px",
              fontSize: "0.8rem",
              background: groupBy === "month" ? "var(--accent-indigo)" : "transparent",
              color: groupBy === "month" ? "#fff" : "var(--text-muted)",
              boxShadow: groupBy === "month" ? "0 2px 8px var(--accent-indigo-glow)" : "none"
            }}
          >
            Monthly
          </button>
          <button
            className="btn"
            onClick={() => onChangeGroupBy("year")}
            style={{
              padding: "4px 12px",
              fontSize: "0.8rem",
              background: groupBy === "year" ? "var(--accent-indigo)" : "transparent",
              color: groupBy === "year" ? "#fff" : "var(--text-muted)",
              boxShadow: groupBy === "year" ? "0 2px 8px var(--accent-indigo-glow)" : "none"
            }}
          >
            Yearly
          </button>
        </div>
      </div>

      {isLoading ? (
        <div style={{ height: "340px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          Loading timeline data...
        </div>
      ) : data.length === 0 ? (
        <div style={{ height: "340px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          No data available for timeline
        </div>
      ) : (
        <div style={{ width: "100%", height: "340px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
              <XAxis
                dataKey="label"
                stroke="var(--text-muted)"
                fontSize={12}
                tickLine={false}
              />
              <YAxis
                stroke="var(--text-muted)"
                fontSize={12}
                tickFormatter={formatCompactCurrency}
                tickLine={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ paddingTop: "10px" }}
                formatter={(value) => (
                  <span style={{ color: "var(--text-secondary)", fontSize: "0.85rem" }}>
                    {value === "Total_Credit" ? "Credit (Inflow)" : "Debit (Outflow)"}
                  </span>
                )}
              />
              <Bar
                dataKey="Total_Credit"
                name="Total_Credit"
                fill="#10b981"
                radius={[4, 4, 0, 0]}
                maxBarSize={40}
              />
              <Bar
                dataKey="Total_Debit"
                name="Total_Debit"
                fill="#f43f5e"
                radius={[4, 4, 0, 0]}
                maxBarSize={40}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
