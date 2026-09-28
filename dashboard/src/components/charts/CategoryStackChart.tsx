"use client";

import React, { useMemo } from "react";
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
import { MonthlyCategoryEntry } from "@/types";
import { formatCurrency, formatCompactCurrency } from "@/lib/formatters";

interface CategoryStackChartProps {
  data: MonthlyCategoryEntry[];
  isLoading?: boolean;
}

const PALETTE = [
  "#6366f1", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6",
  "#06b6d4", "#14b8a6", "#f97316", "#eab308", "#84cc16",
  "#0ea5e9", "#a855f7", "#d946ef", "#f43f5e", "#64748b",
  "#3b82f6", "#22c55e", "#e11d48", "#7c3aed", "#0284c7"
];

export default function CategoryStackChart({
  data,
  isLoading,
}: CategoryStackChartProps) {
  // Extract distinct categories
  const categories = useMemo(() => {
    const set = new Set<string>();
    data.forEach((d) => {
      if (d.Broad_Category) set.add(d.Broad_Category);
    });
    return Array.from(set).sort();
  }, [data]);

  // Pivot data so each row has: label, and keys like `Debit_${cat}` and `Credit_${cat}`
  const pivoted = useMemo(() => {
    const map = new Map<string, any>();
    data.forEach((item) => {
      const lbl = item.label;
      if (!map.has(lbl)) {
        map.set(lbl, { label: lbl });
      }
      const row = map.get(lbl);
      const cat = item.Broad_Category || "Uncategorized";
      if (item.Total_Debit > 0) {
        row[`Debit_${cat}`] = (row[`Debit_${cat}`] || 0) + item.Total_Debit;
      }
      if (item.Total_Credit > 0) {
        row[`Credit_${cat}`] = (row[`Credit_${cat}`] || 0) + item.Total_Credit;
      }
    });
    return Array.from(map.values());
  }, [data]);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="glass-panel" style={{ padding: "12px 16px", maxHeight: "300px", overflowY: "auto", minWidth: "220px" }}>
          <div style={{ fontWeight: 700, marginBottom: "8px", color: "var(--text-primary)" }}>
            {label}
          </div>
          {payload.map((entry: any) => {
            const isDebit = entry.dataKey.startsWith("Debit_");
            const catName = entry.dataKey.replace("Debit_", "").replace("Credit_", "");
            return (
              <div
                key={entry.dataKey}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: "0.8rem",
                  marginBottom: "4px",
                  gap: "12px",
                }}
              >
                <span style={{ color: entry.color, display: "flex", alignItems: "center", gap: "6px" }}>
                  <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", background: entry.color }} />
                  {catName} ({isDebit ? "Debit" : "Credit"}):
                </span>
                <span style={{ fontWeight: 600 }}>{formatCurrency(entry.value)}</span>
              </div>
            );
          })}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass-panel" style={{ padding: "20px", marginBottom: "24px" }}>
      <div style={{ marginBottom: "16px" }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          Monthly Cash Flow by Broad Category
        </h3>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Detailed breakdown of debits and credits layered by semantic categories
        </p>
      </div>

      {isLoading ? (
        <div style={{ height: "360px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          Loading category stack data...
        </div>
      ) : pivoted.length === 0 ? (
        <div style={{ height: "360px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          No category stack data available
        </div>
      ) : (
        <div style={{ width: "100%", height: "360px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={pivoted} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
              <XAxis dataKey="label" stroke="var(--text-muted)" fontSize={12} tickLine={false} />
              <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={formatCompactCurrency} tickLine={false} />
              <Tooltip content={<CustomTooltip />} />
              <Legend
                wrapperStyle={{ paddingTop: "12px", maxHeight: "60px", overflowY: "auto" }}
                formatter={(val: string) => {
                  const name = val.replace("Debit_", "").replace("Credit_", "");
                  const isDebit = val.startsWith("Debit_");
                  return (
                    <span style={{ color: "var(--text-secondary)", fontSize: "0.75rem", marginRight: "8px" }}>
                      {name} {isDebit ? "(-)" : "(+)"}
                    </span>
                  );
                }}
              />
              {categories.map((cat, i) => {
                const color = PALETTE[i % PALETTE.length];
                return (
                  <React.Fragment key={cat}>
                    <Bar
                      dataKey={`Credit_${cat}`}
                      name={`Credit_${cat}`}
                      stackId="credit"
                      fill={color}
                      maxBarSize={36}
                    />
                    <Bar
                      dataKey={`Debit_${cat}`}
                      name={`Debit_${cat}`}
                      stackId="debit"
                      fill={color}
                      fillOpacity={0.8}
                      maxBarSize={36}
                    />
                  </React.Fragment>
                );
              })}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
