"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { API_BASE, setAuthToken } from "@/lib/api";

type Step = "email" | "otp";

function getNetworkAwareError(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) return fallback;
  const msg = err.message || "";
  if (msg === "Failed to fetch" || msg.toLowerCase().includes("networkerror")) {
    return "Cannot reach server. Start backend and check NEXT_PUBLIC_API_URL / proxy config.";
  }
  return msg;
}

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const parseApiError = async (res: Response): Promise<string> => {
    try {
      const data = await res.json();
      if (typeof data?.detail === "string" && data.detail.trim()) return data.detail;
      if (typeof data?.message === "string" && data.message.trim()) return data.message;
    } catch {
      // Fall through to text parsing.
    }
    try {
      const t = await res.text();
      if (t.trim()) return t;
    } catch {
      // Ignore text parse errors.
    }
    return `Request failed (${res.status})`;
  };

  const sendOtp = async () => {
    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail) {
      setError("Please enter your email.");
      return;
    }
    setLoading(true);
    setError(null);
    setInfo(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/send-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanEmail }),
      });
      if (!res.ok) throw new Error(await parseApiError(res));
      // Clear loading before swapping the step subtree so React does not reconcile
      // spinner + branch swap in one commit (reduces DOM/extension edge-case crashes).
      setLoading(false);
      setStep("otp");
      setInfo("If this email exists, an OTP has been sent.");
      return;
    } catch (e: unknown) {
      setError(getNetworkAwareError(e, "Could not send OTP."));
    } finally {
      setLoading(false);
    }
  };

  const verifyOtp = async () => {
    const cleanEmail = email.trim().toLowerCase();
    const cleanOtp = otp.trim();
    if (!cleanEmail || cleanOtp.length !== 6) {
      setError("Enter a valid email and 6-digit OTP.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/auth/verify-otp`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanEmail, otp: cleanOtp }),
      });
      if (!res.ok) throw new Error(await parseApiError(res));
      const data = await res.json();
      const token = typeof data?.token === "string" ? data.token : "";
      if (!token) throw new Error("Token missing in auth response.");
      setAuthToken(token);
      router.replace("/dashboard");
    } catch (e: unknown) {
      setError(getNetworkAwareError(e, "OTP verification failed."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-emerald-50/40">
      <header className="border-b border-slate-200/80 bg-white/90">
        <nav className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 py-4 sm:px-6">
          <Link href="/" className="text-sm font-semibold text-slate-800 hover:text-emerald-700">
            ← AI Neta
          </Link>
        </nav>
      </header>

      <main className="mx-auto flex min-h-[80vh] w-full max-w-4xl items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Citizen Sign In / Sign Up</h1>
          <p className="mt-2 text-sm text-slate-600">
            Use your email OTP to create an account or sign in securely.
          </p>

          {step === "email" ? (
            <div key="email-step" className="mt-6 space-y-4">
              <div>
                <label htmlFor="login-email" className="block text-sm font-medium text-slate-700">
                  Email
                </label>
                <input
                  id="login-email"
                  name="email"
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  disabled={loading}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus:border-emerald-600 focus:outline-none focus:ring-1 focus:ring-emerald-600"
                />
              </div>
              {error ? <p className="text-sm text-red-700">{error}</p> : null}
              <button
                type="button"
                onClick={() => void sendOtp()}
                disabled={loading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                {loading ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    Sending OTP...
                  </>
                ) : (
                  "Send OTP"
                )}
              </button>
            </div>
          ) : (
            <div key="otp-step" className="mt-6 space-y-4">
              <div>
                <label htmlFor="login-otp" className="block text-sm font-medium text-slate-700">
                  6-digit OTP
                </label>
                <input
                  id="login-otp"
                  name="otp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={otp}
                  onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
                  placeholder="123456"
                  disabled={loading}
                  className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-slate-900 focus:border-emerald-600 focus:outline-none focus:ring-1 focus:ring-emerald-600"
                />
              </div>
              {error ? <p className="text-sm text-red-700">{error}</p> : null}
              <button
                type="button"
                onClick={() => void verifyOtp()}
                disabled={loading}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                {loading ? (
                  <>
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    Verifying...
                  </>
                ) : (
                  "Verify OTP"
                )}
              </button>
              <button
                type="button"
                onClick={() => setStep("email")}
                disabled={loading}
                className="w-full rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                Change Email
              </button>
            </div>
          )}

          {info ? <p className="mt-4 text-sm text-emerald-700">{info}</p> : null}
        </div>
      </main>
    </div>
  );
}
