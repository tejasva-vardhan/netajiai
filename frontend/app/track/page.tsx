"use client";

import Link from "next/link";
import { useCallback, useState } from "react";

import { API_BASE } from "@/lib/api";

type EscalationLevel = {
  role: string;
  email: string | null;
};

type TrackResponse = {
  complaint_id: string;
  status: string;
  issue_type: string;
  created_at: string | null;
  department: string;
  escalation_level: number;
  current_level_label: string;
  escalation_matrix: {
    L1: EscalationLevel;
    L2: EscalationLevel;
    L3: EscalationLevel;
  };
};

function formatStatus(raw: string): string {
  const s = (raw || "").toLowerCase();
  if (s === "resolved") return "Resolved";
  if (s === "in_progress") return "In progress";
  if (s === "pending") return "Pending";
  if (s === "submitted") return "Submitted";
  return raw.replace(/_/g, " ") || "Unknown";
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function TrackComplaintPage() {
  const [idInput, setIdInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TrackResponse | null>(null);

  const track = useCallback(async () => {
    const id = idInput.trim();
    setError(null);
    setData(null);

    if (!id) {
      setError("Please enter a complaint ID.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(
        `${API_BASE}/api/track/${encodeURIComponent(id)}`,
        { method: "GET", headers: { Accept: "application/json" } }
      );
      if (res.status === 404) {
        setError(
          "No complaint found for this ID. Check the ID from your confirmation message and try again."
        );
        return;
      }
      if (!res.ok) {
        const text = await res.text();
        setError(text || `Request failed (${res.status}). Please try again later.`);
        return;
      }
      const json = (await res.json()) as TrackResponse;
      setData(json);
    } catch {
      setError("Could not reach the server. Check your connection and try again.");
    } finally {
      setLoading(false);
    }
  }, [idInput]);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-emerald-50/30">
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <nav className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="text-sm font-semibold text-slate-800 hover:text-emerald-700">
            ← AI Neta
          </Link>
          <Link
            href="/chat"
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700"
          >
            File a complaint
          </Link>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-2xl px-4 py-10 sm:px-6">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          Track your complaint
        </h1>
        <p className="mt-2 text-sm text-slate-600">
          Enter the complaint ID you received after registering through the chat assistant.
        </p>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1">
            <label htmlFor="complaint-id" className="block text-sm font-medium text-slate-700">
              Complaint ID
            </label>
            <input
              id="complaint-id"
              type="text"
              value={idInput}
              onChange={(e) => setIdInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void track();
              }}
              placeholder="e.g. CMP-2026-XXXX"
              autoComplete="off"
              className="mt-1 w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
            />
          </div>
          <button
            type="button"
            onClick={() => void track()}
            disabled={loading}
            className="rounded-xl bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Tracking…" : "Track"}
          </button>
        </div>

        {error ? (
          <div
            role="alert"
            className="mt-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
          >
            {error}
          </div>
        ) : null}

        {data ? (
          <div className="mt-10 space-y-8">
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h2 className="text-lg font-semibold text-slate-900">Progress</h2>
              <p className="mt-1 text-sm text-slate-500">
                <span className="font-medium text-slate-700">{data.complaint_id}</span>
                {data.issue_type ? (
                  <>
                    {" "}
                    · <span className="text-slate-600">{data.issue_type}</span>
                  </>
                ) : null}
              </p>

              <ol className="relative mt-8 space-y-0">
                <li className="flex gap-4 pb-8">
                  <div className="flex flex-col items-center">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-sm font-bold text-white">
                      1
                    </span>
                    <span className="mt-1 w-px flex-1 min-h-[2rem] bg-emerald-200" aria-hidden />
                  </div>
                  <div className="pb-2 pt-0.5">
                    <h3 className="font-semibold text-slate-900">Complaint registered</h3>
                    <p className="mt-1 text-sm text-slate-600">{formatDate(data.created_at)}</p>
                  </div>
                </li>

                <li className="flex gap-4 pb-8">
                  <div className="flex flex-col items-center">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-sm font-bold text-white">
                      2
                    </span>
                    <span className="mt-1 w-px flex-1 min-h-[2rem] bg-emerald-200" aria-hidden />
                  </div>
                  <div className="pb-2 pt-0.5">
                    <h3 className="font-semibold text-slate-900">Assigned to department</h3>
                    <p className="mt-1 text-sm text-slate-600">
                      {data.department?.trim() ? data.department : "Department routing in progress"}
                    </p>
                  </div>
                </li>

                <li className="flex gap-4 pb-8">
                  <div className="flex flex-col items-center">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-600 text-sm font-bold text-white">
                      3
                    </span>
                    <span className="mt-1 w-px flex-1 min-h-[2rem] bg-emerald-200" aria-hidden />
                  </div>
                  <div className="pb-2 pt-0.5">
                    <h3 className="font-semibold text-slate-900">Current level</h3>
                    <p className="mt-1 text-sm text-slate-600">
                      Level {data.escalation_level} — {data.current_level_label}
                    </p>
                  </div>
                </li>

                <li className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-800 text-sm font-bold text-white">
                      4
                    </span>
                  </div>
                  <div className="pt-0.5">
                    <h3 className="font-semibold text-slate-900">Status</h3>
                    <p className="mt-1 text-sm text-slate-600">{formatStatus(data.status)}</p>
                  </div>
                </li>
              </ol>
            </section>

            <section className="rounded-2xl border border-slate-200 bg-slate-50/80 p-6">
              <h2 className="text-base font-semibold text-slate-900">Escalation matrix</h2>
              <p className="mt-1 text-xs text-slate-500">
                Who handles your complaint at each level (contacts configured for your city and issue
                type).
              </p>
              <ul className="mt-4 space-y-3">
                {(["L1", "L2", "L3"] as const).map((key) => {
                  const row = data.escalation_matrix[key];
                  return (
                    <li
                      key={key}
                      className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm"
                    >
                      <div className="font-semibold text-emerald-800">{key}</div>
                      <div className="mt-0.5 text-slate-700">{row.role}</div>
                      <div className="mt-1 font-mono text-xs text-slate-600 break-all">
                        {row.email ?? "—"}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          </div>
        ) : null}
      </main>
    </div>
  );
}
