"use client";

import { useEffect } from "react";
import { getCitizenUserManager } from "../../../lib/citizen-auth";

/**
 * OIDC-client-ts loads this route in a hidden iframe when a refresh token is
 * unavailable. It must complete the iframe callback, not run the normal
 * redirect callback or navigate the citizen's conversation away.
 */
export default function CitizenSilentAuthCallbackPage() {
  useEffect(() => {
    const manager = getCitizenUserManager();
    if (!manager) return;
    void manager.signinSilentCallback().catch(() => {
      // The parent UserManager receives the renewal error event.
    });
  }, []);

  return null;
}
