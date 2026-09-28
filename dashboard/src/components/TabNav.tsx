"use client";

import React from "react";

export type TabId = "analytics" | "explorer" | "categories" | "cards";

interface TabNavProps {
  activeTab: TabId;
  onChangeTab: (tab: TabId) => void;
  /** Card statement count, shown as a badge on the Credit Cards tab. */
  cardCount?: number;
}

export default function TabNav({ activeTab, onChangeTab, cardCount }: TabNavProps) {
  const tabs: { id: TabId; label: string; icon: string }[] = [
    { id: "analytics", label: "Time & Group Analytics", icon: "📊" },
    { id: "explorer", label: "Interactive Search & Table", icon: "🔎" },
    { id: "categories", label: "Broad Categories", icon: "🏷️" },
    { id: "cards", label: "Credit Cards", icon: "💳" },
  ];

  return (
    <div style={{
      display: "flex",
      gap: "8px",
      borderBottom: "1px solid var(--border-subtle)",
      marginBottom: "24px",
      paddingBottom: "4px"
    }}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onChangeTab(tab.id)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "8px",
              padding: "10px 18px",
              fontSize: "0.95rem",
              fontWeight: 600,
              color: isActive ? "var(--text-primary)" : "var(--text-muted)",
              background: isActive ? "rgba(99, 102, 241, 0.15)" : "transparent",
              border: "1px solid",
              borderColor: isActive ? "rgba(99, 102, 241, 0.4)" : "transparent",
              borderRadius: "var(--radius-md)",
              cursor: "pointer",
              transition: "all 0.15s ease",
              position: "relative"
            }}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
            {tab.id === "cards" && cardCount != null && cardCount > 0 && (
              <span
                className="badge badge-indigo"
                style={{ fontSize: "0.65rem", padding: "1px 7px" }}
              >
                {cardCount}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
