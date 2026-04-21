"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { API_BASE } from "@/lib/api";

const COMPLAINTS_LIST_URL = `${API_BASE}/api/complaints`;
const CONFIG_URL = `${API_BASE}/api/config`;
const ADMIN_API_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY?.trim();

function adminHeaders(extra?: HeadersInit): HeadersInit {
  const base: Record<string, string> = {};
  if (ADMIN_API_KEY) base["x-api-key"] = ADMIN_API_KEY;
  if (extra) {
    return { ...base, ...(extra as Record<string, string>) };
  }
  return base;
}

function fetchErrorMessage(url: string, e: unknown): string {
  if (e instanceof TypeError) {
    return (
      `Cannot reach the API at ${url}. ` +
      `From the project root, run: py -m uvicorn main:app --reload --port 8000 ` +
      `(needs a valid .env with DATABASE_URL; PostgreSQL must be up). ` +
      `GROQ_API_KEY is only required for /chat, not for this admin list. ` +
      `If the API is on another host/port, set NEXT_PUBLIC_API_URL in frontend/.env.local and restart Next.js.`
    );
  }
  if (e instanceof Error) return e.message;
  return "Request failed";
}

type ComplaintRow = {
  complaint_id: string;
  created_at: string | null;
  department: string;
  issue_type: string;
  routed_email: string;
  level_1_email: string;
  level_2_email: string;
  level_3_email: string;
  severity: string;
  escalation_level: number;
  location: string;
  latitude: number | null;
  longitude: number | null;
  description: string;
  status: string;
  photo_path: string | null;
  photo_url: string | null;
  source: "database" | "json";
};

type StatusValue = "pending" | "in_progress" | "resolved";

function statusForSelect(dbStatus: string): StatusValue {
  const s = (dbStatus || "").toLowerCase();
  if (s === "submitted") return "pending";
  if (s === "pending" || s === "in_progress" || s === "resolved") return s;
  return "pending";
}

function formatDate(iso: string | null) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function currentEscalationLabel(level: number | undefined | null): string {
  if (level === undefined || level === null) return "—";
  const n = Number(level);
  if (Number.isNaN(n)) return "—";
  const map: Record<number, string> = {
    1: "Level 1 (Local)",
    2: "Level 2 (Zonal)",
    3: "Level 3 (State)",
  };
  return map[n] ?? `Level ${n}`;
}

function EscalationMatrixBadges({ row }: { row: ComplaintRow }) {
  const l1 = row.level_1_email || row.routed_email || "";
  const l2 = row.level_2_email || "";
  const l3 = row.level_3_email || "";
  const levels: { tag: string; email: string; bar: string }[] = [
    { tag: "L1", email: l1, bar: "border-amber-200 bg-amber-50 text-amber-950" },
    { tag: "L2", email: l2, bar: "border-sky-200 bg-sky-50 text-sky-950" },
    { tag: "L3", email: l3, bar: "border-violet-200 bg-violet-50 text-violet-950" },
  ];
  return (
    <div className="flex min-w-[200px] max-w-[260px] flex-col gap-1">
      {levels.map(({ tag, email, bar }) => (
        <div
          key={tag}
          className={`flex items-start gap-2 rounded-md border px-2 py-1.5 text-[11px] leading-snug ${bar}`}
        >
          <span className="shrink-0 rounded bg-white/80 px-1.5 py-0.5 font-bold tabular-nums text-slate-700 shadow-sm">
            {tag}
          </span>
          <span className="break-all font-mono text-[10px] text-slate-800">
            {email || "—"}
          </span>
        </div>
      ))}
      <p className="mt-0.5 text-[9px] leading-tight text-slate-400">
        Mapped targets (reference). SMTP still goes to the dev inbox — see banner.
      </p>
    </div>
  );
}

