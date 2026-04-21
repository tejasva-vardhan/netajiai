"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { API_BASE } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

type ComplaintCard = {
  complaint_id: string;
  issue_type: string;
  location: string;
  status: string;
  created_at: string | null;
};

function prettyStatus(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "in_progress") return "In Progress";
  if (s === "resolved") return "Resolved";
  if (s === "pending") return "Pending";
  if (s === "submitted") return "Submitted";
  return status || "Unknown";
}

function prettyDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export default function DashboardPage() {
  const router = useRouter();
  const { isReady, isLoggedIn, authFetch, logout } = useAuth({
    redirectOnUnauthorizedTo: "/login",
  });
  const [items, setItems] = useState<ComplaintCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isReady) return;
    if (!isLoggedIn) {
      router.replace("/login");
      return;
    }

    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await authFetch(`${API_BASE}/api/user/complaints`, {
          cache: "no-store",
        });
        if (res.status === 401) return;
        if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) setItems(Array.isArray(data?.complaints) ? data.complaints : []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load complaints.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [authFetch, isLoggedIn, isReady, router]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-emerald-50/40">
      <header className="border-b border-slate-200/80 bg-white/90">
        <nav className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="text-sm font-semibold text-slate-800 hover:text-emerald-700">
            ← AI Neta
          </Link>
          <div className="flex items-center gap-2">
            <Link
              href="/chat"
              className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700"
            >
              ➕ File New Complaint
            </Link>
            <button
              type="button"
              onClick={() => logout("/")}
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Logout
            </button>
          </div>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">My Complaints</h1>
        <p className="mt-2 text-sm text-slate-600">Track all your registered issues in one place.</p>

        {loading ? <p className="mt-6 text-sm text-slate-500">Loading dashboard...</p> : null}
        {error ? <p className="mt-6 text-sm text-red-700">{error}</p> : null}

        {!loading && !error ? (
          items.length === 0 ? (
            <div className="mt-6 rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
              No complaints found for this account.
            </div>
          ) : (
            <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => {
                const status = prettyStatus(c.status);
                const statusClass =
                  status === "Resolved"
                    ? "bg-green-50 text-green-800 border-green-200"
                    : "bg-amber-50 text-amber-800 border-amber-200";
                return (
                  <div
                    key={c.complaint_id}
                    className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h2 className="text-base font-semibold text-slate-900">{c.issue_type || "General Issue"}</h2>
                      <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusClass}`}>
                        {status}
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-slate-700">{c.location || "Location unavailable"}</p>
                    <p className="mt-3 text-xs text-slate-500">Date: {prettyDate(c.created_at)}</p>
                    <p className="mt-1 font-mono text-xs text-slate-500">{c.complaint_id}</p>
                  </div>
                );
              })}
            </div>
          )
        ) : null}
      </main>
    </div>
  );
}
