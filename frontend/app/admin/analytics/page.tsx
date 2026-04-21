"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { API_BASE } from "@/lib/api";

const ADMIN_API_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY?.trim();

function adminHeaders(): HeadersInit {
  return ADMIN_API_KEY ? { "x-api-key": ADMIN_API_KEY } : {};
}

type DepartmentStat = {
  department_name: string;
  total_complaints: number;
  stuck_at_l1: number;
  stuck_at_l2: number;
  stuck_at_l3: number;
};

type AnalyticsResponse = {
  total_complaints: number;
  status_breakdown: Record<string, number>;
  department_stats: DepartmentStat[];
};

const STATUS_COLORS: Record<string, string> = {
  pending: "#f59e0b",
  in_progress: "#0284c7",
  resolved: "#16a34a",
  submitted: "#64748b",
};

function prettyStatus(s: string): string {
  if (s === "in_progress") return "In Progress";
  if (s === "submitted") return "Submitted";
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export default function AdminAnalyticsPage() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/api/admin/analytics`, {
          cache: "no-store",
          headers: adminHeaders(),
        });
        if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
        const json = (await res.json()) as AnalyticsResponse;
        if (!cancelled) setData(json);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load analytics.");
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const statusChartData = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.status_breakdown).map(([status, count]) => ({
      name: prettyStatus(status),
      value: count,
      color: STATUS_COLORS[status] ?? "#94a3b8",
    }));
  }, [data]);

  const pendingActions = (data?.status_breakdown.pending ?? 0) + (data?.status_breakdown.in_progress ?? 0);
  const resolvedCount = data?.status_breakdown.resolved ?? 0;
  const resolutionRate =
    data && data.total_complaints > 0 ? Math.round((resolvedCount / data.total_complaints) * 100) : 0;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white shadow-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-4">
          <div>
            <h1 className="text-xl font-semibold text-slate-800">AI NETA — Admin Analytics</h1>
            <p className="text-sm text-slate-500">SLA and department performance dashboard</p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/admin"
              className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Table View
            </Link>
            <Link
              href="/"
              className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700"
            >
              Back to chat
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {error ? (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        ) : null}

        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-sm text-slate-500">Total Complaints</p>
            <p className="mt-2 text-3xl font-bold text-slate-900">{data?.total_complaints ?? "—"}</p>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
            <p className="text-sm text-amber-800">Pending Actions</p>
            <p className="mt-2 text-3xl font-bold text-amber-900">{loading ? "…" : pendingActions}</p>
          </div>
          <div className="rounded-xl border border-green-200 bg-green-50 p-5 shadow-sm">
            <p className="text-sm text-green-800">Resolved</p>
            <p className="mt-2 text-3xl font-bold text-green-900">{loading ? "…" : resolvedCount}</p>
          </div>
          <div className="rounded-xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
            <p className="text-sm text-sky-800">Resolution Rate</p>
            <p className="mt-2 text-3xl font-bold text-sky-900">{loading ? "…" : `${resolutionRate}%`}</p>
          </div>
        </section>

        <section className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-base font-semibold text-slate-900">Status Breakdown</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={statusChartData} dataKey="value" nameKey="name" outerRadius={110} label>
                    {statusChartData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-3 text-base font-semibold text-slate-900">Complaints by Department</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data?.department_stats ?? []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="department_name" angle={-20} textAnchor="end" height={75} interval={0} />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="total_complaints" name="Total" fill="#0f766e" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
