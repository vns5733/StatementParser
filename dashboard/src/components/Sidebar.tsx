"use client";

import React, { useState } from "react";
import { Filters, Meta } from "@/types";
import api from "@/lib/api";

interface SidebarProps {
  meta?: Meta;
  filters: Filters;
  onChangeFilters: (f: Filters) => void;
  categories: string[];
  subCategories: string[];
  customCategories: string[];
  onAddCategory: (name: string) => Promise<void>;
  onDeleteCategory: (name: string) => Promise<void>;
  onDataUploaded: () => void;
  onRecategorized: () => void;
}

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

export default function Sidebar({
  meta,
  filters,
  onChangeFilters,
  categories,
  subCategories,
  customCategories,
  onAddCategory,
  onDeleteCategory,
  onDataUploaded,
  onRecategorized,
}: SidebarProps) {
  const [newCatName, setNewCatName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [isRecategorizing, setIsRecategorizing] = useState(false);
  const [recatMessage, setRecatMessage] = useState<string | null>(null);
  const [customExpanded, setCustomExpanded] = useState(false);
  const [isLoadingSample, setIsLoadingSample] = useState(false);

  // Load the bundled sample statement into an empty database
  const handleLoadSample = async () => {
    try {
      setIsLoadingSample(true);
      const res = await api.post("/transactions/load-sample");
      setUploadMessage({
        type: "success",
        text: `Loaded ${res.data.imported} sample transactions from ${res.data.filename}.`,
      });
      onDataUploaded();
    } catch (err: any) {
      setUploadMessage({
        type: "error",
        text: err?.response?.data?.detail || err.message || "Sample load failed",
      });
    } finally {
      setIsLoadingSample(false);
    }
  };

  // File Upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("file", file);

    try {
      setIsUploading(true);
      setUploadMessage(null);
      const res = await api.post("/transactions/upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadMessage({
        type: "success",
        text: `Imported ${res.data.imported} transactions from ${file.name}!`,
      });
      onDataUploaded();
    } catch (err: any) {
      setUploadMessage({
        type: "error",
        text: err?.response?.data?.detail || err.message || "Upload failed",
      });
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  // Recategorize All
  const handleRecategorize = async () => {
    try {
      setIsRecategorizing(true);
      setRecatMessage(null);
      await api.post("/transactions/recategorize");
      setRecatMessage("Successfully re-parsed all narrations!");
      onRecategorized();
    } catch (err: any) {
      setRecatMessage("Recategorization failed: " + (err?.response?.data?.detail || err.message));
    } finally {
      setIsRecategorizing(false);
    }
  };

  // Add custom category
  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCatName.trim()) return;
    try {
      await onAddCategory(newCatName.trim());
      setNewCatName("");
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to add category");
    }
  };

  // Toggle helpers
  const toggleYear = (yr: number) => {
    const exists = filters.years.includes(yr);
    const updated = exists ? filters.years.filter((y) => y !== yr) : [...filters.years, yr];
    onChangeFilters({ ...filters, years: updated });
  };

  const toggleMonth = (m: number) => {
    const exists = filters.months.includes(m);
    const updated = exists ? filters.months.filter((val) => val !== m) : [...filters.months, m];
    onChangeFilters({ ...filters, months: updated });
  };

  const resetFilters = () => {
    onChangeFilters({
      years: meta?.years || [],
      months: meta?.months || [],
      txnTypes: [],
      broadCategories: [],
      categories: [],
      subCategories: [],
      isRecurring: null,
      direction: "all",
      search: "",
      amountField: "any",
      amountMin: null,
      amountMax: null,
      spendBasis: "all",
      accountSources: [],
    });
  };

  return (
    <aside style={{
      width: "320px",
      minWidth: "320px",
      background: "var(--bg-secondary)",
      borderRight: "1px solid var(--border-subtle)",
      padding: "24px 20px",
      display: "flex",
      flexDirection: "column",
      gap: "24px",
      overflowY: "auto",
      maxHeight: "100vh",
    }}>
      {/* Brand Header */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
          <span style={{ fontSize: "1.75rem" }}>💳</span>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 800, color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
            StatementParser
          </h1>
        </div>
        <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
          Bank Statement Intelligence & Analytics
        </p>
      </div>

      {/* Upload Statement */}
      <div className="glass-panel-subtle" style={{ padding: "16px" }}>
        <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--text-secondary)", marginBottom: "8px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          📥 Upload Statement
        </h3>
        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "12px" }}>
          Upload .xls, .xlsx, .csv, or .pdf bank statement to parse & store.
        </p>

        <label
          className="btn btn-primary"
          style={{ width: "100%", textAlign: "center", cursor: isUploading ? "not-allowed" : "pointer" }}
        >
          {isUploading ? "Processing..." : "Select Statement File"}
          <input
            type="file"
            accept=".xls,.xlsx,.csv,.pdf"
            onChange={handleFileUpload}
            disabled={isUploading}
            style={{ display: "none" }}
          />
        </label>

        {uploadMessage && (
          <div style={{
            marginTop: "10px",
            padding: "8px",
            borderRadius: "var(--radius-sm)",
            fontSize: "0.75rem",
            background: uploadMessage.type === "success" ? "rgba(16, 185, 129, 0.15)" : "rgba(244, 63, 94, 0.15)",
            color: uploadMessage.type === "success" ? "#34d399" : "#fb7185",
            border: `1px solid ${uploadMessage.type === "success" ? "rgba(16, 185, 129, 0.3)" : "rgba(244, 63, 94, 0.3)"}`,
          }}>
            {uploadMessage.text}
          </div>
        )}

        {/* Empty-database affordance: seed a fresh install with the sample file */}
        {meta && meta.years.length === 0 && (
          <button
            className="btn btn-secondary"
            onClick={handleLoadSample}
            disabled={isLoadingSample}
            style={{ width: "100%", marginTop: "10px", fontSize: "0.78rem" }}
          >
            {isLoadingSample ? "Loading sample..." : "📥 Load Sample Statement"}
          </button>
        )}
      </div>

      {/* Recategorize Narrations */}
      <div className="glass-panel-subtle" style={{ padding: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
          <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            ♻️ Recategorize
          </h3>
        </div>
        <p style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "10px" }}>
          Re-parse all stored narrations with latest rules.
        </p>
        <button
          className="btn btn-secondary"
          onClick={handleRecategorize}
          disabled={isRecategorizing}
          style={{ width: "100%", fontSize: "0.8rem" }}
        >
          {isRecategorizing ? "Re-parsing..." : "Recategorize All"}
        </button>
        {recatMessage && (
          <div style={{ fontSize: "0.75rem", color: "var(--emerald-inflow)", marginTop: "6px" }}>
            {recatMessage}
          </div>
        )}
      </div>

      {/* Manage Broad Categories */}
      <div className="glass-panel-subtle" style={{ padding: "16px" }}>
        <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--text-secondary)", marginBottom: "6px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
          🏷️ Broad Categories
        </h3>
        <form onSubmit={handleAddCategory} style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
          <input
            type="text"
            className="input"
            placeholder="New category..."
            value={newCatName}
            onChange={(e) => setNewCatName(e.target.value)}
            style={{ fontSize: "0.8rem", padding: "6px 8px" }}
          />
          <button type="submit" className="btn btn-primary" style={{ padding: "6px 12px", fontSize: "0.8rem" }}>
            +
          </button>
        </form>

        {customCategories.length > 0 && (
          <div>
            <button
              onClick={() => setCustomExpanded(!customExpanded)}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-muted)",
                fontSize: "0.75rem",
                cursor: "pointer",
                padding: 0,
              }}
            >
              {customExpanded ? "▾ Hide" : "▸ Show"} Custom Categories ({customCategories.length})
            </button>

            {customExpanded && (
              <div style={{ marginTop: "8px", display: "flex", flexDirection: "column", gap: "4px" }}>
                {customCategories.map((name) => (
                  <div
                    key={name}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      fontSize: "0.8rem",
                      padding: "4px 6px",
                      background: "rgba(255, 255, 255, 0.02)",
                      borderRadius: "var(--radius-sm)",
                    }}
                  >
                    <span>{name}</span>
                    <button
                      onClick={() => onDeleteCategory(name)}
                      style={{
                        background: "transparent",
                        border: "none",
                        color: "var(--rose-outflow)",
                        cursor: "pointer",
                        fontSize: "0.85rem",
                      }}
                      title="Delete category"
                    >
                      🗑
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Filters Section */}
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ fontSize: "0.85rem", fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            🔍 Filters & Search
          </h3>
          <button
            onClick={resetFilters}
            style={{
              background: "transparent",
              border: "none",
              color: "var(--accent-indigo)",
              fontSize: "0.75rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reset All
          </button>
        </div>

        {/* Free text search */}
        <div>
          <input
            type="text"
            className="input"
            placeholder="Search narration, payee, ref..."
            value={filters.search}
            onChange={(e) => onChangeFilters({ ...filters, search: e.target.value })}
            style={{ fontSize: "0.8rem" }}
          />
        </div>

        {/* Direction Filter */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Direction
          </label>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: "4px",
            background: "var(--bg-input)",
            padding: "3px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
          }}>
            {(["all", "debits", "credits"] as const).map((dir) => (
              <button
                key={dir}
                onClick={() => onChangeFilters({ ...filters, direction: dir })}
                style={{
                  padding: "5px 0",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  background: filters.direction === dir ? "var(--accent-indigo)" : "transparent",
                  color: filters.direction === dir ? "#fff" : "var(--text-muted)",
                }}
              >
                {dir === "all" ? "All" : dir === "debits" ? "Debits" : "Credits"}
              </button>
            ))}
          </div>
        </div>

        {/* Spend Basis — which ledger the numbers come from.
            A card purchase and the bank debit that settles it are two halves of
            one transaction, so the server drops the settlement from every basis;
            otherwise a card purchase would be counted twice. */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Spend Basis
          </label>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: "4px",
            background: "var(--bg-input)",
            padding: "3px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
          }}>
            {([
              { key: "all", label: "Combined" },
              { key: "bank_only", label: "Bank" },
              { key: "card_only", label: "Card" },
            ] as const).map((opt) => (
              <button
                key={opt.key}
                onClick={() => onChangeFilters({ ...filters, spendBasis: opt.key })}
                title={
                  opt.key === "all"
                    ? "Bank and card spend combined, with card bill payments excluded"
                    : opt.key === "bank_only"
                      ? "Only transactions paid from the bank account"
                      : "Only credit-card purchases"
                }
                style={{
                  padding: "5px 0",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  background: filters.spendBasis === opt.key ? "var(--accent-indigo)" : "transparent",
                  color: filters.spendBasis === opt.key ? "#fff" : "var(--text-muted)",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Year Pills */}
        {meta?.years && meta.years.length > 0 && (
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
              Years
            </label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {meta.years.map((yr) => {
                const isSelected = filters.years.includes(yr);
                return (
                  <button
                    key={yr}
                    onClick={() => toggleYear(yr)}
                    style={{
                      padding: "4px 8px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      borderRadius: "var(--radius-sm)",
                      border: `1px solid ${isSelected ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
                      background: isSelected ? "rgba(99, 102, 241, 0.2)" : "transparent",
                      color: isSelected ? "#fff" : "var(--text-muted)",
                      cursor: "pointer",
                    }}
                  >
                    {yr}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Month Pills */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Months
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "4px" }}>
            {MONTH_NAMES.map((name, idx) => {
              const mNum = idx + 1;
              const isSelected = filters.months.includes(mNum);
              return (
                <button
                  key={name}
                  onClick={() => toggleMonth(mNum)}
                  style={{
                    padding: "4px 0",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    borderRadius: "var(--radius-sm)",
                    border: `1px solid ${isSelected ? "var(--accent-indigo)" : "var(--border-subtle)"}`,
                    background: isSelected ? "rgba(99, 102, 241, 0.2)" : "transparent",
                    color: isSelected ? "#fff" : "var(--text-muted)",
                    cursor: "pointer",
                  }}
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Category Multiselect */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Category
          </label>
          <select
            className="select"
            multiple
            value={filters.categories}
            onChange={(e) => {
              const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
              onChangeFilters({ ...filters, categories: selected });
            }}
            style={{ height: "90px", fontSize: "0.8rem" }}
          >
            {(meta?.categories || []).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: "4px" }}>
            Top-level groups that roll up everything beneath them.
          </p>
        </div>

        {/* Broad Category Multiselect */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Broad Category
          </label>
          <select
            className="select"
            multiple
            value={filters.broadCategories}
            onChange={(e) => {
              const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
              onChangeFilters({ ...filters, broadCategories: selected });
            }}
            style={{ height: "110px", fontSize: "0.8rem" }}
          >
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        {/* Sub-Category Multiselect */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Sub-Category
          </label>
          <select
            className="select"
            multiple
            value={filters.subCategories}
            onChange={(e) => {
              const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
              onChangeFilters({ ...filters, subCategories: selected });
            }}
            style={{ height: "110px", fontSize: "0.8rem" }}
          >
            {subCategories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <p style={{ fontSize: "0.68rem", color: "var(--text-muted)", marginTop: "4px" }}>
            Finest level — e.g. Residential_Rent vs CoLiving_Rent vs Rent_Brokerage.
          </p>
        </div>

        {/* Recurring toggle */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Recurrence
          </label>
          <div style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: "4px",
            background: "var(--bg-input)",
            padding: "3px",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
          }}>
            {([
              { key: null, label: "All" },
              { key: true, label: "Recurring" },
              { key: false, label: "One-off" },
            ] as const).map((opt) => (
              <button
                key={String(opt.key)}
                onClick={() => onChangeFilters({ ...filters, isRecurring: opt.key })}
                title="Counterparties that repeat monthly — rent, EMIs, SIPs, subscriptions"
                style={{
                  padding: "5px 0",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  border: "none",
                  borderRadius: "var(--radius-sm)",
                  cursor: "pointer",
                  background: filters.isRecurring === opt.key ? "var(--accent-indigo)" : "transparent",
                  color: filters.isRecurring === opt.key ? "#fff" : "var(--text-muted)",
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Channel Type Multiselect */}
        {meta?.txn_types && (
          <div>
            <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
              Channel Type
            </label>
            <select
              className="select"
              multiple
              value={filters.txnTypes}
              onChange={(e) => {
                const selected = Array.from(e.target.selectedOptions, (opt) => opt.value);
                onChangeFilters({ ...filters, txnTypes: selected });
              }}
              style={{ height: "90px", fontSize: "0.8rem" }}
            >
              {meta.txn_types.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Amount Filter */}
        <div>
          <label style={{ display: "block", fontSize: "0.75rem", color: "var(--text-muted)", marginBottom: "6px" }}>
            Amount Range (₹)
          </label>
          <select
            className="select"
            value={filters.amountField}
            onChange={(e) =>
              onChangeFilters({ ...filters, amountField: e.target.value as Filters["amountField"] })
            }
            style={{ fontSize: "0.8rem", marginBottom: "6px" }}
          >
            <option value="any">Any (Debit or Credit)</option>
            <option value="debit">Debit Amount</option>
            <option value="credit">Credit Amount</option>
          </select>
          <div style={{ display: "flex", gap: "6px" }}>
            <input
              type="number"
              className="input"
              placeholder="Min ≥"
              min={0}
              value={filters.amountMin ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                onChangeFilters({ ...filters, amountMin: v === "" ? null : Number(v) });
              }}
              style={{ fontSize: "0.8rem", width: "50%" }}
            />
            <input
              type="number"
              className="input"
              placeholder="Max ≤"
              min={0}
              value={filters.amountMax ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                onChangeFilters({ ...filters, amountMax: v === "" ? null : Number(v) });
              }}
              style={{ fontSize: "0.8rem", width: "50%" }}
            />
          </div>
        </div>
      </div>
    </aside>
  );
}
