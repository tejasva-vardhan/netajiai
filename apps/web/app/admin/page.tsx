"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AdminApiError,
  AdminComplaint,
  AdminOverview,
  EvidenceReviewItem,
  SchemeReviewItem,
  approveScheme,
  decideEvidenceReview,
  getAdminOverview,
  getEvidenceReviewQueue,
  getSchemeReviewQueue,
  listAdminComplaints,
} from "../../lib/admin-api";
import {
  beginAdminSignIn,
  getAdminUser,
  isAdminOidcConfigured,
  signOutAdmin,
} from "../../lib/admin-auth";

type LoadState = "loading" | "ready" | "error";

export default function AdminPage() {
  const [configured] = useState(isAdminOidcConfigured);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState("");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [complaints, setComplaints] = useState<AdminComplaint[]>([]);
  const [mappingComplaints, setMappingComplaints] = useState<AdminComplaint[]>([]);
  const [reviewItems, setReviewItems] = useState<EvidenceReviewItem[]>([]);
  const [schemeReviewItems, setSchemeReviewItems] = useState<SchemeReviewItem[]>([]);
  const [schemeReviewAvailable, setSchemeReviewAvailable] = useState<boolean | null>(null);

  const loadData = useCallback(async (token: string) => {
    setLoadState("loading");
    setError("");
    try {
      const [overviewResult, complaintsResult, mappingResult, reviewResult] = await Promise.all([
        getAdminOverview(token),
        listAdminComplaints(token),
        listAdminComplaints(token, { executionZoneState: "mapping_in_progress" }),
        getEvidenceReviewQueue(token),
      ]);
      setOverview(overviewResult);
      setComplaints(complaintsResult.items);
      setMappingComplaints(mappingResult.items);
      setReviewItems(reviewResult.items);
      try {
        const schemeResult = await getSchemeReviewQueue(token);
        setSchemeReviewItems(schemeResult.items);
        setSchemeReviewAvailable(true);
      } catch (caught) {
        if (!(caught instanceof AdminApiError && caught.status === 403)) throw caught;
        setSchemeReviewAvailable(false);
      }
      setLoadState("ready");
    } catch (caught) {
      setLoadState("error");
      setError(caught instanceof AdminApiError ? caught.message : "Operator data could not be loaded.");
      if (caught instanceof AdminApiError && (caught.status === 401 || caught.status === 403)) {
        setAccessToken(null);
      }
    }
  }, []);

  useEffect(() => {
    if (!configured) {
      setLoadState("ready");
      return;
    }
    void getAdminUser()
      .then((user) => {
        if (user?.access_token) {
          setAccessToken(user.access_token);
          void loadData(user.access_token);
        } else {
          setLoadState("ready");
        }
      })
      .catch(() => {
        setLoadState("error");
        setError("Operator sign-in state could not be read.");
      });
  }, [configured, loadData]);

  async function review(item: EvidenceReviewItem, decision: "approve" | "reject"): Promise<void> {
    if (!accessToken) return;
    try {
      await decideEvidenceReview(accessToken, item.evidence_asset_id, decision, decision === "approve" ? "operator_approved" : "operator_rejected");
      setReviewItems((current) => current.filter((candidate) => candidate.evidence_asset_id !== item.evidence_asset_id));
    } catch (caught) {
      setError(caught instanceof AdminApiError ? caught.message : "The evidence decision could not be saved.");
    }
  }

  if (!configured) return <ConfigurationRequired />;
  if (!accessToken) return <SignInPanel onSignIn={() => void beginAdminSignIn().catch(() => setError("Operator sign-in could not be started."))} error={error} />;

  return (
    <main className="shell admin-shell">
      <header className="topbar">
        <div><p className="eyebrow">AI Neta operator</p><h1 className="admin-title">Control tower</h1></div>
        <button className="button button-secondary" type="button" onClick={() => void signOutAdmin()}>Sign out</button>
      </header>
      {error && <p className="error" role="alert">{error}</p>}
      {loadState === "loading" && <p className="lede">Operator data load ho raha hai…</p>}
      {overview && <OverviewCards overview={overview} />}
      <section className="admin-section" aria-labelledby="mapping-title">
        <div className="section-heading"><div><p className="eyebrow">Routing review</p><h2 id="mapping-title">Pending department mapping</h2></div><span className="queue-count">{mappingComplaints.length} shown</span></div>
        <p className="result-note">These complaints are accepted but remain in Mapping in progress. No contact or outbound dispatch is inferred by this queue.</p>
        <ComplaintTable complaints={mappingComplaints} />
      </section>
      <section className="admin-section" aria-labelledby="review-title">
        <div className="section-heading"><div><p className="eyebrow">Evidence safety</p><h2 id="review-title">Review queue</h2></div><span className="queue-count">{reviewItems.length} pending</span></div>
        {reviewItems.length === 0 ? <p className="result-note">Abhi uncertain evidence pending nahi hai.</p> : <div className="review-grid">{reviewItems.map((item) => <ReviewCard key={item.evidence_asset_id} item={item} onReview={review} />)}</div>}
      </section>
      <section className="admin-section" aria-labelledby="complaints-title">
        <div className="section-heading"><div><p className="eyebrow">Redacted workload</p><h2 id="complaints-title">Recent complaints</h2></div></div>
        <ComplaintTable complaints={complaints} />
      </section>
      {schemeReviewAvailable && <section className="admin-section" aria-labelledby="scheme-review-title">
        <div className="section-heading"><div><p className="eyebrow">Grounded information</p><h2 id="scheme-review-title">Scheme source review</h2></div><span className="queue-count">{schemeReviewItems.length} pending</span></div>
        {schemeReviewItems.length === 0 ? <p className="result-note">No staged scheme records are waiting for review.</p> : <div className="scheme-review-grid">{schemeReviewItems.map((item) => <SchemeReviewCard key={item.scheme_id} item={item} accessToken={accessToken} onApproved={(schemeId) => setSchemeReviewItems((current) => current.filter((candidate) => candidate.scheme_id !== schemeId))} />)}</div>}
      </section>}
    </main>
  );
}

