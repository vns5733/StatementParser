"use client";

import React, { useState, useRef, useEffect } from "react";
import { Meta } from "@/types";
import api from "@/lib/api";

interface DataToolsProps {
  meta?: Meta;
  customCategories: string[];
  onAddCategory: (name: string) => Promise<void>;
  onDeleteCategory: (name: string) => Promise<void>;
  onDataUploaded: () => void;
  onRecategorized: () => void;
  /** Opens the definitions editor — what each category is for. */
  onEditDefinitions: () => void;
}

/**
 * Upload, re-parse and category-registry maintenance. These were three
 * permanently expanded blocks at the top of the filter sidebar, pushing the
 * filters below the fold for anyone who only wanted to narrow the view.
 * They are occasional data-maintenance actions, so they live behind one
 * header control instead.
 */
export default function DataTools({
  meta,
  customCategories,
  onAddCategory,
  onDeleteCategory,
  onDataUploaded,
  onRecategorized,
  onEditDefinitions,
}: DataToolsProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const [newCatName, setNewCatName] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [isLoadingSample, setIsLoadingSample] = useState(false);
  const [isRecategorizing, setIsRecategorizing] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<{ type: "success" | "error"; text: string } | null>(
    null
  );
  const [recatMessage, setRecatMessage] = useState<string | null>(null);

  // Dismiss on outside click or Escape, so the popover never sits open over
  // the content it is covering.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const isEmptyDb = Boolean(meta && meta.years.length === 0);

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
        text: `Imported ${res.data.imported} transactions from ${file.name}.`,
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

  const handleRecategorize = async () => {
    try {
      setIsRecategorizing(true);
      setRecatMessage(null);
      await api.post("/transactions/recategorize");
      setRecatMessage("Successfully re-parsed all narrations.");
      onRecategorized();
    } catch (err: any) {
      setRecatMessage("Recategorization failed: " + (err?.response?.data?.detail || err.message));
    } finally {
      setIsRecategorizing(false);
    }
  };

  const handleAddCategory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCatName.trim()) return;
    try {
      await onAddCategory(newCatName.trim());
      setNewCatName("");
    } catch (err: any) {
      setUploadMessage({
        type: "error",
        text: err?.response?.data?.detail || "Failed to add category",
      });
    }
  };

  return (
    <div className="tools" ref={rootRef}>
      <button
        className="btn btn-secondary"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span aria-hidden>⚙</span>
        Data
        {/* Amber dot rather than a count: there is no "1 of 1" to report here,
            it flags that the database is still empty. */}
        {isEmptyDb && <span className="empty-state-dot" title="No statements imported yet" />}
      </button>

      {open && (
        <div className="tools-popover">
          {/* Import */}
          <section>
            <h3 className="tools-section-title">Import</h3>
            <p className="tools-note">
              Upload a .xls, .xlsx, .csv or .pdf bank statement to parse and store it.
            </p>
            <label
              className="btn btn-primary"
              style={{ width: "100%", cursor: isUploading ? "not-allowed" : "pointer" }}
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

            {/* Empty-database affordance: seed a fresh install with the sample */}
            {isEmptyDb && (
              <button
                className="btn btn-secondary"
                onClick={handleLoadSample}
                disabled={isLoadingSample}
                style={{ width: "100%", marginTop: "8px", fontSize: "0.78rem" }}
              >
                {isLoadingSample ? "Loading sample..." : "Load Sample Statement"}
              </button>
            )}

            {uploadMessage && (
              <div className={uploadMessage.type === "success" ? "tools-msg-ok" : "tools-msg-err"}>
                {uploadMessage.text}
              </div>
            )}
          </section>

          {/* Re-parse */}
          <section>
            <h3 className="tools-section-title">Recategorize</h3>
            <p className="tools-note">Re-parse all stored narrations with the latest rules.</p>
            <button
              className="btn btn-secondary"
              onClick={handleRecategorize}
              disabled={isRecategorizing}
              style={{ width: "100%", fontSize: "0.8rem" }}
            >
              {isRecategorizing ? "Re-parsing..." : "Recategorize All"}
            </button>
            {recatMessage && (
              <div
                className={recatMessage.startsWith("Successfully") ? "tools-msg-ok" : "tools-msg-err"}
              >
                {recatMessage}
              </div>
            )}
          </section>

          {/* Category registry */}
          <section>
            <h3 className="tools-section-title">Broad Categories</h3>
            <form onSubmit={handleAddCategory} style={{ display: "flex", gap: "6px" }}>
              <input
                type="text"
                className="input"
                placeholder="New category..."
                value={newCatName}
                onChange={(e) => setNewCatName(e.target.value)}
                style={{ fontSize: "0.8rem" }}
              />
              <button type="submit" className="btn btn-primary" style={{ padding: "6px 12px" }}>
                +
              </button>
            </form>
            <button
              className="btn btn-secondary"
              onClick={() => {
                setOpen(false);
                onEditDefinitions();
              }}
              style={{ width: "100%", marginTop: "8px", fontSize: "0.8rem" }}
            >
              Edit what each category is for
            </button>
            {customCategories.length > 0 && (
              <div className="tools-list">
                {customCategories.map((name) => (
                  <div key={name} className="tools-list-row">
                    <span>{name}</span>
                    <button
                      onClick={() => onDeleteCategory(name)}
                      className="link-btn link-btn-danger"
                      title={`Delete ${name}`}
                    >
                      Delete
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}