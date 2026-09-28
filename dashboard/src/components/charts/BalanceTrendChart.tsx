"use client";

import React from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { BalanceTrendEntry } from "@/types";
import { formatCurrency, formatCompactCurrency, formatDate } from "@/lib/formatters";

interface BalanceTrendChartProps {
  data: BalanceTrendEntry[];
  isLoading?: boolean;
}

export default function BalanceTrendChart({
  data,
  isLoading,
}: BalanceTrendChartProps) {
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const balance = payload[0].value;
      return (
        <div className="glass-panel" style={{ padding: "10px 14px", minWidth: "170px" }}>
          <div style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginBottom: "4px" }}>
            {formatDate(label)}
          </div>
          <div style={{ color: "var(--blue-balance)", fontWeight: 700, fontSize: "1.05rem" }}>
            {formatCurrency(balance)}
          </div>
          <div style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "2px" }}>
            Closing Balance
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="glass-panel" style={{ padding: "20px", height: "100%" }}>
      <div style={{ marginBottom: "16px" }}>
        <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "var(--text-primary)" }}>
          Account Balance Trend
        </h3>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Historical closing balance trajectory
        </p>
      </div>

      {isLoading ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          Loading balance trend...
        </div>
      ) : data.length === 0 ? (
        <div style={{ height: "300px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)" }}>
          No balance data available
        </div>
      ) : (
        <div style={{ width: "100%", height: "300px" }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
              <defs>
                <linearGradient id="balanceGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.4} />
                  <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" />
              <XAxis
                dataKey="Date"
                stroke="var(--text-muted)"
                fontSize={12}
                tickFormatter={(val) => formatDate(val)}
                tickLine={false}
              />
              <YAxis
                stroke="var(--text-muted)"
                fontSize={12}
                tickFormatter={formatCompactCurrency}
                tickLine={false}
              />
              <Tooltip content={<CustomTooltip />} />
              <Area
                type="monotone"
                dataKey="Closing_Balance"
                stroke="#38bdf8"
                strokeWidth={2.5}
                fillOpacity={1}
                fill="url(#balanceGradient)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