function ConfigurationRequired() {
  return <main className="shell narrow-shell admin-shell"><p className="eyebrow">Operator sign-in</p><h1>Admin access is not enabled</h1><p className="lede">Is deployment mein OIDC configure nahi hai. Privileged data ke liye fake login ya shared secret use nahi kiya jayega.</p><div className="admin-notice"><strong>ACTION REQUIRED</strong><p>Set <code>NEXT_PUBLIC_OIDC_ISSUER</code> and <code>NEXT_PUBLIC_OIDC_CLIENT_ID</code>, register <code>/admin/auth/callback</code> with the provider, and configure the backend role claim before enabling operator access.</p></div></main>;
}

function SignInPanel({ onSignIn, error }: { onSignIn: () => void; error: string }) {
  return <main className="shell narrow-shell admin-shell"><p className="eyebrow">Operator sign-in</p><h1>Control tower mein sign in karein</h1><p className="lede">Sirf approved operator accounts ko redacted workload aur evidence review dikhega.</p><button className="button button-primary" type="button" onClick={onSignIn}>Secure sign-in</button>{error && <p className="error" role="alert">{error}</p>}</main>;
}

function OverviewCards({ overview }: { overview: AdminOverview }) {
  return <section className="admin-section" aria-labelledby="overview-title"><div className="section-heading"><div><p className="eyebrow">Live aggregate</p><h2 id="overview-title">Aaj ka workload</h2></div><span className="last-updated">{overview.last_updated_at ? formatDate(overview.last_updated_at) : "No update time"}</span></div><div className="metric-grid"><Metric label="Total complaints" value={overview.total_complaints} /><Metric label="Escalated" value={overview.escalated_count} /><Metric label="Mapping pending" value={overview.mapping_in_progress_count} /></div><div className="breakdown-grid"><Breakdown title="Status" values={overview.status_counts} /><Breakdown title="Execution zone" values={overview.execution_zone_counts} /></div></section>;
}

