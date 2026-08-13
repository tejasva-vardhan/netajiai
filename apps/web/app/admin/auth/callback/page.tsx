"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { completeAdminSignIn, isAdminOidcConfigured } from "../../../../lib/admin-auth";

export default function AdminAuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isAdminOidcConfigured()) {
      setError("Operator sign-in is not configured for this deployment.");
      return;
    }
    void completeAdminSignIn()
      .then(() => router.replace("/admin"))
      .catch(() => setError("Operator sign-in could not be completed. Please try again."));
  }, [router]);

  return (
    <main className="shell narrow-shell admin-shell">
      <p className="eyebrow">Operator sign-in</p>
      <h1>Sign-in complete kar rahe hain</h1>
      {error ? <p className="error" role="alert">{error}</p> : <p className="lede">Please wait…</p>}
    </main>
  );
}
