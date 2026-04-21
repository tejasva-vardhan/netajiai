"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { API_BASE } from "@/lib/api";
const ADMIN_API_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY?.trim();

function adminHeaders(extra?: HeadersInit): HeadersInit {
  const base: Record<string, string> = {};
  if (ADMIN_API_KEY) base["x-api-key"] = ADMIN_API_KEY;
  return extra ? { ...base, ...(extra as Record<string, string>) } : base;
}

type CityRow = {
  id: number;
  name: string;
  state_id: number;
  state_name: string | null;
};

type DeptRow = {
  id: number;
  name: string;
  keyword: string;
};

type OfficerRoute = {
  id: number;
  city_id: number;
  city_name: string;
  state_name: string;
  department_id: number;
  department_name: string;
  department_keyword: string;
  level_1_email: string;
  level_2_email: string;
  level_3_email: string;
};

export default function SuperAdminPage() {
  const [cities, setCities] = useState<CityRow[]>([]);
  const [departments, setDepartments] = useState<DeptRow[]>([]);
  const [officers, setOfficers] = useState<OfficerRoute[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [formCityId, setFormCityId] = useState<string>("");
  const [formDeptId, setFormDeptId] = useState<string>("");
  const [formL1, setFormL1] = useState("");
  const [formL2, setFormL2] = useState("");
  const [formL3, setFormL3] = useState("");

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cRes, dRes, oRes] = await Promise.all([
        fetch(`${API_BASE}/api/superadmin/cities`, { headers: adminHeaders() }),
        fetch(`${API_BASE}/api/superadmin/departments`, { headers: adminHeaders() }),
        fetch(`${API_BASE}/api/superadmin/officers`, { headers: adminHeaders() }),
      ]);
      if (!cRes.ok) throw new Error(await cRes.text());
      if (!dRes.ok) throw new Error(await dRes.text());
      if (!oRes.ok) throw new Error(await oRes.text());
      const cJson = await cRes.json();
      const dJson = await dRes.json();
      const oJson = await oRes.json();
      setCities(Array.isArray(cJson.cities) ? cJson.cities : []);
      setDepartments(Array.isArray(dJson.departments) ? dJson.departments : []);
      setOfficers(Array.isArray(oJson.officers) ? oJson.officers : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
      setCities([]);
      setDepartments([]);
      setOfficers([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleAssignOfficer = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    const cid = parseInt(formCityId, 10);
    const did = parseInt(formDeptId, 10);
    if (!cid || !did) {
      setFormError("Please select both city and department.");
      return;
    }
    const l1 = formL1.trim();
    const l2 = formL2.trim();
    const l3 = formL3.trim();
    const hasAny = [l1, l2, l3].some((x) => x.length > 0);
    if (!hasAny) {
      setFormError("Enter at least one escalation email (L1, L2, or L3).");
      return;
    }
    const valid = (s: string) => !s || s.includes("@");
    if (!valid(l1) || !valid(l2) || !valid(l3)) {
      setFormError("Each non-empty email must contain @.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/api/superadmin/officers`, {
        method: "POST",
        headers: adminHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          city_id: cid,
          department_id: did,
          level_1_email: l1 || null,
          level_2_email: l2 || null,
          level_3_email: l3 || null,
        }),
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      setFormL1("");
      setFormL2("");
      setFormL3("");
      await loadAll();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-100">
      <header className="sticky top-0 z-10 border-b border-slate-700 bg-slate-800 text-white shadow-md">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">AI NETA — Super Admin</h1>
            <p className="text-xs text-slate-300">Platform setup · Cities & officer routing</p>
          </div>
          <nav className="flex flex-wrap gap-3 text-sm">
            <Link href="/" className="text-slate-200 underline-offset-2 hover:underline">
              Citizen chat
            </Link>
            <Link href="/admin" className="text-slate-200 underline-offset-2 hover:underline">
              Officer dashboard
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl space-y-10 px-4 py-8">
        {loading && (
          <p className="text-sm text-slate-600">Loading platform data…</p>
        )}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            {error}
          </div>
        )}

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">City management</h2>
          <p className="mt-1 text-sm text-slate-600">
            Active cities on the platform (seed new rows via DB or future “add city” API).
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-4 font-medium">ID</th>
                  <th className="py-2 pr-4 font-medium">City</th>
                  <th className="py-2 font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {cities.map((c) => (
                  <tr key={c.id} className="border-b border-slate-100">
                    <td className="py-2 pr-4 font-mono text-xs text-slate-600">{c.id}</td>
                    <td className="py-2 pr-4 text-slate-900">{c.name}</td>
                    <td className="py-2 text-slate-700">{c.state_name ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {cities.length === 0 && !loading && (
              <p className="mt-2 text-sm text-slate-500">No cities found. Run <code className="rounded bg-slate-100 px-1">py seed.py</code> on the backend.</p>
            )}
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Officer onboarding</h2>
          <p className="mt-1 text-sm text-slate-600">
            Assign or update the escalation chain (L1 local, L2 zonal, L3 state) for a department in a city.
          </p>
          <form onSubmit={handleAssignOfficer} className="mt-4 flex max-w-3xl flex-col gap-4 sm:flex-row sm:flex-wrap sm:items-end">
            <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-sm">
              <span className="text-slate-600">City</span>
              <select
                value={formCityId}
                onChange={(e) => setFormCityId(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900"
                required
              >
                <option value="">Select city…</option>
                {cities.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.name} ({c.state_name})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm">
              <span className="text-slate-600">Department</span>
              <select
                value={formDeptId}
                onChange={(e) => setFormDeptId(e.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900"
                required
              >
                <option value="">Select department…</option>
                {departments.map((d) => (
                  <option key={d.id} value={String(d.id)}>
                    {d.name} ({d.keyword})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[220px] flex-[2] flex-col gap-1 text-sm">
              <span className="text-slate-600">L1 email (local)</span>
              <input
                type="email"
                value={formL1}
                onChange={(e) => setFormL1(e.target.value)}
                placeholder="je.dept@city.gov.in"
                className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900"
              />
            </label>
            <label className="flex min-w-[220px] flex-[2] flex-col gap-1 text-sm">
              <span className="text-slate-600">L2 email (zonal)</span>
              <input
                type="email"
                value={formL2}
                onChange={(e) => setFormL2(e.target.value)}
                placeholder="ae.zone@city.gov.in"
                className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900"
              />
            </label>
            <label className="flex min-w-[220px] flex-[2] flex-col gap-1 text-sm">
              <span className="text-slate-600">L3 email (state)</span>
              <input
                type="email"
                value={formL3}
                onChange={(e) => setFormL3(e.target.value)}
                placeholder="secretary@state.gov.in"
                className="rounded-lg border border-slate-300 px-3 py-2 text-slate-900"
              />
            </label>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-slate-800 px-5 py-2 text-sm font-medium text-white hover:bg-slate-900 disabled:opacity-50"
            >
              {submitting ? "Saving…" : "Save mapping"}
            </button>
          </form>
          {formError && (
            <p className="mt-2 text-sm text-red-600">{formError}</p>
          )}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-base font-semibold text-slate-900">Active officer routes</h2>
          <p className="mt-1 text-sm text-slate-600">
            All department inboxes configured per city (used for complaint email routing).
          </p>
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-slate-500">
                  <th className="py-2 pr-4 font-medium">City</th>
                  <th className="py-2 pr-4 font-medium">State</th>
                  <th className="py-2 pr-4 font-medium">Department</th>
                  <th className="py-2 pr-2 font-medium">L1</th>
                  <th className="py-2 pr-2 font-medium">L2</th>
                  <th className="py-2 font-medium">L3</th>
                </tr>
              </thead>
              <tbody>
                {officers.map((o) => (
                  <tr key={o.id} className="border-b border-slate-100">
                    <td className="py-2 pr-4 text-slate-900">{o.city_name}</td>
                    <td className="py-2 pr-4 text-slate-600">{o.state_name || "—"}</td>
                    <td className="py-2 pr-4 text-slate-800">
                      {o.department_name}
                      <span className="ml-1 text-xs text-slate-400">({o.department_keyword})</span>
                    </td>
                    <td className="py-2 font-mono text-xs text-slate-700">{o.level_1_email || "—"}</td>
                    <td className="py-2 font-mono text-xs text-slate-700">{o.level_2_email || "—"}</td>
                    <td className="py-2 font-mono text-xs text-slate-700">{o.level_3_email || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {officers.length === 0 && !loading && (
              <p className="mt-2 text-sm text-slate-500">No officer mappings yet. Use the form above or run <code className="rounded bg-slate-100 px-1">py seed.py</code>.</p>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
