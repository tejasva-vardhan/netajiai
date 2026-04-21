 "use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/useAuth";

function ActionCard({
  href,
  title,
  description,
  icon,
  primary = false,
}: {
  href: string;
  title: string;
  description: string;
  icon: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group rounded-2xl border p-6 sm:p-8 shadow-sm transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600 focus-visible:ring-offset-2 ${
        primary
          ? "border-emerald-200 bg-emerald-50 hover:bg-emerald-100/70 hover:shadow-md"
          : "border-slate-200 bg-white hover:border-emerald-200 hover:shadow-md"
      }`}
    >
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-600 text-xl text-white">
        <span aria-hidden>{icon}</span>
      </div>
      <h3 className="text-xl font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{description}</p>
      <p className="mt-6 inline-flex items-center gap-2 text-sm font-medium text-emerald-700 group-hover:text-emerald-800">
        Continue
        <span aria-hidden>→</span>
      </p>
    </Link>
  );
}

export default function LandingPage() {
  const { isLoggedIn, logout } = useAuth();
  const [isHydrated, setIsHydrated] = useState(false);
  const complaintCtaHref = isHydrated && isLoggedIn ? "/chat" : "/login";

  useEffect(() => {
    setIsHydrated(true);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-white to-emerald-50/40">
      <header className="border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <nav className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <Link href="/" className="flex items-center gap-2 text-slate-900">
            <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-600 text-sm font-bold text-white">
              AI
            </span>
            <span className="text-lg font-semibold tracking-tight">AI Neta</span>
          </Link>
          <div className="flex items-center gap-4 sm:gap-6 text-sm font-medium text-slate-600">
            <Link href="/transparency" className="hover:text-emerald-700 transition-colors">
              Transparency Map
            </Link>
            {isHydrated && isLoggedIn ? (
              <Link href="/dashboard" className="hover:text-emerald-700 transition-colors">
                My Dashboard
              </Link>
            ) : (
              <Link href="/track" className="hover:text-emerald-700 transition-colors">
                Track Complaint
              </Link>
            )}
            {!isHydrated || !isLoggedIn ? (
              <Link href="/login" className="hover:text-emerald-700 transition-colors">
                Login
              </Link>
            ) : (
              <button
                type="button"
                onClick={() => logout("/")}
                className="hover:text-emerald-700 transition-colors"
              >
                Logout
              </button>
            )}
            <Link
              href="/admin"
              className="rounded-lg border border-slate-300 px-3 py-1.5 hover:border-emerald-600 hover:text-emerald-700 transition-colors"
            >
              Admin Login
            </Link>
          </div>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-6xl px-4 pb-16 pt-12 sm:px-6 sm:pt-16 lg:px-8">
        <section className="mx-auto max-w-3xl text-center">
          <p className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-emerald-700">
            Trusted Civic Platform
          </p>
          <h1 className="mt-5 text-balance text-3xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            AI Neta: Aapka Digital Janpratinidhi
          </h1>
          <p className="mt-5 text-pretty text-base leading-7 text-slate-600 sm:text-lg">
            Register local civic complaints, track progress transparently, and stay connected with
            public service resolution workflows through one secure, citizen-first platform.
          </p>
        </section>

        <section className="mx-auto mt-10 grid max-w-4xl grid-cols-1 gap-5 sm:mt-12 sm:grid-cols-2">
          <ActionCard
            href={complaintCtaHref}
            title="File a New Complaint"
            description="Start an AI-assisted conversation to quickly submit your civic issue with location, voice, and photo support."
            icon="📣"
            primary
          />
          <ActionCard
            href="/track"
            title="Track Existing Complaint"
            description="Check status timelines, follow updates, and monitor resolution progress for already filed complaints."
            icon="🔎"
          />
        </section>
      </main>
    </div>
  );
}
