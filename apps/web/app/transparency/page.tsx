"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getPublicTransparency, PublicApiError, PublicTransparency } from "../../lib/public-api";

export default function TransparencyPage() {
  const [data, setData] = useState<PublicTransparency | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getPublicTransparency()
      .then(setData)
      .catch((reason: unknown) => {
        setError(reason instanceof PublicApiError ? reason.message : "Public transparency could not be loaded.");
      });
  }, []);

  return (
    <main className="shell narrow-shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="AI Neta home">AI NETA</Link>
        <Link className="quiet-link" href="/track">Shikayat dekhein</Link>
      </header>
      <section className="page-heading">
        <p className="eyebrow">Public accountability</p>
        <h1>AI Neta ka saaf hisaab</h1>
        <p className="lede">Yahan sirf aggregate numbers dikhte hain. Kisi citizen ka naam, complaint text ya exact location nahi.</p>
      </section>
      {error && <div className="admin-notice" role="status"><strong>ACTION REQUIRED</strong><p>{error}</p><p>Public transparency tabhi khulegi jab approved redaction policy aur deployment flag set honge.</p></div>}
      {data && <>
        <section className="admin-section" aria-labelledby="summary-title" aria-live="polite">
          <div className="section-heading"><div><p className="eyebrow">Aggregate view</p><h2 id="summary-title">Abhi ka public snapshot</h2></div><span className="last-updated">Updated {formatDate(data.last_updated_at ?? data.generated_at)}</span></div>
          <div className="metric-grid">
            <Metric label="Total complaints" value={data.total_complaints} />
            <Metric label="Escalated" value={data.escalated_count} />
            <Metric label="Mapping pending" value={data.mapping_in_progress_count} />
          </div>
        </section>
        <section className="breakdown-grid" aria-label="Public status breakdown">
          <Breakdown title="Status" values={data.status_counts} />
          <Breakdown title="Execution zone" values={data.execution_zone_counts} />
        </section>
        <p className="result-note">Policy version: <code>{data.policy_version}</code>. Yeh snapshot department contacts, personal details aur case-level evidence publish nahi karta.</p>
      </>}
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <article className="metric-card"><span>{label}</span><strong>{value}</strong></article>;
}

function Breakdown({ title, values }: { title: string; values: Record<string, number> }) {
  return <article className="breakdown-card"><h3>{title}</h3>{Object.entries(values).map(([key, value]) => <div className="breakdown-row" key={key}><span>{humanize(key)}</span><strong>{value}</strong></div>)}</article>;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "Update available" : new Intl.DateTimeFormat("hi-IN", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