export default function AdminDashboardPage() {
  const [complaints, setComplaints] = useState<ComplaintRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  /** Resolved dev inbox for the banner; `null` = still loading */
  const [devSafeInbox, setDevSafeInbox] = useState<string | null>(null);

  const loadComplaints = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(COMPLAINTS_LIST_URL, {
        cache: "no-store",
        headers: adminHeaders(),
      });
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      const data = await res.json();
      setComplaints(Array.isArray(data.complaints) ? data.complaints : []);
    } catch (e) {
      setError(fetchErrorMessage(COMPLAINTS_LIST_URL, e));
      setComplaints([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadComplaints();
  }, [loadComplaints]);

  useEffect(() => {
    let cancelled = false;
    const envFallback = process.env.NEXT_PUBLIC_DEV_INBOX?.trim();

    (async () => {
      try {
        const res = await fetch(CONFIG_URL, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: unknown = await res.json();
        const v =
          data &&
          typeof data === "object" &&
          "dev_safe_inbox" in data &&
          typeof (data as { dev_safe_inbox: unknown }).dev_safe_inbox === "string"
            ? (data as { dev_safe_inbox: string }).dev_safe_inbox.trim()
            : "";
        if (!cancelled) {
          setDevSafeInbox(v || envFallback || "");
        }
      } catch {
        if (!cancelled) {
          setDevSafeInbox(envFallback || "");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleStatusChange = async (complaintId: string, newStatus: StatusValue) => {
    setUpdatingId(complaintId);
    try {
      const res = await fetch(`${API_BASE}/api/complaints/${encodeURIComponent(complaintId)}`, {
        method: "PATCH",
        headers: adminHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ status: newStatus }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      setComplaints((prev) =>
        prev.map((c) =>
          c.complaint_id === complaintId ? { ...c, status: newStatus } : c
        )
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : "Update failed");
      await loadComplaints();
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white shadow-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-800">AI NETA — Admin</h1>
            <p className="text-sm text-slate-500">Complaint management dashboard</p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/admin/analytics"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              View Analytics
            </Link>
            <button
              type="button"
              onClick={() => loadComplaints()}
              disabled={loading}
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              Refresh
            </button>
            <Link
              href="/"
              className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700"
            >
              Back to chat
            </Link>
          </div>
        </div>
      </header>

      <div className="border-b border-amber-200 bg-amber-50">
        <div className="mx-auto max-w-7xl px-4 py-3 text-sm text-amber-950">
          {devSafeInbox === null ? (
            <p className="text-amber-800/90">Loading dev inbox configuration…</p>
          ) : devSafeInbox ? (
            <p className="font-medium">
              ⚠️ DEVELOPMENT MODE: All outbound emails are currently locked and routed to{" "}
              <span className="font-mono">{devSafeInbox}</span>
            </p>
          ) : (
            <p className="font-medium">
              ⚠️ DEVELOPMENT MODE: Outbound emails are locked to the developer inbox. Start the API
              and ensure <code className="rounded bg-amber-100/80 px-1 text-xs">GET /api/config</code>{" "}
              is reachable, or set <code className="rounded bg-amber-100/80 px-1 text-xs">NEXT_PUBLIC_DEV_INBOX</code>{" "}
              in <code className="rounded bg-amber-100/80 px-1 text-xs">frontend/.env.local</code>.
            </p>
          )}
          <p className="mt-1 text-xs text-amber-900/85">
            The escalation matrix shows intended L1–L3 recipients from the database; delivery is not
            sent to those government addresses while this mode is active. The address above matches{" "}
            <code className="rounded bg-amber-100/80 px-[3px] text-[11px]">DEV_SAFE_INBOX</code> on the
            backend.
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            <p className="whitespace-pre-wrap">{error}</p>
            <p className="mt-2 text-xs text-red-700/90">
              Request URL: <code className="rounded bg-red-100/80 px-1">{COMPLAINTS_LIST_URL}</code>
            </p>
            <button
              type="button"
              onClick={() => loadComplaints()}
              className="mt-3 rounded-md border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-900 hover:bg-red-50"
            >
              Retry
            </button>
          </div>
        )}

        {loading && complaints.length === 0 ? (
          <p className="text-slate-500">Loading complaints…</p>
        ) : complaints.length === 0 ? (
          <p className="text-slate-500">No complaints found.</p>
        ) : (
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1580px] text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-100/80 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    <th className="px-4 py-3">Complaint ID</th>
                    <th className="px-4 py-3">Date</th>
                    <th className="px-4 py-3">Department</th>
                    <th className="px-4 py-3">Issue type</th>
                    <th className="px-4 py-3">Severity</th>
                    <th className="px-4 py-3 min-w-[220px]">Escalation Matrix</th>
                    <th className="px-4 py-3 whitespace-nowrap">Current Level</th>
                    <th className="px-4 py-3">Location</th>
                    <th className="px-4 py-3">Map</th>
                    <th className="px-4 py-3 min-w-[200px]">Description</th>
                    <th className="px-4 py-3">Photo</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {complaints.map((row) => {
                    const photoHref =
                      row.photo_url != null ? `${API_BASE}${row.photo_url}` : null;
                    const hasCoords =
                      typeof row.latitude === "number" &&
                      typeof row.longitude === "number";
                    const mapHref = hasCoords
                      ? `https://www.google.com/maps?q=${row.latitude},${row.longitude}`
                      : null;
                    const canPatch = row.source === "database";
                    const selectValue = statusForSelect(row.status);

                    return (
                      <tr key={row.complaint_id} className="hover:bg-slate-50/80">
                        <td className="px-4 py-3 font-mono text-xs text-slate-800">
                          {row.complaint_id}
                          {row.source === "json" && (
                            <span className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-normal text-amber-800">
                              JSON only
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-slate-600">
                          {formatDate(row.created_at)}
                        </td>
                        <td className="px-4 py-3 text-slate-700">{row.department || "—"}</td>
                        <td className="px-4 py-3 text-slate-700">{row.issue_type || "—"}</td>
                        <td className="px-4 py-3 text-slate-700">{row.severity ?? "—"}</td>
                        <td className="px-4 py-3 align-top">
                          <EscalationMatrixBadges row={row} />
                        </td>
                        <td className="px-4 py-3 align-top text-slate-800">
                          <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-800">
                            {currentEscalationLabel(row.escalation_level)}
                          </span>
                        </td>
                        <td className="px-4 py-3 max-w-[160px] truncate text-slate-700" title={row.location}>
                          {row.location || "—"}
                        </td>
                        <td className="px-4 py-3">
                          {mapHref ? (
                            <div className="space-y-1">
                              <a
                                href={mapHref}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-block rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
                              >
                                View on Map
                              </a>
                              <div className="text-[11px] text-slate-500 font-mono">
                                {row.latitude?.toFixed(6)}, {row.longitude?.toFixed(6)}
                              </div>
                            </div>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 max-w-[280px] text-slate-600" title={row.description}>
                          <span className="line-clamp-3">{row.description || "—"}</span>
                        </td>
                        <td className="px-4 py-3">
                          {photoHref ? (
                            <a
                              href={photoHref}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-medium text-emerald-600 hover:text-emerald-800 hover:underline"
                            >
                              View photo
                            </a>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {canPatch ? (
                            <select
                              value={selectValue}
                              disabled={updatingId === row.complaint_id}
                              onChange={(e) =>
                                handleStatusChange(
                                  row.complaint_id,
                                  e.target.value as StatusValue
                                )
                              }
                              className="w-full min-w-[140px] rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-800 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 disabled:opacity-50"
                            >
                              <option value="pending">Pending</option>
                              <option value="in_progress">In Progress</option>
                              <option value="resolved">Resolved</option>
                            </select>
                          ) : (
                            <span className="text-xs text-slate-500" title="Not in database; status not editable">
                              {row.status || "—"}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
