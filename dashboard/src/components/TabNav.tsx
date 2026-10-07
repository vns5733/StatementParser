"use client";

import React from "react";

export type TabId = "overview" | "transactions" | "cards" | "insights";

interface TabNavProps {
  activeTab: TabId;
  onChangeTab: (tab: TabId) => void;
  /** Card statement count, shown as a badge on the Cards tab. */
  cardCount?: number;
}

export default function TabNav({ activeTab, onChangeTab, cardCount }: TabNavProps) {
  // The tabs are cut on what you are trying to answer, not on which chart you
  // want. Scope (bank / card / both) is a filter in the sidebar rather than a
  // tab, which is what removed a card tab that was a clone of the Overview.
  const tabs: { id: TabId; label: string; icon: string }[] = [
    { id: "overview", label: "Overview", icon: "📊" },
    { id: "transactions", label: "Transactions", icon: "🔎" },
    { id: "cards", label: "Cards", icon: "💳" },
    { id: "insights", label: "Insights", icon: "💡" },
  ];

  return (
    <div className="tab-nav" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          className="tab-btn"
          aria-selected={tab.id === activeTab}
          onClick={() => onChangeTab(tab.id)}
        >
          <span aria-hidden>{tab.icon}</span>
          <span>{tab.label}</span>
          {tab.id === "cards" && cardCount != null && cardCount > 0 && (
            <span className="tab-count">{cardCount}</span>
          )}
        </button>
      ))}
    </div>
  );
}