function Metric({ label, value }: { label: string; value: number }) { return <article className="metric-card"><span>{label}</span><strong>{value}</strong></article>; }
function Breakdown({ title, values }: { title: string; values: Record<string, number> }) { return <article className="breakdown-card"><h3>{title}</h3>{Object.entries(values).map(([key, value]) => <div className="breakdown-row" key={key}><span>{humanize(key)}</span><strong>{value}</strong></div>)}</article>; }

function ReviewCard({ item, onReview }: { item: EvidenceReviewItem; onReview: (item: EvidenceReviewItem, decision: "approve" | "reject") => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  async function decide(decision: "approve" | "reject") { setBusy(true); try { await onReview(item, decision); } finally { setBusy(false); } }
  return <article className="review-card"><div className="review-preview">{item.asset_type === "photo" ? <img src={item.preview_url} alt="Evidence preview for operator review" /> : item.asset_type === "audio" ? <audio controls src={item.preview_url} /> : <a href={item.preview_url} target="_blank" rel="noreferrer">Open video preview</a>}</div><div className="review-body"><h3>{humanize(item.asset_type)} evidence</h3><p className="result-note">Reason: {item.reason_codes.map(humanize).join(", ") || "Needs review"}</p><p className="result-note">{formatBytes(item.byte_size)} · captured {formatDate(item.captured_at)}</p><div className="actions"><button className="button button-primary" type="button" disabled={busy} onClick={() => void decide("approve")}>Approve</button><button className="button button-secondary" type="button" disabled={busy} onClick={() => void decide("reject")}>Reject</button></div></div></article>;
}

function ComplaintTable({ complaints }: { complaints: AdminComplaint[] }) {
  if (complaints.length === 0) return <p className="result-note">No redacted complaints available.</p>;
  return <div className="table-wrap"><table><thead><tr><th>Status</th><th>Issue</th><th>Zone</th><th>Escalation</th><th>Updated</th></tr></thead><tbody>{complaints.map((complaint) => <tr key={complaint.complaint_id}><td>{humanize(complaint.status)}</td><td>{complaint.issue_type ?? "Unclassified"}</td><td>{humanize(complaint.execution_zone_state)}</td><td>L{complaint.escalation_level}</td><td>{formatDate(complaint.updated_at)}</td></tr>)}</tbody></table></div>;
}

function SchemeReviewCard({ item, accessToken, onApproved }: { item: SchemeReviewItem; accessToken: string; onApproved: (schemeId: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function approve(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      await approveScheme(accessToken, item.scheme_id);
      onApproved(item.scheme_id);
    } catch (caught) {
      setError(caught instanceof AdminApiError ? caught.message : "The scheme could not be approved.");
    } finally {
      setBusy(false);
    }
  }
  return <article className="scheme-review-card"><div className="scheme-review-heading"><div><p className="result-label">{item.scheme_key} · v{item.version}</p><h3>{item.title}</h3></div><span className="queue-count">{item.language}</span></div><p className="scheme-answer">{item.answer_text}</p><div className="scheme-meta"><span>Jurisdiction: {item.jurisdiction_code ?? "All supported areas"}</span><span>Search terms: {item.search_terms}</span></div><h4>Eligibility summary</h4><pre className="eligibility-summary">{JSON.stringify(item.eligibility_summary, null, 2)}</pre><h4>Sources</h4><ul className="source-list">{item.sources.map((source) => <li key={source.source_id}><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a><span>{source.publisher} · retrieved {formatDate(source.retrieved_at)}</span><code>{source.document_hash}</code></li>)}</ul><button className="button button-primary" type="button" disabled={busy} onClick={() => void approve()}>{busy ? "Saving…" : "Approve verified content"}</button>{error && <p className="error" role="alert">{error}</p>}</article>;
}

function humanize(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function formatBytes(value: number): string { return value < 1_048_576 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1_048_576).toFixed(1)} MB`; }
function formatDate(value: string): string { const date = new Date(value); return Number.isNaN(date.valueOf()) ? "Update available" : new Intl.DateTimeFormat("hi-IN", { dateStyle: "medium", timeStyle: "short" }).format(date); }
