"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { API_BASE } from "@/lib/api";
import type { PublicComplaint } from "@/app/components/TransparencyMap";

const TransparencyMap = dynamic(() => import("@/app/components/TransparencyMap"), {
  ssr: false,
});

export default function TransparencyPage() {
  const [complaints, setComplaints] = useState<PublicComplaint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/api/public/complaints`, { cache: "no-store" });
        if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
        const data = await res.json();
        if (!cancelled) {
          setComplaints(Array.isArray(data?.complaints) ? data.complaints : []);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load transparency data.");
          setComplaints([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-emerald-50/40">
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <nav className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <Link href="/" className="text-sm font-semibold text-slate-800 hover:text-emerald-700">
            ← AI Neta
          </Link>
          <div className="flex items-center gap-4 text-sm">
            <Link href="/chat" className="text-slate-600 hover:text-emerald-700">
              File Complaint
            </Link>
            <Link href="/track" className="text-slate-600 hover:text-emerald-700">
              Track Complaint
            </Link>
          </div>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 lg:px-8">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          City Transparency Dashboard
        </h1>
        <p className="mt-2 text-sm text-slate-600 sm:text-base">
          Public map of registered civic complaints. Marker colors represent issue categories and
          popups show issue type, department, and current status.
        </p>

        <div className="mt-6">
          {loading ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
              Loading transparency map...
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-sm text-red-800 shadow-sm">
              Could not load map data. {error}
            </div>
          ) : complaints.length === 0 ? (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600 shadow-sm">
              No geotagged complaints available yet.
            </div>
          ) : (
            <TransparencyMap complaints={complaints} />
          )}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1">
            <span className="h-2.5 w-2.5 rounded-full bg-blue-600" /> Water
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1">
            <span className="h-2.5 w-2.5 rounded-full bg-gray-500" /> Road
          </span>
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1">
            <span className="h-2.5 w-2.5 rounded-full bg-yellow-500" /> Electricity
          </span>
        </div>
      </main>
    </div>
  );
}
