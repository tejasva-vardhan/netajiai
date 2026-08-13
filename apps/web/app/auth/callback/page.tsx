"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { completeCitizenSignIn, getCitizenReturnUrl, isCitizenOidcConfigured } from "../../../lib/citizen-auth";

export default function CitizenAuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  useEffect(() => {
    if (!isCitizenOidcConfigured()) {
      setError("Citizen sign-in is not configured for this deployment.");
      return;
    }
    void completeCitizenSignIn()
      .then((user) => router.replace(getCitizenReturnUrl(user)))
      .catch(() => setError("Citizen sign-in could not be completed. Please try again."));
  }, [router]);

  return (
    <main className="shell narrow-shell">
      <p className="eyebrow">Citizen sign-in</p>
      <h1>Sign-in complete kar rahe hain</h1>
      {error ? <p className="error" role="alert">{error}</p> : <p className="lede">Please wait…</p>}
    </main>
  );
}
